# RAG 数据相关类
from dataclasses import dataclass
from enum import Enum
from typing import List


class RetrievalStrategy(str, Enum):
    PLAIN = "plain"
    QUERY2DOC = "query2doc"
    HYDE = "hyde"
    REWRITE = "rewrite"
    STEP_BACK = "step_back"
    SUB_QUESTION = "sub_question"
    PARENT_CHILD = "parent_child"
    SUMMARY_INDEX = "summary_index"
    HYPOTHETICAL_QUESTION = "hypothetical_question"
    MULTI_INDEX = "multi_index"
    HYBRID = "hybrid"
    ITERATIVE = "iterative"
    SENTENCE_WINDOW = "sentence_window"
    AUTO_MERGING = "auto_merging"
    LLAMA_PLAIN = "llama_plain"
    LLAMA_SENTENCE_WINDOW = "llama_sentence_window"
    LLAMA_AUTO_MERGING = "llama_auto_merging"
    LLAMA_HYDE = "llama_hyde"
    LLAMA_QUERY_FUSION = "llama_query_fusion"
    LLAMA_HYBRID = "llama_hybrid"
    LLAMA_RERANK = "llama_rerank"
    LLAMA_ROUTER = "llama_router"
    LLAMA_RECURSIVE = "llama_recursive"
    LLAMA_SUMMARY = "llama_summary"
    LLAMA_AUTO_RETRIEVAL = "llama_auto_retrieval"
    LLAMA_GRAPH = "llama_graph"
    LANGGRAPH_AGENT = "langgraph_agent"
    SELF_RAG = "self_rag"
    SELF_RAG_LANGGRAPH = "self_rag_langgraph"


class RerankMethod(str, Enum):
    LLM = "llm"
    LLM_BATCH = "llm_batch"


@dataclass
class RetrievalOptions:
    """检索参数配置。
    这个类的作用是把 UI 上的几个控制项打包起来，
    避免函数参数越来越多、越来越难传。
    """
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    top_k: int = 4
    enable_rerank: bool = True
    rerank_top_n: int = 4
    rerank_method: RerankMethod = RerankMethod.LLM
    bm25_weight: float = 0.35
    vector_weight: float = 0.65
    enable_triad_eval: bool = False


@dataclass
class AnswerPackage:
    """回答结果包。
    前端真正需要展示的东西，都在这个对象里：
    - answer: 最终答案
    - context: 实际喂给模型的上下文
    - references: 来源文件
    - route/strategy/debug_note: 调试信息
    """
    answer: str
    context: str
    references: List[str]
    route: str
    strategy: RetrievalStrategy
    debug_note: str
    triad_report: str = ""
