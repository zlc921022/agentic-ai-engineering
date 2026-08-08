import operator
import uuid
from dataclasses import dataclass
from typing import TypedDict, Any, List, Annotated, Literal, Dict, Sequence, Optional

from langchain_core.documents import Document
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END
from langgraph.graph import StateGraph

from src.client import QwenChatClient
from src.index_manager import ChromaIndexManager
from src.retrieval_util import _extract_json, _dedupe_docs, docs_to_context, \
    _collect_references

AgentRoute = Literal["rules", "business", "both"]


class EnterpriseAgentState(TypedDict):
    """LangGraph 状态对象。
    `debug_steps` 和 `docs` 使用 reducer，方便各节点追加执行轨迹和检索结果。
     其他字段由节点覆盖更新。
    """
    question: str
    route: AgentRoute
    plan: str
    search_queries: List[str]
    docs: Annotated[List[Document], operator.add]
    context: str
    answer: str
    critique: str
    needs_human_review: bool
    revision_count: int
    revision_max: int
    top_k: int
    debug_steps: Annotated[List[str], operator.add]


@dataclass
class LangGraphAgentResult:
    """Agent 最终结果，方便 service 层转成 AnswerPackage。"""
    answer: str
    context: str
    references: List[str]
    route: str
    docs: List[Document]
    debug_note: str
    plan: str = ""
    critique: str = ""
    needs_human_review: bool = False


class EnterpriseLangGraphAgent:
    """面向企业制度/经营知识库的 LangGraph Agent。
    这个类故意不依赖 OpenAI tools-calling，因为项目当前 LLM 是百炼/Qwen
    OpenAI-compatible completion 客户端。这里采用“LLM 输出 JSON 计划 +
    Python 节点执行工具”的方式，更适合课程学习和本项目落地。
    """

    SYSTEM_PROMPT = (
        "你是企业员工助手 Agent。你可以使用两个内部检索工具：\n"
        "1) search_rules: 查询请假、报销、IT、员工手册、考勤、远程办公、信息安全等制度。\n"
        "2) search_business: 查询公司经营、投融资、市场动态等经营资料。\n"
        "回答必须基于检索上下文；证据不足时要明确说明，并建议咨询对应部门。"
    )

    HUMAN_REVIEW_KEYWORDS = (
        "开除",
        "辞退",
        "劳动仲裁",
        "法律",
        "赔偿",
        "薪资争议",
        "客户资料导出",
        "数据泄露",
        "处分",
        "罚款",
    )

    def __init__(
            self,
            llm: QwenChatClient,
            index_manager: ChromaIndexManager,
            memory_saver: MemorySaver = None
    ):
        self.llm = llm
        self.index_manager = index_manager
        self.memory_saver = memory_saver or MemorySaver()
        self.graph = self._build_graph()

    def _fallback_route(self, question: str) -> AgentRoute:
        business_keywords = ("经营", "季度", "市场", "投融资", "投资", "融资", "营收", "增长")
        rules_keywords = ("请假", "报销", "考勤", "IT", "VPN", "远程", "打卡", "病假", "年假")
        has_business = any(keyword in question for keyword in business_keywords)
        has_rules = any(keyword in question for keyword in rules_keywords)
        if has_business and has_rules:
            return "both"
        if has_business:
            return "business"
        return "rules"

    def _is_sensitive(self, question: str) -> bool:
        return any(keyword in question for keyword in self.HUMAN_REVIEW_KEYWORDS)

    def _search_rules(self, queries: Sequence[str], k: int) -> List[Document]:
        docs: List[Document] = []
        per_query_k = max(1, k)
        for query in list(queries)[:2]:
            docs.extend(self.index_manager._search_rules(query, k=per_query_k))
        return _dedupe_docs(docs)[:k]

    def _search_business(self, queries: Sequence[str], k: int) -> List[Document]:
        docs: List[Document] = []
        per_query_k = max(1, k)
        for query in list(queries)[:2]:
            docs.extend(self.index_manager._search_business(query, k=per_query_k))
        return _dedupe_docs(docs)[:k]

    def _build_graph(self):
        graph = StateGraph(EnterpriseAgentState)
        graph.add_node("plan", self.plan)
        graph.add_node("retrieve_rules", self.retrieve_rules)
        graph.add_node("retrieve_business", self.retrieve_business)
        graph.add_node("retrieve_both", self.retrieve_both)
        graph.add_node("generate", self.generate)
        graph.add_node("reflect", self.reflect)
        graph.add_node("revise", self.revise)
        # 入口节点
        graph.set_entry_point("plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "rules": "retrieve_rules",
                "business": "retrieve_business",
                "both": "retrieve_both",
            }
        )
        graph.add_edge("retrieve_rules", "generate")
        graph.add_edge("retrieve_business", "generate")
        graph.add_edge("retrieve_both", "generate")
        graph.add_edge("generate", "reflect")
        graph.add_conditional_edges(
            "reflect",
            self._route_after_reflect,
            {
                "revise": "revise",
                "end": END
            }
        )
        graph.add_edge("revise", "reflect")
        app = graph.compile(checkpointer=self.memory_saver)
        return app

    # 计划
    def plan(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        question = state.get("question")
        prompt = (
            f"{self.SYSTEM_PROMPT}\n\n"
            "请为用户问题制定检索计划，并严格输出 JSON：\n"
            "{\n"
            '  "route": "rules|business|both",\n'
            '  "search_queries": ["用于检索的查询1", "用于检索的查询2"],\n'
            '  "reason": "一句话说明为什么这样选",\n'
            '  "needs_human_review": false\n'
            "}\n\n"
            f"用户问题: {question}"
        )
        response = self.llm.complete(prompt, temperature=0, max_tokens=512)
        data = _extract_json(response)
        route = data.get("route")
        if route not in ("rules", "business", "both"):
            route = self._fallback_route(question)
        queries = data.get("search_queries")
        if not isinstance(queries, list):
            queries = [question]
        queries = [str(item).strip() for item in queries if item and str(item).strip()][:2]
        if not queries:
            queries = [question]
        reason = str(data.get("reason") or "使用启发式路由。")
        needs_human_review = bool(data.get("needs_human_review")) or self._is_sensitive(question)
        return {
            "route": route,
            "search_queries": queries,
            "plan": reason,
            "needs_human_review": needs_human_review,
            "debug_steps": [f"plan: route={route}, queries={queries}, reason={reason}"],
        }

    # 计划之后条件分支
    def _route_after_plan(self, state: EnterpriseAgentState) -> str:
        route = state.get("route", "rules")
        return route if route in ("rules", "business", "both") else "rules"

    # 检索规则类
    def retrieve_rules(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        queries = state.get("search_queries") or [state.get("question")]
        top_k = state.get("top_k") or 4
        docs = self._search_rules(queries, top_k)
        return {
            "docs": docs,
            "context": docs_to_context(docs),
            "debug_steps": [f"act: search_rules -> {len(docs)} docs"],
        }

    # 检索经营类
    def retrieve_business(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        queries = state.get("search_queries") or [state.get("question")]
        top_k = state.get("top_k") or 4
        docs = self._search_business(queries, top_k)
        return {
            "docs": docs,
            "context": docs_to_context(docs),
            "debug_steps": [f"act: search_business -> {len(docs)} docs"],
        }

    # 两者都检索
    def retrieve_both(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        queries = state.get("search_queries") or [state.get("question")]
        top_k = state.get("top_k") or 4
        docs = _dedupe_docs(self._search_rules(queries, top_k) + self._search_business(queries, top_k))[:top_k]
        return {
            "docs": docs,
            "context": docs_to_context(docs),
            "debug_steps": [f"act: search_rules + search_business -> {len(docs)} docs"],
        }

    # 生成
    def generate(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        question = state.get("question")
        context = state.get("context")
        needs_human_review = state.get("needs_human_review")
        review_note = (
            "注意：该问题可能涉及高风险决策，回答中必须提示需要人工确认。\n"
            if needs_human_review
            else ""
        )
        prompt = (
            f"{self.SYSTEM_PROMPT}\n"
            f"{review_note}"
            "请根据上下文回答用户问题。输出要简洁，包含结论、关键依据和引用来源。\n"
            "如果上下文不足，请明确说不知道。\n\n"
            f"问题:\n{question}\n\n"
            f"上下文:\n{context}\n\n"
            "回答:"
        )
        answer = self.llm.complete(prompt, temperature=0.1, max_tokens=1200)
        return {
            "question": question,
            "context": context,
            "answer": answer,
            "debug_steps": [f"act: complete"],
        }

    # 反思
    def reflect(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        answer = state.get("answer", "")
        question = state.get("question", "")
        context = state.get("context", "")
        docs = state.get("docs")
        needs_human_review = state.get("needs_human_review")
        if not docs:
            return {
                "critique": "没有检索到上下文，不能给出有证据的回答。",
                "needs_human_review": True,
                "debug_steps": ["reflect: no context, human review required"],
            }
        prompt = (
            "你是企业 RAG Agent 的反思节点。请检查回答是否：\n"
            "1) 回答了问题；2) 被上下文支撑；3) 没有越权承诺。\n"
            "严格输出 JSON：\n"
            '{"pass": true, "critique": "一句话说明", "needs_human_review": false}\n\n'
            f"问题:\n{question}\n\n"
            f"上下文:\n{context}\n\n"
            f"回答:\n{answer}"
        )
        response = self.llm.complete(prompt, temperature=0.1, max_tokens=1200)
        data = _extract_json(response)
        critique = str(data.get("critique") or "反思节点未发现明显问题。")
        needs_human_review = bool(data.get("needs_human_review")) or needs_human_review
        return {
            "needs_human_review": needs_human_review,
            "critique": critique,
            "debug_steps": [f"reflect: critique -> {critique}"],
        }

    # 反思之后条件分支
    def _route_after_reflect(self, state: EnterpriseAgentState) -> str:
        revision_count = int(state.get("revision_count", 0))
        revision_max = int(state.get("revision_max", 1))
        critique = state.get("critique") or ""
        needs_human_review = state.get("needs_human_review", False)
        should_revise = (
                revision_count < revision_max
                and not needs_human_review
                and any(keyword in critique for keyword in ("不足", "不完整", "没有", "缺少", "未"))
        )
        return "revise" if should_revise else "end"

    # 修正
    def revise(self, state: EnterpriseAgentState) -> Dict[str, Any]:
        question = state.get("question")
        context = state.get("context")
        answer = state.get("answer")
        critique = state.get("critique")
        prompt = (
            "请根据反思意见修订回答。仍然必须基于上下文，不要编造。\n\n"
            f"问题:\n{question}\n\n"
            f"上下文:\n{context}\n\n"
            f"原回答:\n{answer}\n\n"
            f"反思意见:\n{critique}\n\n"
            "修订回答:"
        )
        new_answer = self.llm.complete(prompt, temperature=0.1, max_tokens=1200)
        revision_count = state.get("revision_count", 0) + 1
        return {
            "answer": new_answer,
            "revision_count": revision_count,
            "debug_steps": [f"revise: revised answer from critique"],
        }

    def _init_state(
            self,
            question: str,
            *,
            top_k: int,
            revision_max: int,
    ) -> EnterpriseAgentState:
        return {
            "question": question,
            "search_queries": [question],
            "top_k": top_k,
            "revision_max": revision_max,
            "docs": [],
            "answer": "",
            "critique": "",
            "needs_human_review": False,
            "revision_count": 0,
            "debug_steps": [],
            "route": "rules",
            "plan": "",
            "context": "",
        }

    def answer(
            self,
            question: str,
            *,
            top_k: int = 4,
            thread_id: Optional[str] = None,
            revision_max: int = 1,
    ) -> LangGraphAgentResult | None:
        final_state = self.graph.invoke(
            input=self._init_state(
                question=question,
                top_k=top_k,
                revision_max=revision_max,
            ),
            config=self._thread_config(thread_id)
        )
        if final_state is None:
            return None

        docs = final_state.get("docs", [])
        return LangGraphAgentResult(
            answer=str(final_state.get("answer", "")),
            context=str(final_state.get("context", "")),
            references=_collect_references(docs),
            route=str(final_state.get("route", "")),
            docs=docs,
            debug_note="\n".join(final_state.get("debug_steps", [])),
            plan=str(final_state.get("plan", "")),
            critique=str(final_state.get("critique", "")),
            needs_human_review=bool(final_state.get("needs_human_review", False)),
        )

    def stream_events(
            self,
            question: str,
            *,
            top_k: int = 4,
            thread_id: Optional[str] = None,
            revision_max: int = 1,
    ):
        """流式产出 LangGraph 节点事件，适合后续接 UI 调试面板。"""
        yield from self.graph.stream(
            self._init_state(
                question,
                top_k=top_k,
                revision_max=revision_max
            ),
            config=self._thread_config(thread_id)
        )

    @staticmethod
    def _thread_config(thread_id: Optional[str]) -> Dict[str, Any]:
        return {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
