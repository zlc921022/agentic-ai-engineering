# 检索增强工具箱（重点）
"""检索增强模块（ch8 对照加强版）。

目标：尽量把课程里的核心检索增强方法都放进来，并写成“小白可读注释”。

包含的方法：
1) run_rag_pipeline(...)        # 基础总入口（兼容课程风格）
2) query2doc(query)
3) hyde(query)
4) sub_question(query)
5) question_rewrite(query)
6) take_step_back(query)
7) 多索引检索（父子块/摘要/假设问题）
8) hybrid_retrieve(BM25 + 向量)
9) rerank（逐条 LLM + 批量 LLM）
10) iter_retgen
11) self_rag_answer（LangGraph）
"""
from typing import List, Literal, Tuple, Any, Dict, Optional

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate

from src.advanced_retrieval import SentenceWindowRetriever, SentenceWindowConfig, \
    AutoMergingRetriever, AutoMergingConfig
from src.client import QwenChatClient, DashScopeEmbeddingClient
from src.index_manager import ChromaIndexManager
from src.multi_index_retriever import MultiIndexRetriever
from src.rag_types import RerankMethod
from src.retrieval_types import RetrievalResult
from src.retrieval_util import (
    docs_to_context,
    _jieba_preprocess,
    _dedupe_docs,
    parse_index, )
from src.retrieval_util import parse_score, parse_lines
from src.self_rag_retriever import SelfRagRetriever


class RetrievalEnhancer:
    """检索增强工具箱（课程增强版）。
    小白可以把这个类理解成“策略仓库”：
    - 输入：用户问题、索引管理器、模型客户端
    - 处理：按不同策略改写问题、检索文档、重排文档
    - 输出：更适合交给 LLM 回答的上下文
    它本身不负责最终回答给用户。
    最终回答是由 `EnterpriseAssistantService` 调用这里的结果后，再统一组织 Prompt。
    """

    def __init__(self,
                 llm: QwenChatClient,
                 embedding_client: DashScopeEmbeddingClient,
                 index_manager: ChromaIndexManager
                 ):
        self.llm = llm
        self.embedding_client = embedding_client
        self.index_manager = index_manager

        self.bm25_retriever = None

        self.multi_index_retriever = MultiIndexRetriever(
            llm=self.llm,
            embedding_client=self.embedding_client,
            index_manager=self.index_manager
        )

        self.self_rag_retriever = SelfRagRetriever(
            llm=llm,
            index_manager=index_manager
        )

        # 高级检索器会创建额外的 Chroma collection。保持懒加载，避免基础
        # 检索策略在初始化阶段就承担不必要的索引成本，也便于注入轻量测试替身。
        self._sentence_window_retriever = None
        self._auto_merging_retriever = None

    def _get_sentence_window_retriever(self) -> SentenceWindowRetriever:
        if self._sentence_window_retriever is None:
            self._sentence_window_retriever = SentenceWindowRetriever(
                index_manager=self.index_manager,
                embedding_client=self.embedding_client,
                config=SentenceWindowConfig(),
            )
        return self._sentence_window_retriever

    def _get_auto_merging_retriever(self) -> AutoMergingRetriever:
        if self._auto_merging_retriever is None:
            self._auto_merging_retriever = AutoMergingRetriever(
                index_manager=self.index_manager,
                embedding_client=self.embedding_client,
                config=AutoMergingConfig(),
            )
        return self._auto_merging_retriever

    # ---------------------------------------------------------------------
    # 通用工具
    # ---------------------------------------------------------------------

    # ---------------------------------------------------------------------
    # 0.  最普通的向量检索-> 用户问题 -> 向量库 -> 返回 top_k 文档
    # 作为所有高级策略的对照组。先把这个写通，再写其他增强方法。
    # ---------------------------------------------------------------------
    def plain_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        """最基础的向量检索。
        这是所有增强策略的“对照组”：
        不改写问题、不做融合、不做重排，直接拿原问题去查向量库。
        """
        docs = self.index_manager._search_rules(query, k)
        return RetrievalResult(
            strategy="plain_retrieve",
            docs=docs,
            debug_note="基础向量检索"
        )

    # ---------------------------------------------------------------------
    # 1.  融合检索（BM25 + 向量）
    # 概念：混合检索：关键词检索 + 语义检索。
    # BM25：更擅长关键词命中，比如 VPN、OA、发票、税号
    # 向量：向量检索更擅长语义相似，比如“电脑坏了”和“设备故障”
    # 用法：适合作为企业知识库默认检索策略。
    # ---------------------------------------------------------------------
    def _get_bm25_retriever(self, k: int) -> BM25Retriever:
        # 懒加载
        if self.bm25_retriever is None:
            docs = self.index_manager._all_rule_documents()
            self.bm25_retriever = BM25Retriever.from_documents(
                documents=docs,
                preprocess_func=_jieba_preprocess
            )
            self.bm25_retriever.k = k
        return self.bm25_retriever

    def hybrid_retrieve(self,
                        query: str,
                        k: int = 4,
                        bm25_weight: float = 0.35,
                        vector_weight: float = 0.65
                        ) -> RetrievalResult:
        # bm25检索器
        bm25_retriever = self._get_bm25_retriever(k)
        # 向量检索器
        vector_retriever = self.index_manager.rule_store.as_retriever(search_kwargs={"k": k})
        # 融合检索器 是 LangChain 提供的融合检索器。
        ensemble_retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[bm25_weight, vector_weight],
        )
        # 执行混合检索
        docs = ensemble_retriever.invoke(query)
        # 去重
        new_docs = _dedupe_docs(docs)[:k]
        return RetrievalResult(
            strategy="hybrid_retrieve",
            docs=new_docs,
            debug_note=f"融合检索权重 bm25={bm25_weight}, vector={vector_weight}"
        )

    # ---------------------------------------------------------------------
    # 2. 查询改写
    # 概念：把短问题扩写成一段“像文档一样的话”，再拿这段话去检索。
    # 用法：适合问题太短、太口语化、关键词不足的时候。
    # ---------------------------------------------------------------------
    def query2doc(self, query: str) -> str:
        prompt = f"""
               请把用户问题扩写成一段像企业制度文档的短文。
               保留原意，补充可能出现的制度关键词。
               用户问题：{query}
               """
        pseudo_doc = self.llm.complete(prompt)
        return query + "\n" + pseudo_doc

    def query2doc_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        new_query = self.query2doc(query)
        docs = self.index_manager._search_rules(new_query, k)
        return RetrievalResult(
            strategy="query2doc_retrieve",
            docs=docs,
            debug_note="查询改写"
        )

    # ---------------------------------------------------------------------
    # 3. HyDE 假设文档向量
    # 概念：HyDE 是先生成一个“假设答案”，再把这个假设答案向量化去检索。
    # 用户问题 -> LLM 假设答案 -> embedding -> 向量检索
    # 用法：适合用户表达很口语，但你希望检索靠近正式制度文本。
    # ---------------------------------------------------------------------
    def hyde(self, query: str, include_query: bool = True) -> List[float]:
        prompt = f"""
                请基于常见企业制度，生成一段可能回答该问题的短文。
                问题：{query}
                """
        # 生成假设答案
        fake_answer = self.llm.complete(prompt, temperature=0.2)
        # 把假设答案转成向量
        hyde_vec = self.embedding_client.embed_query(fake_answer)
        if include_query:
            # 原始问题转成向量
            query_vec = self.embedding_client.embed_query(query)
            return [float((a + b) / 2) for a, b in zip(hyde_vec, query_vec)]
        return [float(x) for x in hyde_vec]

    def hyde_retrieve(self, query: str, k: int = 4, include_query: bool = True) -> RetrievalResult:
        vector = self.hyde(query, include_query)
        docs = self.index_manager._search_rules_by_vector(vector, k)
        return RetrievalResult(
            strategy="hyde_retrieve",
            docs=docs,
            debug_note="HyDE向量 + 原问题向量平均" if include_query else "仅HyDE向量检索"
        )

    # ---------------------------------------------------------------------
    # 4. 子问题查询
    # 思想：把复杂问题拆成多个子问题，分别检索，再合并结果。
    # ---------------------------------------------------------------------
    def sub_question(self, query: str) -> str:
        prompt = f"""
               请把下面问题拆成最多 3 个子问题，每行一个。
               问题：{query}
               """
        return self.llm.complete(prompt)

    def sub_question_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        questions = parse_lines(self.sub_question(query))
        all_docs = []
        for sub in questions:
            docs = self.index_manager._search_rules(sub, k)
            all_docs.extend(docs)
        docs = _dedupe_docs(all_docs)
        return RetrievalResult(
            strategy="sub_question_retrieve",
            docs=docs,
            debug_note="子问题查询"
        )

    # ---------------------------------------------------------------------
    # 5) 查询改写
    # 思想：把用户问题改写成更适合检索的正式表达。
    # 用法：企业员工助手里非常常用。用户说话口语化，但制度文档通常是正式表达。
    # ---------------------------------------------------------------------
    def question_rewrite(self, query: str) -> str:
        prompt = f"""
                 请把用户问题改写成适合检索企业制度文档的问题。
                 保留原意，补充关键词。
                 原问题：{query}
              """
        return self.llm.complete(prompt).strip()

    def question_rewrite_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        rewrite_query = self.question_rewrite(query)
        docs = self.index_manager._search_rules(rewrite_query.strip(), k)
        return RetrievalResult(
            strategy="question_rewrite",
            docs=docs,
            debug_note="查询改写"
        )

    # ---------------------------------------------------------------------
    # 6. Step-Back
    # 概念：Step-back 是“退一步”，把具体问题抽象成更通用的问题。
    # 用法：适合问题很具体、直接检索找不到制度条款时。
    # ---------------------------------------------------------------------
    def take_step_back(self, query: str) -> str:
        prompt = f"""
        请把下面问题抽象成一个更通用的制度问题。
        要求：
        1. 只输出一句话
        2. 30字以内
        3. 不要解释
        原问题：{query}
        """
        return self.llm.complete(prompt).strip()

    def step_back_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        abstract_query = self.take_step_back(query)
        docs = self.index_manager._search_rules(abstract_query, k)
        return RetrievalResult(
            strategy="step_back_retrieve",
            docs=docs,
            debug_note=f"step-back后检索, abstract_query-{abstract_query}"
        )

    # ---------------------------------------------------------------------
    # 7. 多索引检索（父子块 / 摘要 / 假设问题）
    # ---------------------------------------------------------------------

    def parent_child_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        return self.multi_index_retriever.parent_child_retrieve(query, k)

    def summary_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        return self.multi_index_retriever.summary_retrieve(query, k)

    def hypothetical_question_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        return self.multi_index_retriever.hypothetical_question_retrieve(query, k)

    def multi_index_retrieve(self, query: str, k: int = 4) -> RetrievalResult:
        return self.multi_index_retriever.multi_index_retrieve(query, k)

    # ---------------------------------------------------------------------
    # 8. rerank（逐条 LLM + 批量 LLM）
    # 思想：把问题和每篇候选文档交给大模型，让它判断相关性，输出分数。
    # ---------------------------------------------------------------------
    def rerank_with_llm(self, query: str, docs: List[Document], top_n: int = 4) -> List[Document]:
        scored_docs = []
        for doc in docs:
            prompt = f"""
                   请评估下面文档对问题的相关性，输出 0-100 的整数。
                   问题：
                   {query}
                   文档：
                   {doc.page_content}
                   只输出数字。
                   """
            result = self.llm.complete(prompt)
            score = parse_score(result)
            scored_docs.append((score, doc))
        print(f"文档相关性分数-{scored_docs}")
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored_docs[:top_n]]

    # 批量LLM Rerank
    def rerank_with_llm_batch(self, query: str, docs: List[Document], top_n: int = 4) -> List[Document]:
        doc_text = ""
        for i, doc in enumerate(docs, start=1):
            doc_text += f"\n[{i}], {doc.page_content}\n"
        print(f"doc_text-{doc_text}")
        prompt = f"""
           请根据用户问题，对候选文档按相关性排序。
           用户问题：
           {query}
           候选文档：
           {doc_text}
           请只输出最相关的文档编号，最多 {top_n} 个。
           格式示例：
           2,4,1
           """
        result = self.llm.complete(prompt, temperature=0)
        print(f"文档编号result-{result}")
        indexes = parse_index(result)
        reranked_docs = []
        for idx in indexes:
            if 1 <= idx <= len(docs):
                reranked_docs.append(docs[idx - 1])
        return reranked_docs[:top_n]

    def rerank(self,
               query: str,
               docs: List[Document],
               top_n: int = 4,
               method: RerankMethod = RerankMethod.LLM
               ) -> Tuple[List[Document], str]:
        if method == RerankMethod.LLM_BATCH:
            return self.rerank_with_llm_batch(query, docs, top_n), "rank_with_llm_batch"
        else:
            return self.rerank_with_llm(query, docs, top_n), "rank_with_llm"

    # ---------------------------------------------------------------------
    # 9. iter_retgen（课程同名）
    # 概念：迭代式检索生成：
    # 用法：适合复杂问题，一轮检索不够时。
    # ---------------------------------------------------------------------
    def iterative_retrieve(self, query: str, k: int = 4, max_iters: int = 2) -> RetrievalResult:
        """
        第一轮先用原问题检索
        根据第一轮文档生成一个简短草稿
        第二轮用“原问题 + 草稿”再检索一次
        最后返回第二轮检索到的文档
        """
        # 每一轮生成的草稿答案
        iter_answer = ""
        docs = []
        for i in range(max_iters):
            context_query = (query + " " + iter_answer).strip()
            docs = self.index_manager._search_rules(context_query, k)
            if i < max_iters - 1:
                # 如果不是最后一轮，就生成草稿，供下一轮检索使用。
                # 为什么最后一轮不生成草稿？
                # 因为最后一轮之后已经不再检索了，生成草稿也用不上，浪费一次LLM调用。
                context = docs_to_context(docs)
                prompt = f"""
                请根据上下文给出简短答案，50字以内\n
                问题：{query}\n,
                上下文：\n{context}\n
                """
                iter_answer = self.llm.complete(prompt, temperature=0.2)
        return RetrievalResult(
            strategy="iterative_retrieve",
            docs=docs,
            debug_note=f"迭代检索轮数={max_iters}"
        )

    def self_rag_answer(self, query: str, k: int = 4) -> Dict[str, Any]:
        return self.self_rag_retriever.self_rag_answer(query, k)

    def self_rag_answer_langgraph(self, query: str, k: int = 4) -> Dict[str, Any]:
        return self.self_rag_retriever.self_rag_answer_langgraph(query, k)

    def sentence_window_retriever(self, query: str, k: int = 4) -> RetrievalResult:
        docs = self._get_sentence_window_retriever().retrieve(query, k)
        return RetrievalResult(
            strategy="sentence_window_retriever",
            docs=docs,
            debug_note="sentence_window"
        )

    def auto_merging_retriever(self, query: str, k: int = 4) -> RetrievalResult:
        docs = self._get_auto_merging_retriever().retrieve(query, k)
        return RetrievalResult(
            strategy="auto_merging_retriever",
            docs=docs,
            debug_note="auto_merging"
        )

    # ---------------------------------------------------------------------
    # 1) 基础总入口（兼容课程风格）
    # ---------------------------------------------------------------------
    """基础总入口（课程风格）。
        思想：问题 -> 检索文档 -> 拼上下文 -> 生成答案, 用户问什么，就拿什么检索，然后根据检索结果回答。
        参数说明（和你提到的一致）：
        1. query: 用户真实问题
        2. context_query: 用来检索的查询（可被改写）
        3. k: 取前k条文档
        4. context_query_type:
           - query: 文本检索
           - vector: 直接用向量检索（HyDE常用）
           - doc: 直接传文档列表（融合检索/rerank后常用）
        5. stream: 是否流式输出
    """

    def run_rag_pipeline(self,
                         query: str,
                         context_query: str,
                         k: int = 4,
                         context_query_type: Literal["query", "vector", "doc"] = "query",
                         stream: bool = False,
                         prompt_template: Optional[str] = None,
                         temperature: float = 0.1
                         ) -> Tuple[Any, str]:
        if context_query_type == "query":
            docs = self.index_manager._search_rules(context_query, k)
        elif context_query_type == "vector":
            docs = self.index_manager._search_rules_by_vector(context_query, k)
        else:
            docs = list(context_query)
        context = docs_to_context(docs)

        template = prompt_template or (
            "你是企业员工助手，需要根据上下文回答问题。\n"
            "若上下文不足，先明确说不知道。\n"
            "问题: {question}\n"
            "上下文:\n{context}\n"
            "回答:"
        )
        prompt = PromptTemplate(
            template=template,
            input_variables=["question", "context"],
        )
        llm_prompt = prompt.format(question=query, context=context)
        if stream:
            return self.llm.stream(llm_prompt, temperature=temperature), context

        answer = self.llm.complete(llm_prompt, temperature=temperature)
        return answer, context
