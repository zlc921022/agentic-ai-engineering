# 路由+检索+生成编排
from typing import Any, Dict, Optional, Sequence

from langchain_core.documents import Document

from enterprise_employee_assistant.src.client import QwenChatClient
from enterprise_employee_assistant.src.index_manager import ChromaIndexManager
from enterprise_employee_assistant.src.langgraph_enterprise_agent import EnterpriseLangGraphAgent
from enterprise_employee_assistant.src.llamaindex_retrieval_enhance import LlamaIndexRetrievalEnhancer
from enterprise_employee_assistant.src.rag_types import RetrievalOptions, RetrievalStrategy, AnswerPackage
from enterprise_employee_assistant.src.rag_triad import RAGTriadEvaluator
from enterprise_employee_assistant.src.retrieval_enhance import RetrievalEnhancer
from enterprise_employee_assistant.src.retrieval_types import RetrievalResult
from enterprise_employee_assistant.src.retrieval_util import docs_to_context, _collect_references


class QueryRouter:
    """简单路由器：把问题分为“制度问答”或“经营问答”。"""

    def __init__(self, llm: QwenChatClient):
        self.llm = llm

    def route(self, query: str) -> str:
        prompt = (
            "你是路由器。请判断问题类型：\n"
            "A=企业规章制度（请假、报销、考勤、IT服务台等）\n"
            "B=公司经营/投融资/市场动态\n"
            f"问题: {query}\n"
            "只输出 A 或 B。"
        )
        resp = self.llm.complete(prompt, temperature=0.0, max_tokens=8).strip().upper()
        return "rules" if "A" in resp else "business"


class EnterpriseAssistantService:
    """企业员工助手主服务。
       这是整个项目的“总调度”：
       - 它不自己做向量化
       - 它不自己实现某种检索算法
       - 它负责把“路由、检索、生成、引用整理”串起来
    """
    RULE_PROMPT = (
        "你是企业员工助手，必须根据给定上下文回答。\n"
        "要求：\n"
        "1) 如果上下文不足，明确说“不知道/建议咨询HR或相关部门”；\n"
        "2) 回答要简洁，优先给流程、时效、材料、审批链路；\n"
        "3) 最后给出“引用来源”。\n\n"
        "问题: {question}\n"
        "上下文:\n{context}\n\n"
        "请输出：\n"
        "- 结论\n"
        "- 操作步骤\n"
        "- 引用来源"
    )

    BUSINESS_PROMPT = (
        "你是企业经营分析助手，请基于上下文回答。\n"
        "若上下文不足，请明确说明。\n\n"
        "问题: {question}\n"
        "上下文:\n{context}\n\n"
        "请输出：\n"
        "- 结论\n"
        "- 关键依据\n"
        "- 风险提示\n"
        "- 引用来源"
    )

    LLAMAINDEX_STRATEGY_METHODS = {
        RetrievalStrategy.LLAMA_PLAIN: ("plain_retrieve", "LlamaIndex 基础向量检索"),
        RetrievalStrategy.LLAMA_SENTENCE_WINDOW: ("sentence_window_retrieve", "LlamaIndex sentence-window 检索"),
        RetrievalStrategy.LLAMA_AUTO_MERGING: ("auto_merging_retrieve", "LlamaIndex auto-merging 检索"),
        RetrievalStrategy.LLAMA_HYDE: ("hyde_retrieve", "LlamaIndex HyDE 检索"),
        RetrievalStrategy.LLAMA_QUERY_FUSION: ("llama_query_fusion_retrieve", "LlamaIndex query fusion 检索"),
        RetrievalStrategy.LLAMA_HYBRID: ("hybrid_retrieve", "LlamaIndex BM25 + vector 混合检索"),
        RetrievalStrategy.LLAMA_RERANK: ("rerank_retrieve", "LlamaIndex LLM rerank 检索"),
        RetrievalStrategy.LLAMA_ROUTER: ("llama_router_retrieve", "LlamaIndex router 检索"),
        RetrievalStrategy.LLAMA_RECURSIVE: ("llama_recursive_retrieve", "LlamaIndex recursive 检索"),
        RetrievalStrategy.LLAMA_SUMMARY: ("summary_retrieve", "LlamaIndex SummaryIndex 检索"),
        RetrievalStrategy.LLAMA_AUTO_RETRIEVAL: ("llama_auto_retrieval_retrieve", "LlamaIndex auto-retrieval 检索"),
        RetrievalStrategy.LLAMA_GRAPH: ("llama_graph_retrieve", "LlamaIndex GraphRAG 检索"),
    }

    def __init__(self,
                 llm: QwenChatClient,
                 index_manager: ChromaIndexManager,
                 enhancer: RetrievalEnhancer,
                 llamaindex_enhancer: Optional[LlamaIndexRetrievalEnhancer] = None,
                 langgraph_agent: Optional[EnterpriseLangGraphAgent] = None,
                 triad_evaluator: Optional[RAGTriadEvaluator] = None,
                 ):
        self.llm = llm
        self.index_manager = index_manager
        self.enhancer = enhancer
        self.llamaindex_enhancer = llamaindex_enhancer
        self.langgraph_agent = langgraph_agent
        self.triad_evaluator = triad_evaluator
        self.router = QueryRouter(llm)

    def _llamaindex_retrieve(self, query: str, options: RetrievalOptions) -> RetrievalResult:
        """把 LlamaIndex 返回的 docs 包装成项目统一的 RetrievalResult。"""
        if self.llamaindex_enhancer is None:
            raise RuntimeError("LlamaIndex 检索增强器未接入，请在 app.py 的 build_service() 中初始化。")

        method_name, debug_note = self.LLAMAINDEX_STRATEGY_METHODS[options.strategy]
        retrieve = getattr(self.llamaindex_enhancer, method_name)
        docs = retrieve(query, k=options.top_k)
        return RetrievalResult(
            strategy=options.strategy.value,
            docs=docs,
            debug_note=debug_note,
        )

    def _maybe_evaluate_triad(
            self,
            query: str,
            answer: str,
            docs: Sequence[Document],
            options: RetrievalOptions,
    ) -> str:
        """按需执行 RAG Triad 评估，默认关闭以避免普通问答额外消耗模型调用。"""
        if not options.enable_triad_eval:
            return ""
        if self.triad_evaluator is None:
            return "RAG Triad 评估器未接入，请在 app.py 的 build_service() 中初始化。"
        try:
            return self.triad_evaluator.evaluate(query, answer, docs).to_text()
        except Exception as exc:
            return f"RAG Triad 评估失败: {exc}"

    def _retrieval_rules(self, query: str, options: RetrievalOptions) -> RetrievalResult:
        strategy = options.strategy
        if strategy == RetrievalStrategy.QUERY2DOC:
            result = self.enhancer.query2doc_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.HYDE:
            result = self.enhancer.hyde_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.REWRITE:
            result = self.enhancer.question_rewrite_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.STEP_BACK:
            result = self.enhancer.step_back_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.SUB_QUESTION:
            result = self.enhancer.sub_question_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.PARENT_CHILD:
            result = self.enhancer.parent_child_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.SUMMARY_INDEX:
            result = self.enhancer.summary_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.HYPOTHETICAL_QUESTION:
            result = self.enhancer.hypothetical_question_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.MULTI_INDEX:
            result = self.enhancer.multi_index_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.HYBRID:
            result = self.enhancer.hybrid_retrieve(
                query=query,
                k=options.top_k,
                bm25_weight=options.bm25_weight,
                vector_weight=options.vector_weight,
            )
        elif strategy == RetrievalStrategy.ITERATIVE:
            result = self.enhancer.iterative_retrieve(query, k=options.top_k)
        elif strategy == RetrievalStrategy.SENTENCE_WINDOW:
            result = self.enhancer.sentence_window_retriever(query, k=options.top_k)
        elif strategy == RetrievalStrategy.AUTO_MERGING:
            result = self.enhancer.auto_merging_retriever(query, k=options.top_k)
        elif strategy in self.LLAMAINDEX_STRATEGY_METHODS:
            result = self._llamaindex_retrieve(query, options)
        else:
            result = self.enhancer.plain_retrieve(query, k=options.top_k)

        """
        self-rag 自带节点内的生成与校验，不在这里 rerank。
        其他策略则统一在服务层做一次“是否需要重排”的控制。
        """
        if (options.enable_rerank and result.docs
                and strategy != RetrievalStrategy.SELF_RAG
                and strategy != RetrievalStrategy.SELF_RAG_LANGGRAPH
                and strategy != RetrievalStrategy.LANGGRAPH_AGENT
                and strategy != RetrievalStrategy.LLAMA_RERANK
                and strategy not in self.LLAMAINDEX_STRATEGY_METHODS
        ):
            reranked_docs, rerank_note = self.enhancer.rerank(
                query=query,
                docs=result.docs,
                top_n=min(options.rerank_top_n, len(result.docs)),
                method=options.rerank_method,
            )
            result.docs = reranked_docs
            result.debug_note += f"| 已执行{rerank_note}"

        return result

    def answer(self, query: str, options: RetrievalOptions = None) -> AnswerPackage:
        """主入口：完成路由 + 检索 + 生成。"""
        # 第一步：先判断这个问题更像“制度问答”还是“经营分析”。
        if options is None:
            options = RetrievalOptions()
        if options.strategy == RetrievalStrategy.LANGGRAPH_AGENT:
            return self._langgraph_agent_answer(query, options)

        route = self.router.route(query)
        if route == "business":
            return self._business_answer(query, options)
        elif options.strategy == RetrievalStrategy.SELF_RAG:
            return self._self_rag_answer(query, options)
        elif options.strategy == RetrievalStrategy.SELF_RAG_LANGGRAPH:
            return self._self_rag_answer_langgraph(query, options)
        else:
            return self._rule_answer(query, options)

    # 经营类回复
    def _business_answer(self, query: str, options: RetrievalOptions) -> AnswerPackage:
        docs = self.index_manager._search_business(query, k=options.top_k)
        context = docs_to_context(docs)
        references = _collect_references(docs)
        prompt = self.BUSINESS_PROMPT.format(question=query, context=context)
        answer = self.llm.complete(prompt, temperature=0.1)
        return AnswerPackage(
            answer=answer,
            context=context,
            references=references,
            strategy=options.strategy,
            route="business",
            debug_note="经营文档向量检索",
            triad_report=self._maybe_evaluate_triad(query, answer, docs, options),
        )

    # 制度类回复
    def _rule_answer(self, query: str, options: RetrievalOptions) -> AnswerPackage:
        result = self._retrieval_rules(query, options)
        context = docs_to_context(result.docs)
        prompt = self.RULE_PROMPT.format(question=query, context=context)
        answer = self.llm.complete(prompt, temperature=0.1)
        references = _collect_references(result.docs)
        return AnswerPackage(
            answer=answer,
            context=context,
            references=references,
            strategy=options.strategy,
            route="rule",
            debug_note=result.debug_note,
            triad_report=self._maybe_evaluate_triad(query, answer, result.docs, options),
        )

    # self-rag 线性回复
    def _self_rag_answer(self, query: str, options: RetrievalOptions) -> AnswerPackage:
        result = self.enhancer.self_rag_answer(query, k=options.top_k)
        return self._rag_answer(query, result, RetrievalStrategy.SELF_RAG, options)

    # self-rag langgraph 回复
    def _self_rag_answer_langgraph(self, query: str, options: RetrievalOptions) -> AnswerPackage:
        result = self.enhancer.self_rag_answer_langgraph(query, k=options.top_k)
        return self._rag_answer(query, result, RetrievalStrategy.SELF_RAG_LANGGRAPH, options)

    # LangGraph Agentic RAG 回复
    def _langgraph_agent_answer(self, query: str, options: RetrievalOptions) -> AnswerPackage:
        """LangGraph Agentic RAG 入口。

        Agent 内部会自己 plan route，并按状态图调用规则库/经营库检索工具，
        所以这里不再先走 service 的 QueryRouter。
        """
        if self.langgraph_agent is None:
            raise RuntimeError("LangGraph Agent 未接入，请在 app.py 的 build_service() 中初始化。")

        result = self.langgraph_agent.answer(
            query,
            top_k=options.top_k,
            revision_max=1,
        )
        if result is None:
            raise RuntimeError("LangGraph Agent 未返回结果。")

        debug_note = result.debug_note
        if result.needs_human_review:
            debug_note += "\nhuman_review: 建议人工确认后再执行。"
        if result.critique:
            debug_note += f"\ncritique: {result.critique}"

        return AnswerPackage(
            answer=result.answer,
            context=result.context,
            references=result.references,
            strategy=RetrievalStrategy.LANGGRAPH_AGENT,
            route=result.route,
            debug_note=debug_note,
            triad_report=self._maybe_evaluate_triad(query, result.answer, result.docs, options),
        )

    # 构建rag回复
    def _rag_answer(
            self,
            query: str,
            result: Dict[str, Any],
            strategy: RetrievalStrategy,
            options: RetrievalOptions,
    ) -> AnswerPackage:
        answer = result.get("answer", "")
        context = result.get("context", "")
        docs = result.get("docs", [])
        debug_note = result.get("debug_note", "")
        references = _collect_references(docs)
        return AnswerPackage(
            answer=answer,
            context=context,
            references=references,
            strategy=strategy,
            route="rules",
            debug_note=debug_note,
            triad_report=self._maybe_evaluate_triad(query, answer, docs, options),
        )
