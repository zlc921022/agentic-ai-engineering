"""RAG Triad 评估器。

对应短课 `RAG Triad of metrics` 的核心内容，但这里没有强依赖 TruLens。
项目已经使用阿里百炼/Qwen，所以这里直接用现有 `QwenChatClient`
做 LLM-as-a-judge 评估，便于和企业文件助手项目集成。
"""
import re
from typing import Sequence

from langchain_core.documents import Document

from enterprise_employee_assistant.src.advanced_rag_types import TriadMetricResult, RAGTriadReport
from enterprise_employee_assistant.src.client import QwenChatClient


class RAGTriadEvaluator:
    """把一个 RAG 回答拆成三层质量指标来评估。

       课程里的关键思想是：不要只看最终回答“像不像”，而要把 RAG
       拆成检索和生成两个阶段分别诊断。

       - Context Relevance 定位检索问题：召回是否相关
       - Groundedness 定位幻觉问题：回答是否有上下文证据
       - Answer Relevance 定位表达问题：回答是否真正回应用户
    """

    def __init__(self, llm: QwenChatClient, context_char_limit: int = 1800):
        self.llm = llm
        # 控制每段上下文的最大长度，避免评估 prompt 过长导致成本和时延失控。
        self.context_char_limit = context_char_limit

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        """裁剪长文本。
        评估时不需要把整篇文档都塞给模型，保留前 limit 个字符即可。
        企业制度类 chunk 通常前半段已经包含标题和关键规则。
        """
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...（后文已截断）"

    @staticmethod
    def _parse_score(text: str) -> float:
        """从模型输出里解析 0-1 分数。
        为了抗格式波动，支持这些写法：
        - 0.82
        - 82
        - 分数：0.82
        - score: 82/100
        """
        score_line = re.search(
            r"(?:分数|score)\s*[:：]\s*"
            r"(?P<score>0(?:\.\d+)?|1(?:\.0+)?|100|\d{1,2})",
            text,
            re.I,
        )
        match = score_line or re.search(
            r"(?<!\d)(?:0(?:\.\d+)?|1(?:\.0+)?|100|\d{1,2})(?!\d)",
            text,
        )
        if not match:
            return 0.0
        value = float(match.group("score") if score_line else match.group())
        if value > 1:
            value = value / 100
        return max(0.0, min(1.0, value))

    @staticmethod
    def _parse_reason(text: str) -> str:
        """抽取理由文本，失败时保留原始短输出。"""
        reason_match = re.search(r"(?:理由|原因|reason)\s*[:：]\s*(.+)", text, re.I | re.S)
        if reason_match:
            return reason_match.group(1).strip().replace("\n", " ")
        cleaned = text.strip().replace("\n", " ")
        return cleaned[:180] if cleaned else "未给出理由"

    def _score_with_prompt(self, name: str, prompt: str) -> TriadMetricResult:
        """调用评估模型并统一解析结果。"""
        response = self.llm.complete(prompt, temperature=0.0, max_tokens=512)
        return TriadMetricResult(
            name=name,
            score=self._parse_score(response),
            reason=self._parse_reason(response),
        )

    def evaluate_answer_relevance(self, question: str, answer: str) -> TriadMetricResult:
        """评估 Answer Relevance：答案是否回应了用户问题。"""
        prompt = (
            "你是 RAG 系统评估员。请评估【回答】是否直接、完整地回应了【问题】。\n"
            "评分标准：1=完全回答；0=完全答非所问。只按相关性评分，不判断事实真假。\n"
            "请严格按格式输出：\n"
            "分数: 0到1的小数\n"
            "理由: 一句话说明\n\n"
            f"问题:\n{question}\n\n"
            f"回答:\n{self._clip(answer, 2000)}"
        )
        return self._score_with_prompt("Answer Relevance", prompt)

    def evaluate_context_relevance(self, question: str, docs: Sequence[Document]) -> tuple[
        TriadMetricResult, list[TriadMetricResult]]:
        """评估 Context Relevance：每段检索上下文是否和问题相关。
        课程里会对每个 retrieved context 分别打分，再聚合平均。
        这里也保留这个结构，方便你定位到底是哪一段召回偏了。
        """
        item_scores: list[TriadMetricResult] = []
        if not docs:
            empty = TriadMetricResult("Context Relevance", 0.0, "没有检索到上下文")
            return empty, item_scores
        for idx, doc in enumerate(docs, start=1):
            source = doc.metadata.get("source", "unknown")
            prompt = (
                "你是 RAG 检索质量评估员。请评估【上下文】对回答【问题】是否有帮助。\n"
                "评分标准：1=高度相关且可用于回答；0=完全无关。\n"
                "请严格按格式输出：\n"
                "分数: 0到1的小数\n"
                "理由: 一句话说明\n\n"
                f"问题:\n{question}\n\n"
                f"上下文来源: {source}\n"
                f"上下文:\n{self._clip(doc.page_content, self.context_char_limit)}"
            )
            item_scores.append(
                self._score_with_prompt(f"context {idx} ({source})", prompt)
            )
        average = sum(item.score for item in item_scores) / len(item_scores)
        aggregate = TriadMetricResult(
            name="Context Relevance",
            score=round(average, 4),
            reason="各检索片段相关性得分的平均值"
        )
        return aggregate, item_scores

    def evaluate_groundedness(self, answer: str, docs: Sequence[Document]) -> TriadMetricResult:
        """评估 Groundedness：回答是否能被检索上下文支撑。"""
        context = "\n\n".join(
            f"[来源: {doc.metadata.get('source', 'unknown')}]\n"
            f"{self._clip(doc.page_content, self.context_char_limit)}"
            for doc in docs
        )
        if not context.strip():
            return TriadMetricResult("Groundedness", 0.0, "没有上下文，无法支撑回答")
        prompt = (
            "你是 RAG 事实支撑性评估员。请判断【回答】中的主要结论是否都能被【上下文】支持。\n"
            "评分标准：1=所有关键结论都有证据；0=关键结论大多没有证据或明显编造。\n"
            "请严格按格式输出：\n"
            "分数: 0到1的小数\n"
            "理由: 一句话说明哪些内容有或没有依据\n\n"
            f"上下文:\n{context}\n\n"
            f"回答:\n{self._clip(answer, 2400)}"
        )
        return self._score_with_prompt("Groundedness", prompt)

    def evaluate(
            self,
            question: str,
            answer: str,
            docs: Sequence[Document],
    ) -> RAGTriadReport:
        answer_relevance = self.evaluate_answer_relevance(question, answer)
        context_relevance, context_items = self.evaluate_context_relevance(question, docs)
        groundedness = self.evaluate_groundedness(answer, docs)
        return RAGTriadReport(
            answer_relevance=answer_relevance,
            context_relevance=context_relevance,
            groundedness=groundedness,
            context_items=context_items
        )

# if __name__ == "__main__":
    # config = Config()
    # llm = QwenChatClient(config)
    # evaluator = RAGTriadEvaluator(llm)
    # question = "",
    # answer = ""
    # evaluator.evaluate()
