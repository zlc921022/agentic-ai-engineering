# 评估
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv
from ragas import EvaluationDataset, evaluate
from ragas.embeddings.base import LangchainEmbeddingsWrapper
from ragas.llms import llm_factory
from ragas.metrics._answer_relevance import answer_relevancy
from ragas.metrics._context_precision import context_precision
from ragas.metrics._context_recall import context_recall
from ragas.metrics._faithfulness import faithfulness

from enterprise_employee_assistant.app import build_service
from enterprise_employee_assistant.src.rag_service import EnterpriseAssistantService
from enterprise_employee_assistant.src.rag_types import RetrievalOptions, RetrievalStrategy


@dataclass
class EvalSample:
    """单条评估样本。"""
    question: str
    reference: str


def _split_context(context: str) -> List[str]:
    """把 docs_to_context 拼接后的上下文拆回多个 retrieved_contexts。"""
    if not context or not context.strip():
        return []
    parts = re.split(r"(?=上下文\d+\s*\(来源[:：][^)]+\):)", context)
    chunks = [part.strip() for part in parts if part.strip()]
    return chunks or [context.strip()]


def _build_ragas_runtime(service: EnterpriseAssistantService):
    """构造 Ragas 评估用的 LLM、Embedding、指标。"""
    ragas_llm = llm_factory(
        model=service.llm.config.chat_model,
        client=service.llm.client
    )
    ragas_embeddings = LangchainEmbeddingsWrapper(
        embeddings=service.index_manager.embedding_client.embedding
    )
    metrics = [
        deepcopy(context_precision),
        deepcopy(context_recall),
        deepcopy(faithfulness),
        deepcopy(answer_relevancy)
    ]
    return ragas_llm, ragas_embeddings, metrics


def run_eval_with_ragas(
        service: EnterpriseAssistantService,
        samples: List[EvalSample],
        options: RetrievalOptions,
):
    """运行 Ragas 评估，返回 pandas DataFrame 或原始 EvaluationResult。

    options.strategy 可以传普通 RAG、LlamaIndex 或 LangGraph Agent 策略。
    """
    if not samples:
        raise ValueError("评估样本不能为空。")
    rows = []
    for sample in samples:
        pack = service.answer(sample.question, options=options)
        rows.append(
            {
                "user_input": sample.question,
                "response": pack.answer,
                "retrieved_contexts": _split_context(pack.context),
                "reference": sample.reference
            }
        )
    eval_dataset = EvaluationDataset.from_list(rows)
    ragas_llm, ragas_embeddings, metrics = _build_ragas_runtime(service)
    result = evaluate(
        dataset=eval_dataset,
        llm=ragas_llm,
        embeddings=ragas_embeddings,
        metrics=metrics,
        raise_exceptions=False,
        show_progress=True,
        batch_size=4,
    )
    return result.to_pandas() if hasattr(result, "to_pandas") else result


if __name__ == "__main__":
    load_dotenv()

    service = build_service()

    samples = [
        EvalSample(
            question="病假需要提交哪些材料？如果是临时生病来不及走系统怎么办？",
            reference=(
                "病假在紧急情况下可以先口头报备，返岗后2个工作日内补齐系统申请和医院证明材料。"
                "连续病假超过2天时，还需要上传就诊证明或电子病历截图。"
            ),
        ),
        EvalSample(
            question="报销最晚多久内提交？跨月费用怎么处理？发票有什么要求？",
            reference=(
                "费用发生后应在10个自然日内发起报销申请。跨月费用需在次月第3个工作日前完成提交，"
                "逾期要补充说明。报销需上传清晰完整的电子发票或纸质票据扫描件，"
                "发票抬头、税号、金额和开票日期必须可识别。"
            ),
        ),
        EvalSample(
            question="远程办公补贴标准是多少？如果我要远程办公，需要提前多久申请、说明什么？",
            reference=(
                "当前制度中没有写明远程办公补贴标准。远程办公应至少提前半个工作日提交申请，"
                "并说明工作计划、在线时段和协作方式；远程办公期间应保持企业IM、邮件和电话可联系状态。"
                "若要确认补贴标准，建议咨询HR或相关管理部门。"
            ),
        ),
    ]

    eval_strategies = [
        RetrievalStrategy.HYBRID,
        RetrievalStrategy.LANGGRAPH_AGENT,
    ]
    for strategy in eval_strategies:
        options = RetrievalOptions(
            strategy=strategy,
            top_k=4,
            enable_rerank=False,
        )
        print(f"\n===== Ragas 评估策略: {strategy.value} =====")
        df = run_eval_with_ragas(service, samples, options)
        print(df.to_string(index=False) if hasattr(df, "to_string") else df)
