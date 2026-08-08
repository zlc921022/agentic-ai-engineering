"""LlamaIndex 高级 RAG 检索增强策略。

这个模块和 `retrieval_enhance.py` / `advanced_retrieval.py` 是对照关系：

- `retrieval_enhance.py`：项目原生策略仓库，主要用 LangChain + Chroma + 手写逻辑。
- `advanced_retrieval.py`：手写版 sentence-window / auto-merging，方便理解算法思想。
- 本模块：尽量用 LlamaIndex 官方组件实现同类高级 RAG 方法，方便学习框架原生 API。

重要边界：
本模块只负责“检索出更好的上下文”，不负责最终回答。
最终答案仍交给 `EnterpriseAssistantService`，这样所有策略都能走同一套生成 Prompt。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Tuple, Optional, List, Sequence, Dict

from langchain_core.documents import Document

from src.client import DashScopeEmbeddingClient, QwenChatClient
from src.config import Config
from src.index_manager import ChromaIndexManager
from src.retrieval_util import _missing_dependency_message, _dedupe_docs


def _node_to_langchain_doc(node_with_score: Any) -> Document:
    node = getattr(node_with_score, "node", node_with_score)
    score = getattr(node_with_score, "score", None)

    if hasattr(node, "get_content"):
        text = node.get_content()
    else:
        text = getattr(node, "text", "") or str(node)

    metadata = dict(getattr(node, "metadata", {}) or {})
    metadata["llama_node_id"] = getattr(node, "node_id", "")

    if score is not None:
        metadata["llama_score"] = float(score)

    return Document(page_content=text, metadata=metadata)


def _nodes_to_docs(nodes: List[Any], k: int) -> List[Document]:
    return _dedupe_docs([_node_to_langchain_doc(node) for node in nodes])[:k]


@dataclass
class LlamaIndexRetrievalConfig:
    """LlamaIndex 高级检索参数。
    这些参数大多和课程/官方示例保持同一类思路，但根据企业制度文档
    做了轻量调整：
    """
    # 命中句子前后各带几句
    sentence_window_size: int = 2
    # 大多数检索器的初召回数量。
    similarity_top_k: int = 6
    # auto-merging 的父子层级 chunk 尺寸
    auto_merge_chunk_sizes: Tuple[int, ...] = (1024, 512, 128)
    # query fusion 自动生成多少个改写查询
    fusion_num_queries: int = 4
    # 先多召回多少候选，再做 LlamaIndex rerank
    rerank_candidate_k: int = 12
    # 切割大小
    recursive_chunk_size: int = 512
    # 切割重叠数量
    recursive_chunk_overlap: int = 80


class LlamaIndexRetrievalEnhancer:
    """LlamaIndex 官方组件版检索增强器。
    每个公开方法都对应一种 `llama_*` 策略：
    - `llama_plain_retrieve`：基础向量检索，对照 `RetrievalEnhancer.plain_retrieve`。
    - `llama_sentence_window_retrieve`：对照 `advanced_retrieval.py` 手写 sentence-window。
    - `llama_auto_merging_retrieve`：对照 `advanced_retrieval.py` 手写 auto-merging。
    - `llama_hyde_retrieve`：对照 `RetrievalEnhancer.hyde_retrieve`。
    - `llama_query_fusion_retrieve`：LlamaIndex 多查询融合 / RAG Fusion。
    - `llama_hybrid_retrieve`：LlamaIndex BM25/keyword + vector 混合检索。
    - `llama_rerank_retrieve`：LlamaIndex node postprocessor / reranker。
    - `llama_router_retrieve`：LlamaIndex router，在多个检索器之间选择。
    - `llama_recursive_retrieve`：LlamaIndex RecursiveRetriever，先查文档入口再深入子索引。
    - `llama_summary_retrieve`：LlamaIndex SummaryIndex，适合总结型问题。
    - `llama_auto_retrieval_retrieve`：metadata filter + semantic search。
    - `llama_graph_retrieve`：KnowledgeGraph / PropertyGraph 风格 GraphRAG。
    """

    def __init__(
            self,
            config: Config,
            index_manager: ChromaIndexManager,
            embedding_client: DashScopeEmbeddingClient,
            llm: QwenChatClient,
            retrieval_config: LlamaIndexRetrievalConfig
    ):
        self.config = config
        self.index_manager = index_manager
        self.embedding_client = embedding_client
        self.llm = llm
        self.retrieval_config = retrieval_config

        self._embed_model: Optional[Any] = None
        self._llama_llm: Optional[Any] = None

        self._all_rule_documents: Optional[List[Any]] = None
        self._all_rule_nodes: Optional[List[Any]] = None
        self._rule_vector_index: Optional[Any] = None

        self._sentence_window_index: Optional[Any] = None
        self._auto_merging_retriever: Optional[Any] = None
        self._summary_index: Optional[Any] = None
        self._recursive_retriever: Optional[Any] = None
        self._graph_index: Optional[Any] = None

    def _get_embed_model(self) -> Any:
        """把项目 DashScope embedding 包装成 LlamaIndex BaseEmbedding。
        对照点：
        `retrieval_enhance.py` 里的手写版直接让 Chroma 调用
        `DashScopeEmbeddingClient`；这里则把同一个 embedding 客户端
        包装成 LlamaIndex 需要的接口，保证两边使用同一套向量模型。
        """
        if self._embed_model is not None:
            return self._embed_model

        try:
            from llama_index.core.base.embeddings.base import BaseEmbedding
            from pydantic import PrivateAttr
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("pydantic")) from e

        model_name = self.embedding_client.config.embedding_model

        # 转成项目里面的向量库实现，做一层适配器转化
        class DashScopeLlamaIndexEmbedding(BaseEmbedding):
            """LlamaIndex BaseEmbedding -> 项目 DashScopeEmbeddingClient。"""

            _client: DashScopeEmbeddingClient = PrivateAttr()

            def __init__(self, client: DashScopeEmbeddingClient):
                super().__init__(model_name=model_name)
                self._client = client

            def _get_query_embedding(self, text: str) -> List[float]:
                return self._client.embed_query(text)

            async def _aget_query_embedding(self, text: str) -> List[float]:
                return self._get_query_embedding(text)

            def _get_text_embedding(self, text: str) -> List[float]:
                return self._client.embed_query(text)

            async def _aget_text_embedding(self, text: str) -> List[float]:
                return self._get_query_embedding(text)

            def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
                return self._client.embed_documents(texts)

            async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
                return self._get_text_embeddings(texts)

        self._embed_model = DashScopeLlamaIndexEmbedding(self.embedding_client)
        return self._embed_model

    def _get_llama_llm(self) -> Any:
        if self._llama_llm is not None:
            return self._llama_llm

        try:
            from llama_index.core.llms import (
                CompletionResponse,
                CompletionResponseGen,
                CustomLLM,
                LLMMetadata,
            )
            from llama_index.core.llms.callbacks import llm_completion_callback
            from pydantic import PrivateAttr
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index llm")) from e

        qwen_client = self.llm

        # 转成项目里面的千问大模型实现，做一层适配器转化
        class QwenLlamaxIndexLLM(CustomLLM):
            """LlamaIndex CustomLLM -> 项目 QwenChatClient。"""
            _client = PrivateAttr()
            model_name: str = qwen_client.config.chat_model
            context_window: int = 8192
            num_output: int = 1024

            def __init__(self, client: QwenChatClient):
                super().__init__(
                    context_window=8192,
                    num_output=1024,
                    model_name=client.config.chat_model
                )
                self._client = client

            @property
            def metadata(self) -> LLMMetadata:
                return LLMMetadata(
                    context_window=self.context_window,
                    num_output=self.num_output,
                    model_name=self.model_name
                )

            @llm_completion_callback()
            def complete(
                    self,
                    prompt: str,
                    formatted: bool = False,
                    **kwargs: Any
            ) -> CompletionResponse:
                response = self._client.complete(
                    prompt=prompt,
                    temperature=kwargs.get("temperature", 0.0),
                    max_tokens=kwargs.get("max_tokens", self.num_output),
                )
                return CompletionResponse(
                    text=response,
                )

            @llm_completion_callback()
            def stream_complete(
                    self,
                    prompt: str,
                    formatted: bool = False,
                    **kwargs: Any
            ) -> CompletionResponseGen:
                response = ""
                for delta in self._client.stream(
                        prompt=prompt,
                        temperature=kwargs.get("temperature", 0.0),
                        max_tokens=kwargs.get("max_tokens", self.num_output),
                ):
                    response += delta
                    yield CompletionResponse(
                        text=response,
                        delta=delta,
                    )

        self._llama_llm = QwenLlamaxIndexLLM(qwen_client)
        return self._llama_llm

    # 读取原始所有制度文件
    def _get_all_rule_documents(self) -> List[Any]:
        """读取企业全部制度原文，并转换成 LlamaIndex Document。
           注意这里故意读原始文件，而不是复用 Chroma 已切好的 chunk。
           因为 LlamaIndex 的 sentence-window、auto-merging、recursive
           等方法本身就要演示“如何切分、如何建立节点关系”。
        """
        if self._all_rule_documents is not None:
            return self._all_rule_documents

        try:
            from llama_index.core import (
                Document as LlamaDocument,
            )
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index document")) from e

        files: List[Path] = []
        for pattern in ("*.txt", "*.md"):
            files.extend(self.config.data_rule_dir.glob(pattern))

        docs = []
        for file in files:
            text = file.read_text(encoding="utf-8")
            if not text:
                continue
            docs.append(
                LlamaDocument(
                    text=text,
                    metadata={
                        "source": file.name,
                        "file_stem": file.stem,
                        "source_type": "rules",
                        "adapter": "llama_index"
                    }
                )
            )
        self._all_rule_documents = docs
        return docs

    # 获取全部已经 chunk 过的 rule nodes
    def _get_all_rule_nodes(self) -> List[Any]:
        """获取全部制度文档切分后的 LlamaIndex chunk nodes。
           这些 nodes 作为 plain、hybrid、fusion、rerank 等基于普通 chunk
           的检索策略的共享输入；首次调用时从制度文档切分并缓存。
        """
        if self._all_rule_nodes is not None:
            return self._all_rule_nodes
        try:
            from llama_index.core.node_parser import (
                SentenceSplitter,
            )
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index sentence_splitter")) from e

        all_rule_documents = self._get_all_rule_documents()
        splitter = SentenceSplitter(
            chunk_size=self.retrieval_config.recursive_chunk_size,
            chunk_overlap=self.retrieval_config.recursive_chunk_overlap,
        )

        nodes = splitter.get_nodes_from_documents(all_rule_documents)
        self._all_rule_nodes = nodes
        return nodes

    def _get_rule_vector_index(self) -> Any:
        """获取基于全部制度 nodes 构建的 LlamaIndex VectorStoreIndex。
        该索引用于普通向量召回，并作为 query fusion、hybrid、rerank
        等策略的共享向量检索基础；首次调用时构建并缓存。
        """
        if self._rule_vector_index is not None:
            return self._rule_vector_index
        try:
            from llama_index.core import VectorStoreIndex
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index sentence_splitter")) from e

        vector_index = VectorStoreIndex(
            nodes=self._get_all_rule_nodes(),
            embed_model=self._get_embed_model()
        )

        self._rule_vector_index = vector_index
        return vector_index

    def _retrieve_rule_vector_nodes(self, query: str, k: int) -> List[Any]:
        """使用制度向量索引召回相似 nodes。
           这是 plain 向量检索的核心步骤，也作为 fusion、hybrid、rerank
           等策略中的向量召回分支复用。
        """
        vector_index = self._get_rule_vector_index()
        retriever = vector_index.as_retriever(similarity_top_k=k)
        return list(retriever.retrieve(query))

    # _fuse   做什么：融合
    # _nodes  融合什么：nodes
    # _by_rrf 怎么融合：Reciprocal Rank Fusion
    @staticmethod
    def _fuse_nodes_by_rrf(node_lists: Sequence[Sequence[Any]], top_k: int) -> List[Any]:
        """使用 Reciprocal Rank Fusion 合并多路 node 检索结果。
        同一个 node 在多路结果中出现时会累加排名分数；排名越靠前，
        单路贡献越高。该方法用于 QueryFusionRetriever 不可用时的兜底融合。
        多路检索结果
            -> 按 node_id 去重
            -> 用 RRF 累加排名分数
            -> 按融合分数倒序排序
            -> 返回 top k nodes
        """
        # score(d) = sum(1 / (k + rank_i))  Reciprocal Rank Fusion 的经典打分公式
        # 60 是RRF 里的平滑常数 k
        rrf_rank_constant = 60.0
        scored: Dict[str, Tuple[float, Any]] = {}
        for nodes in node_lists:
            for rank, node in enumerate(nodes, start=1):
                actual_node = getattr(node, "node", node)
                node_id = getattr(actual_node, "node_id", "") or str(id(actual_node))
                # 取这个 node 之前已经累计的分数, 如果没有就是默认0.0
                old_score, _ = scored.get(node_id, (0.0, node))
                # 这句是 RRF 的核心
                new_score = old_score + (1.0 / (rank + rrf_rank_constant))
                # 把最新累计分数放回字典
                scored[node_id] = (new_score, node)

        sorted_items = sorted(
            # [(0.044, node_a), (0.016, node_b)]
            scored.values(),
            # key=lambda item: item[0] 表示按 tuple 的第一个元素排序，也就是按 RRF 分数排序。
            key=lambda item: item[0],
            # 表示分数从高到低排
            reverse=True,
        )[:top_k]
        result = []
        for score, node in sorted_items:
            result.append(node)
        return result

    def _generate_query_fusion_queries(self, query: str, count: int) -> List[str]:
        """
        用项目 LLM 生成多路检索 query，供 query fusion 兜底使用。
        """
        prompt = (
            "请把用户问题改写成多个适合检索企业制度文档的问题。\n"
            f"用户问题: {query}\n"
            f"要求：最多 {count} 个，每行一个，不要编号。"
        )
        text = self.llm.complete(prompt, temperature=0.2, max_tokens=512)
        queries = [line.strip("-• \t") for line in text.splitlines() if line.strip()]
        queries = [item for item in queries if item and item != query]
        return queries[:count]

    # ------------------------------------------------------------------
    # LlamaIndex 检索策略
    # ------------------------------------------------------------------
    def plain_retrieve(self, query: str, k: int) -> List[Document]:
        nodes = self._retrieve_rule_vector_nodes(query, k)
        return _nodes_to_docs(nodes, k)

    def _build_sentence_window_index(self) -> Any:

        if self._sentence_window_index is not None:
            return self._sentence_window_index

        try:
            from llama_index.core import VectorStoreIndex
            from llama_index.core.node_parser import SentenceWindowNodeParser
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index sentence_splitter")) from e

        # 分割器，负责把文档切成句子，然后句子前后带几句内容放到metadata的window中
        parser = SentenceWindowNodeParser(
            window_size=self.retrieval_config.sentence_window_size,
            window_metadata_key="window",
            original_text_metadata_key="sentence_window_text"
        )
        # 将切分好的句子转成node节点
        nodes = parser.get_nodes_from_documents(self._get_all_rule_documents())
        # 入库
        sentence_index = VectorStoreIndex(
            nodes=nodes,
            embed_model=self._get_embed_model()
        )
        self._sentence_window_index = sentence_index

        return sentence_index

    def sentence_window_retrieve(self, query: str, k: int) -> List[Document]:

        try:
            from llama_index.core.postprocessor import MetadataReplacementPostProcessor
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index postprocessor")) from e

        index = self._build_sentence_window_index()
        # 得到句子节点
        row_nodes = index.as_retriever(
            similarity_top_k=max(k, self.retrieval_config.similarity_top_k)
        ).retrieve(query)
        # 将句子节点里面的内容替换为metadata的window前后上下文
        processor = MetadataReplacementPostProcessor(
            target_metadata_key="window"
        )
        nodes = processor.postprocess_nodes(row_nodes)

        return _nodes_to_docs(nodes, k)

    def _get_auto_merging_retriever(self) -> Any:

        if self._auto_merging_retriever is not None:
            return self._auto_merging_retriever

        try:
            from llama_index.core.node_parser import HierarchicalNodeParser
            from llama_index.core import VectorStoreIndex
            from llama_index.core.storage.docstore import SimpleDocumentStore
            from llama_index.core.retrievers import AutoMergingRetriever
            from llama_index.core.storage.storage_context import StorageContext
            from llama_index.core.node_parser import get_leaf_nodes
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index postprocessor")) from e

        """获取 LlamaIndex AutoMergingRetriever，首次调用时构建并缓存。
        该 retriever 先基于最小叶子节点做向量召回，再根据父子节点命中比例
        自动把多个相关子节点合并成更大的父节点上下文。
        """
        parser = HierarchicalNodeParser.from_defaults(
            chunk_sizes=list(self.retrieval_config.auto_merge_chunk_sizes)
        )
        # 这一步会把文档切成多层,每个小节点会记录自己的 parent 关系
        all_nodes = parser.get_nodes_from_documents(self._get_all_rule_documents())
        # 获取叶子节点
        leaf_nodes = get_leaf_nodes(all_nodes)
        # 虽然数据库只存叶子节点，但是所有节点也要保存，后面叶子节点找父节点需要
        docstore = SimpleDocumentStore()
        # 保存所有节点
        docstore.add_documents(all_nodes)
        # 构造上下文对象
        storage_context = StorageContext.from_defaults(docstore=docstore)
        # 存叶子节点
        leaf_index = VectorStoreIndex(
            nodes=leaf_nodes,
            storage_context=storage_context,
            embed_model=self._get_embed_model()
        )
        leaf_retriever = leaf_index.as_retriever(
            similarity_top_k=self.retrieval_config.similarity_top_k
        )
        # 内部自动找父节点是否合并
        auto_merging_retriever = AutoMergingRetriever(
            leaf_retriever,
            storage_context,
            verbose=True
        )
        self._auto_merging_retriever = auto_merging_retriever

        return auto_merging_retriever

    """
    核心思想：先用小 chunk 做精准向量召回；如果同一个父 chunk 下面命中了足够多的小 chunk，就把这些小 chunk 替换成更大的父 chunk 返回。
    """

    def auto_merging_retrieve(self, query: str, k: int) -> List[Document]:
        auto_merging_retriever = self._get_auto_merging_retriever()
        # 检索的话如果父节点下多个字节点命中, 内部自动合并父节点
        nodes = auto_merging_retriever.retrieve(query)
        return _nodes_to_docs(nodes, k)

    def hyde_retrieve(
            self,
            query: str,
            k: int,
            include_query: bool = True
    ) -> List[Document]:
        try:
            from llama_index.core.query_engine import TransformQueryEngine
            from llama_index.core.indices.query.query_transform import HyDEQueryTransform
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index hyde")) from e

        vector_index = self._get_rule_vector_index()
        # 把向量索引包装成可以查询的 query engine，
        query_engine = vector_index.as_query_engine(
            llm=self._get_llama_llm(),
            similarity_top_k=self.retrieval_config.similarity_top_k,
        )
        # 创建 HyDE 查询转换器，让 LLM 生成一段 hypothetical document，假设文档/假设答案
        hyde_query_transform = HyDEQueryTransform(
            llm=self._get_llama_llm(),
            include_original=include_query
        )
        #  TransformQueryEngine 本身不负责检索，它只是先改写 query，再交给里面的 query_engine
        trans_from_query_engine = TransformQueryEngine(
            query_engine=query_engine,
            query_transform=hyde_query_transform,
        )
        # 执行查询
        response = trans_from_query_engine.query(query)
        # 获取检索到的节点
        source_nodes = list(getattr(response, "source_nodes", []) or [])
        if source_nodes:
            return _nodes_to_docs(source_nodes, k)

        return []

    def _get_bm25_retriever(self, k: int) -> Any:
        try:
            from llama_index.retrievers.bm25 import BM25Retriever
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("bm25")) from e

        return BM25Retriever.from_defaults(
            nodes=self._get_all_rule_nodes(),
            similarity_top_k=k,
        )

    def hybrid_retrieve(self, query: str, k: int) -> List[Document]:
        """LlamaIndex 混合检索：BM25/keyword + Vector。
           对照 `RetrievalEnhancer.hybrid_retrieve()`：
           - 原生版：LangChain BM25Retriever + Chroma retriever + EnsembleRetriever。
           - LlamaIndex 版：LlamaIndex BM25Retriever/KeywordTableIndex + VectorStoreIndex，
             再通过 QueryFusionRetriever 或 reciprocal-rank 兜底融合。
        """
        try:
            from llama_index.core.retrievers import QueryFusionRetriever
            from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("bm25")) from e

        vector_retriever = self._get_rule_vector_index().as_retriever(
            similarity_top_k=max(k, self.retrieval_config.similarity_top_k),
        )
        bm25_retriever = self._get_bm25_retriever(k)

        fusion_retriever = QueryFusionRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            llm=self._get_llama_llm(),
            similarity_top_k=k,
            num_queries=1,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            use_async=False,
            verbose=True,
        )
        nodes = fusion_retriever.retrieve(query)

        return _nodes_to_docs(nodes, k)

    def rerank_retrieve(self, query: str, k: int) -> List[Document]:
        """LlamaIndex rerank。
           对照 `RetrievalEnhancer.rerank()`：
           - 原生版：把候选文档交给项目 LLM 打分排序。
           - LlamaIndex 版：先用 VectorStoreIndex 多召回，再用 `LLMRerank`
             这样的 Node Postprocessor 重新排序。
        """
        try:
            from llama_index.core.postprocessor import LLMRerank
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index hyde")) from e

        candidate_k = max(k, self.retrieval_config.rerank_candidate_k)
        # 获取所有节点
        raw_nodes = self._retrieve_rule_vector_nodes(query, candidate_k)
        # rerank对象
        llm_rank = LLMRerank(
            llm=self._get_llama_llm(),
            top_n=k,
            choice_batch_size=5
        )
        nodes = llm_rank.postprocess_nodes(raw_nodes, query_str=query)
        return _nodes_to_docs(nodes, k)

    def _get_summary_index(self) -> Any:
        """构建 SummaryIndex。
           SummaryIndex 更适合“总结一下、总体原则是什么”这类问题。
           它不是为了精准命中某一小段，而是帮助 LLM 汇总多个节点。
        """
        if self._summary_index is not None:
            return self._summary_index

        try:
            from llama_index.core import SummaryIndex
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index hyde")) from e

        summary_index = SummaryIndex(
            nodes=self._get_all_rule_nodes()
        )
        self._summary_index = summary_index

        return summary_index

    def summary_retrieve(self, query: str, k: int) -> List[Document]:
        """LlamaIndex SummaryIndex 检索。
        对照 `RetrievalEnhancer.summary_retrieve()`：
        - 原生版：先让 LLM 给每份文档写摘要，再查摘要索引。
        - LlamaIndex 版：用 SummaryIndex 组织节点，适合总结型查询。
        """
        summary_index = self._get_summary_index()
        retriever = summary_index.as_retriever(
            llm=self._get_llama_llm(),
            retriever_mode="embedding",
            similarity_top_k=k,
            embed_model=self._get_embed_model()
        )
        nodes = retriever.retrieve(query)

        return _nodes_to_docs(nodes, k)

    def llama_query_fusion_retrieve(self, query: str, k: int) -> List[Document]:
        try:
            from llama_index.core.retrievers import QueryFusionRetriever
            from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index query_fusion")) from e

        vector_retriever = self._get_rule_vector_index().as_retriever(
            similarity_top_k=max(k, self.retrieval_config.similarity_top_k)
        )
        fusion_retriever = QueryFusionRetriever(
            retrievers=[vector_retriever],
            llm=self._get_llama_llm(),
            similarity_top_k=k,
            num_queries=self.retrieval_config.fusion_num_queries,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            use_async=False,
            verbose=True,
        )
        nodes = fusion_retriever.retrieve(query)
        return _nodes_to_docs(nodes, k)

    def llama_router_retrieve(self, query: str, k: int) -> List[Document]:
        """LlamaIndex Router Retriever。
        Router 的作用：
        用户问题进来后，先判断更适合走哪个检索器。
        这里给它三个候选：
        - vector：普通语义检索，适合具体条款。
        - summary：摘要索引，适合问总体原则/总结。
        - hybrid：关键词 + 语义，适合精确术语。
        """
        try:
            from llama_index.core.retrievers import RouterRetriever
            from llama_index.core.selectors import LLMSingleSelector
            from llama_index.core.tools import RetrieverTool
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index router"))

        vector_retriever = self._get_rule_vector_index().as_retriever(
            similarity_top_k=max(k, self.retrieval_config.similarity_top_k)
        )
        summary_retriever = self._get_summary_index().as_retriever()
        hybrid_retriever = self._get_bm25_retriever(
            max(k, self.retrieval_config.similarity_top_k)
        )

        retriever = RouterRetriever(
            selector=LLMSingleSelector.from_defaults(llm=self._get_llama_llm()),
            retriever_tools=[
                RetrieverTool.from_defaults(
                    retriever=vector_retriever,
                    description="适合查询具体制度条款、流程、材料、时效。"
                ),
                RetrieverTool.from_defaults(
                    retriever=summary_retriever,
                    description="适合总结制度总体原则、概览、制度主题。"
                ),
                RetrieverTool.from_defaults(
                    retriever=hybrid_retriever,
                    description="适合包含精确关键词、缩写、专有名词的问题。"
                )
            ]
        )
        nodes = retriever.retrieve(query)
        return _nodes_to_docs(nodes, k)

    def _summarize_for_index_node(self, text: str, source: str) -> str:
        """给 recursive root node 生成一段短摘要。"""
        prompt = (
            "请为下面企业制度文档写一段用于检索路由的摘要，80字以内，包含关键词。\n"
            f"来源: {source}\n"
            f"文档:\n{text[:3000]}"
        )
        try:
            summary = self.llm.complete(prompt, temperature=0.2, max_tokens=256).strip()
            return summary or f"{source}: {text[:300]}"
        except Exception:
            return f"{source}: {text[:300]}"

    def _get_recursive_retriever(self) -> Any:
        """构建 LlamaIndex RecursiveRetriever。
           每份制度文档会生成一个摘要入口 IndexNode，并绑定到该文档自己的
           child retriever。查询时先通过 root retriever 定位相关文档，再递归进入
           对应 child retriever，在文档内部检索具体条款 chunk。
        """
        """
        普通 vector:
        query -> 所有文档所有 chunk 里直接搜
        recursive:
        query -> 先根据摘要选相关文档 -> 再进相关文档内部搜
        """
        if self._recursive_retriever is not None:
            return self._recursive_retriever

        try:
            from llama_index.core.retrievers import RecursiveRetriever
            from llama_index.core.node_parser import SentenceSplitter
            from llama_index.core.schema import IndexNode
            from llama_index.core import VectorStoreIndex
        except ModuleNotFoundError as e:
            raise RuntimeError(_missing_dependency_message("llama-index recursive"))

        # 1. 每份文档做一个摘要入口节点，存“入口节点”，每个入口节点代表一份制度文档。
        index_nodes = []
        # 存“可被递归调用的 retriever”，负责存储root retriever + child retriever
        retriever_dict: dict[str, Any] = {}
        # 文档分割器
        splitter = SentenceSplitter(
            chunk_size=self.retrieval_config.recursive_chunk_size,
            chunk_overlap=self.retrieval_config.recursive_chunk_overlap,
        )

        # 2. 每份文档内部建一个 child retriever
        for doc_id, document in enumerate(self._get_all_rule_documents()):
            # 如果命中这个入口，就进入哪个 child retriever
            index_id = f"rule_doc_{doc_id}"
            source = document.metadata.get("source", f"doc_{doc_id}")
            if getattr(document, "get_content", None):
                text = document.get_content()
            else:
                text = getattr(document, "text", "")
            # 生成这份文档的摘要，用来给 root retriever 做相似度匹配
            summary = self._summarize_for_index_node(text, source)
            # 切割每一份文档，得到它的所有子节点，一份文档内部切出来的具体 chunk
            child_nodes = splitter.get_nodes_from_documents([document])
            # 用子节点创建 child retriever
            child_retriever = VectorStoreIndex(
                nodes=child_nodes,
                embed_model=self._get_embed_model()
            ).as_retriever(
                similarity_top_k=self.retrieval_config.similarity_top_k
            )
            # 创建 IndexNode对象,添加到index_nodes中
            index_nodes.append(
                IndexNode(
                    text=summary,
                    index_id=index_id,
                )
            )
            # 每个子节点id对应一个retriever
            retriever_dict[index_id] = child_retriever

        root_top_k = max(
            1,
            min(len(index_nodes), self.retrieval_config.similarity_top_k)
        )
        # 3. 用所有入口节点建 root retriever
        root_retriever = VectorStoreIndex(
            nodes=index_nodes,
            embed_model=self._get_embed_model(),
        ).as_retriever(
            similarity_top_k=root_top_k
        )
        retriever_dict["root"] = root_retriever

        # 4. RecursiveRetriever 从 root 开始
        retriever = RecursiveRetriever(
            root_id="root",
            retriever_dict=retriever_dict,
            verbose=True,
        )
        self._recursive_retriever = retriever

        return retriever

    def llama_recursive_retrieve(self, query: str, k: int) -> List[Document]:
        retriever = self._get_recursive_retriever()
        nodes = retriever.retrieve(query)
        return _nodes_to_docs(nodes, k)

    def llama_auto_retrieval_retrieve(self, query: str, k: int) -> List[Document]:
        """
        AutoRetriever = 让 LLM 先把自然语言问题翻译成“metadata 过滤条件 + 语义 query”，再去向量库里精确检索。
        LlamaIndex Auto-Retrieval：metadata filter + semantic search。
        学习重点：
        让 LLM 从用户问题里自动提取过滤条件，比如 source/source_type，
        再把结构化过滤和向量检索结合起来。
        在企业制度库里，未来可以把 metadata 扩展成：
        department、year、policy_type、region、permission_level 等。
        """
        try:
            from llama_index.core.indices.vector_store.retrievers import VectorIndexAutoRetriever
        except (ImportError, ModuleNotFoundError):
            return self.plain_retrieve(query, k)

        try:
            from llama_index.core.vector_stores import MetadataInfo, VectorStoreInfo
        except (ImportError, ModuleNotFoundError):
            try:
                from llama_index.core.vector_stores.types import MetadataInfo, VectorStoreInfo
            except (ImportError, ModuleNotFoundError):
                return self.plain_retrieve(query, k)
        vector_store_info = VectorStoreInfo(
            content_info="企业制度、流程、审批、报销、考勤、IT 服务等文本片段",
            metadata_info=[
                MetadataInfo(
                    name="source",
                    type="str",
                    description="制度来源文件名，例如 leave_policy.md"
                ),
                MetadataInfo(
                    name="source_type",
                    type="str",
                    description="知识库类型，本项目制度库固定为 rules"
                ),
                MetadataInfo(
                    name="file_stem",
                    type="str",
                    description="不带扩展名的文件名，可用于按制度文件过滤"
                )
            ]
        )
        try:
            retriever = VectorIndexAutoRetriever(
                index=self._get_rule_vector_index(),
                llm=self._get_llama_llm(),
                vector_store_info=vector_store_info,
                similarity_top_k=k,
                verbose=True,
            )
            nodes = retriever.retrieve(query)
            return _nodes_to_docs(nodes, k)
        except Exception as e:
            return self.plain_retrieve(query, k)

    def _build_graph_index(self, force: bool = False) -> Any:
        """构建 LlamaIndex GraphRAG 索引。
           从制度文档中抽取实体、关系和路径并构建图索引；抽取过程由
           LlamaIndex 内部通过 LLM 完成。优先使用 PropertyGraphIndex，
           不可用时回退到 KnowledgeGraphIndex 以兼容不同版本。
        """
        if self._graph_index is not None and not force:
            return self._graph_index
        documents = self._get_all_rule_documents()

        try:
            from llama_index.core import PropertyGraphIndex
            graph_index = PropertyGraphIndex.from_documents(
                documents=documents,
                llm=self._get_llama_llm(),
                embed_model=self._get_embed_model(),
                show_progress=False
            )
            self._graph_index = graph_index
            return graph_index
        except Exception:
            pass

        try:
            from llama_index.core import KnowledgeGraphIndex
            graph_index = KnowledgeGraphIndex.from_documents(
                documents=documents,
                max_triplets_per_chunk=2,
                include_embeddings=True,
                llm=self._get_llama_llm(),
                embed_model=self._get_embed_model(),
            )
            self._graph_index = graph_index
            graph_index.as_retriever()
            return graph_index
        except Exception as exc:
            raise RuntimeError(
                "当前 LlamaIndex 安装无法构建 PropertyGraphIndex/KnowledgeGraphIndex。"
                "GraphRAG 依赖较重，可先使用 llama_recursive 或 llama_auto_retrieval。"
            ) from exc

    def llama_graph_retrieve(self, query: str, k: int) -> List[Document]:
        """LlamaIndex GraphRAG / KnowledgeGraph retrieval。
          适合实体关系比较重要的问题，例如：
          - 哪些制度约束某类员工行为？
          - 某审批流程涉及哪些角色和系统？
          - 某条款和哪些制度主题有关？
          如果只是普通条款问答，`llama_hybrid` / `llama_recursive`
          通常会更轻、更稳定。
        """
        graph_index = self._build_graph_index(force=False)
        retriever = graph_index.as_retriever(
            similarity_top_k=max(k, self.retrieval_config.similarity_top_k)
        )
        nodes = retriever.retrieve(query)
        return _nodes_to_docs(nodes, k)
