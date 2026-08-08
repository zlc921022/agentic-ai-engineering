# 父子块 / 摘要 / 假设问题 / multi-index 融合
from langchain_chroma import Chroma
from langchain_classic.retrievers import MultiVectorRetriever
from langchain_core.documents import Document
from langchain_core.stores import InMemoryByteStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from enterprise_employee_assistant.src.client import QwenChatClient, DashScopeEmbeddingClient
from enterprise_employee_assistant.src.index_manager import ChromaIndexManager
from enterprise_employee_assistant.src.retrieval_util import parse_lines, _dedupe_docs
from enterprise_employee_assistant.src.retrieval_types import RetrievalResult


class MultiIndexRetriever:

    def __init__(self,
                 llm: QwenChatClient,
                 embedding_client: DashScopeEmbeddingClient,
                 index_manager: ChromaIndexManager
                 ):
        self.llm = llm
        self.embedding_client = embedding_client
        self.index_manager = index_manager

        self._parent_child_retriever = None
        self._summary_retriever = None
        self._hq_retriever = None
        self._multi_index_ready = False

    """
    确认索引已经建立了
    """

    def _ensure_multi_index(self):
        if self._multi_index_ready:
            return
        self._build_parent_child_retriever()
        self._build_summary_retriever()
        self._build_hypothetical_question_retriever()
        self._multi_index_ready = True

    """
    构建一个“父子块检索器”。
    父子块索引：子块检索，返回父文档。
    为什么要这样做：
    - 父文档：信息更完整，适合最终回答
    - 子文档：颗粒度更细，更容易被准确命中
    所以这里采用“检索时查小块，返回时给大块”的思路。
    """

    def _build_parent_child_retriever(self):
        if self._parent_child_retriever is not None:
            return

        parent_docs = self.index_manager._all_rule_documents()
        parent_ids = [f"parent-{i}" for i in range(len(parent_docs))]
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=260,
            chunk_overlap=40
        )
        id_key = "doc_id"
        child_docs = []
        for parent_id, parent_doc in zip(parent_ids, parent_docs):
            pieces = splitter.split_documents([parent_doc])
            if not pieces:
                pieces = [parent_doc]
            for piece in pieces:
                piece.metadata[id_key] = parent_id
                piece.metadata["index_type"] = "parent_child"
                child_docs.append(piece)
        collection_name = "employee_rules_parent_child"
        self.index_manager.reset_collection(collection_name)
        child_db = Chroma.from_documents(
            documents=child_docs,
            collection_name=collection_name,
            client=self.index_manager.client,
            embedding=self.embedding_client.get_embedding_function()
        )
        store = InMemoryByteStore()
        retriever = MultiVectorRetriever(
            vectorstore=child_db,
            byte_store=store,
            id_key=id_key,
        )
        retriever.docstore.mset(list(zip(parent_ids, parent_docs)))
        self._parent_child_retriever = retriever

    """摘要索引：先检索摘要，再映射回父文档。
    适合“问概览、问原则、问总体要求”的场景。
    用户问题未必和原文逐字匹配，但通常和摘要更接近。
    """

    def _build_summary_retriever(self):
        if self._summary_retriever is not None:
            return

        parent_docs = self.index_manager._all_rule_documents()
        parent_ids = [f"parent-{i}" for i in range(len(parent_docs))]
        id_key = "doc_id"
        summary_docs = []
        for parent_id, parent_doc in zip(parent_ids, parent_docs):
            # 先让 LLM 给每个原始文档写一个“更像搜索标签”的摘要版本。
            prompt = (
                "请将下面制度文档做50字以内摘要，并给3-5个关键词。\n"
                f"文档:\n{parent_doc.page_content}"
            )
            summary = self.llm.complete(prompt, temperature=0.2)
            summary_docs.append(
                Document(
                    page_content=summary,
                    metadata={
                        "index_type": "summary",
                        id_key: parent_id,
                    }
                )
            )
        collection_name = "employee_rules_summary"
        self.index_manager.reset_collection(collection_name)
        summary_db = Chroma.from_documents(
            documents=summary_docs,
            collection_name=collection_name,
            client=self.index_manager.client,
            embedding=self.embedding_client.get_embedding_function()
        )
        store = InMemoryByteStore()
        retriever = MultiVectorRetriever(
            vectorstore=summary_db,
            byte_store=store,
            id_key=id_key,
        )
        retriever.docstore.mset(list(zip(parent_ids, parent_docs)))
        self._summary_retriever = retriever

    """假设问题索引：让模型为每段文档生成“可能会被问的问题”。
       这个方法的核心思想是：
       文档不只存“原文”，还存“用户可能怎么问”。
       这样当用户使用口语化表达时，更容易命中到对应制度。
   """

    def _build_hypothetical_question_retriever(self):
        if self._hq_retriever is not None:
            return

        parent_docs = self.index_manager._all_rule_documents()
        parent_ids = [f"parent-{i}" for i in range(len(parent_docs))]
        id_key = "doc_id"
        hq_docs = []
        for parent_id, parent_doc in zip(parent_ids, parent_docs):
            prompt = (
                "请基于以下制度文档，生成3个用户可能提出的问题，每行一个。\n"
                f"文档:\n{parent_doc.page_content}"
            )
            results = self.llm.complete(prompt, temperature=0.2)
            questions = parse_lines(results)
            if not questions:
                questions = [parent_doc.page_content[:30]]
            for question in questions:
                hq_docs.append(
                    Document(
                        page_content=question,
                        metadata={
                            "index_type": "hq",
                            id_key: parent_id,
                        }
                    )
                )
        collection_name = "employee_rules_hq"
        self.index_manager.reset_collection(collection_name)
        hq_db = Chroma.from_documents(
            documents=hq_docs,
            collection_name=collection_name,
            client=self.index_manager.client,
            embedding=self.embedding_client.get_embedding_function()
        )
        store = InMemoryByteStore()
        retriever = MultiVectorRetriever(
            vectorstore=hq_db,
            byte_store=store,
            id_key=id_key,
        )
        retriever.docstore.mset(list(zip(parent_ids, parent_docs)))
        self._hq_retriever = retriever

        # ---------------------------------------------------------------------
        # 7. 多索引检索（父子块 / 摘要 / 假设问题）
        # ---------------------------------------------------------------------

    def parent_child_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        self._build_parent_child_retriever()
        docs = [] if self._parent_child_retriever is None else  list(self._parent_child_retriever.invoke(query))
        docs = _dedupe_docs(docs)[:k]
        return RetrievalResult(
            strategy="parent_child_retrieve",
            docs=docs,
            debug_note="父子块索引检索"
        )

    def summary_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        self._build_summary_retriever()
        docs = [] if self._summary_retriever is None else list(self._summary_retriever.invoke(query))
        docs = _dedupe_docs(docs)[:k]
        return RetrievalResult(
            strategy="summary_retrieve",
            docs=docs,
            debug_note="摘要索引检索"
        )

    def hypothetical_question_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        self._build_hypothetical_question_retriever()
        docs = [] if self._hq_retriever is None else list(self._hq_retriever.invoke(query))
        docs = _dedupe_docs(docs)[:k]
        return RetrievalResult(
            strategy="hypothetical_question_retrieve",
            docs=docs,
            debug_note="假设问题索引检索"
        )

    """把三路多索引结果融合。
       这一步不是重新训练模型，而是“多视角召回”：
       - 父子块视角
       - 摘要视角
       - 假设问题视角
       最后再把三路结果去重、截断。
    """

    def multi_index_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        self._ensure_multi_index()
        docs = []

        if self._parent_child_retriever is None:
            docs.extend([])
        else:
            docs.extend(list(self._parent_child_retriever.invoke(query)))

        if self._summary_retriever is None:
            docs.extend([])
        else:
            docs.extend(list(self._summary_retriever.invoke(query)))

        if self._hq_retriever is None:
            docs.extend([])
        else:
            docs.extend(list(self._hq_retriever.invoke(query)))

        docs = _dedupe_docs(docs)[:k]
        return RetrievalResult(
            strategy="multi_index_retrieve",
            docs=docs,
            debug_note="父子块+摘要+假设问题融合"
        )
