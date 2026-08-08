import contextlib
import io
import logging
import shutil
import tempfile
import unittest
from pathlib import Path

import jieba

from src.config import Config
from src.data_loader import DataLoader
from src.index_manager import ChromaIndexManager
from src.retrieval_enhance import RetrievalEnhancer


jieba.setLogLevel(logging.ERROR)


class KeywordEmbeddingClient:
    """Local deterministic embedding over real project data keywords."""

    KEYWORDS = [
        "病假",
        "年假",
        "请假",
        "报销",
        "发票",
        "差旅",
        "VPN",
        "OA",
        "电脑",
        "设备",
        "绩效",
        "入职",
        "季度",
        "市场",
        "投资",
    ]

    def get_embedding_function(self):
        return self

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        text = text or ""
        lowered = text.lower()
        vector = [float(keyword.lower() in lowered) for keyword in self.KEYWORDS]
        # The smoke embedding is intentionally semantic rather than a term-frequency
        # model: leave-related expressions should share one concept vector.
        if any(keyword in text for keyword in ("病假", "年假", "请假")):
            vector[0:3] = [1.0, 1.0, 1.0]
        # Give Chroma a stable non-zero vector even for texts outside the tiny keyword list.
        vector.append(float(len(text) % 17) / 17.0)
        return vector


class SmokeLLM:
    def complete(self, prompt: str, **kwargs) -> str:
        if "请把用户问题扩写成一段像企业制度文档的短文" in prompt:
            return "病假 请假 材料 医疗证明 企业制度"

        if "请基于常见企业制度，生成一段可能回答该问题的短文" in prompt:
            return "病假 请假 材料 医疗证明"

        if "请把下面问题拆成最多 3 个子问题" in prompt:
            return "病假需要什么材料\n病假怎么审批\n病假证明有什么要求"

        if "请把用户问题改写成适合检索企业制度文档的问题" in prompt:
            return "病假 请假 材料 医疗证明"

        if "请把下面问题抽象成一个更通用的制度问题" in prompt:
            return "员工请假制度 材料 审批"

        if "请将下面制度文档做50字以内摘要" in prompt:
            return self._summary_from_prompt(prompt)

        if "请基于以下制度文档，生成3个用户可能提出的问题" in prompt:
            return self._questions_from_prompt(prompt)

        if "请判断候选文档是否有助于回答用户问题" in prompt:
            return "yes" if self._is_leave_related(prompt) else "no"

        if "判断答案是否被上下文支持" in prompt:
            return "yes"

        if "判断答案是否被有效回复问题" in prompt:
            return "yes"

        if "请评估下面文档对问题的相关性" in prompt:
            return "95" if self._is_leave_related(prompt) else "30"

        if "请根据用户问题，对候选文档按相关性排序" in prompt:
            return "1,2,3"

        if "请根据上下文给出简短答案" in prompt:
            return "病假通常需要按请假制度提交材料。"

        if "你是企业员工助手" in prompt:
            return "病假需要按照请假制度提交相关证明材料，并按流程审批。"

        return "yes"

    def stream(self, prompt: str, **kwargs):
        yield self.complete(prompt, **kwargs)

    @staticmethod
    def _is_leave_related(text: str) -> bool:
        return any(keyword in text for keyword in ["病假", "请假", "年假", "医疗证明"])

    def _summary_from_prompt(self, prompt: str) -> str:
        if self._is_leave_related(prompt):
            return "请假 病假 年假 材料 审批"
        if "报销" in prompt or "发票" in prompt:
            return "报销 发票 差旅 审批"
        if "VPN" in prompt or "OA" in prompt or "电脑" in prompt:
            return "IT VPN OA 电脑 设备"
        return "企业制度 员工 管理"

    def _questions_from_prompt(self, prompt: str) -> str:
        if self._is_leave_related(prompt):
            return "病假需要什么材料\n年假怎么申请\n请假怎么审批"
        if "报销" in prompt or "发票" in prompt:
            return "报销需要什么发票\n差旅怎么报销\n报销审批多久"
        if "VPN" in prompt or "OA" in prompt or "电脑" in prompt:
            return "VPN怎么申请\nOA无法登录怎么办\n电脑坏了找谁"
        return "员工制度有哪些\n公司管理要求是什么\n流程怎么审批"


def _quiet(callable_):
    with contextlib.redirect_stdout(io.StringIO()):
        return callable_()


class RealDataSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="hello_rag_smoke_"))

        cls.config = Config()
        cls.config.storage_dir = cls.temp_dir / "storage"
        cls.config.chroma_dir = cls.config.storage_dir / "chroma"
        cls.config.manifest_file = cls.config.storage_dir / "manifest.json"
        cls.config.ensure_dirs()

        cls.data_loader = DataLoader(chunk_size=500, chunk_overlap=50)
        cls.embedding = KeywordEmbeddingClient()
        cls.llm = SmokeLLM()
        cls.index_manager = ChromaIndexManager(
            config=cls.config,
            embedding_client=cls.embedding,
            data_loader=cls.data_loader,
        )
        cls.index_manager._ensure_indexes(force=True)
        cls.enhancer = RetrievalEnhancer(
            llm=cls.llm,
            embedding_client=cls.embedding,
            index_manager=cls.index_manager,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_real_data_files_load_into_documents(self):
        rule_docs = self.data_loader._load_documents(self.config.data_rule_dir, "rules")
        business_docs = self.data_loader._load_documents(self.config.data_business_dir, "business")

        self.assertGreater(len(rule_docs), 0)
        self.assertGreater(len(business_docs), 0)
        self.assertTrue(any(doc.metadata["source"] == "leave_policy.txt" for doc in rule_docs))
        self.assertTrue(any("病假" in doc.page_content for doc in rule_docs))

    def test_chroma_index_builds_and_searches_real_rule_data(self):
        all_rule_docs = self.index_manager._all_rule_documents()
        docs = self.index_manager._search_rules("病假需要提交什么材料？", k=3)

        self.assertGreater(len(all_rule_docs), 0)
        self.assertGreater(len(docs), 0)
        self.assertTrue(any("病假" in doc.page_content or doc.metadata.get("source") == "leave_policy.txt" for doc in docs))

    def test_core_retrieval_strategies_smoke_on_real_rule_data(self):
        query = "病假需要提交什么材料？"

        plain = self.enhancer.plain_retrieve(query, k=3)
        q2d = self.enhancer.query2doc_retrieve(query, k=3)
        hyde = self.enhancer.hyde_retrieve(query, k=3)
        sub = self.enhancer.sub_question_retrieve(query, k=3)
        rewrite = self.enhancer.question_rewrite_retrieve(query, k=3)
        step_back = self.enhancer.step_back_retrieve(query, k=3)
        hybrid = _quiet(lambda: self.enhancer.hybrid_retrieve(query, k=3))
        iterative = self.enhancer.iterative_retrieve(query, k=3, max_iters=2)

        results = [plain, q2d, hyde, sub, rewrite, step_back, hybrid, iterative]
        for result in results:
            self.assertGreater(len(result.docs), 0, result.strategy)

    def test_multi_index_strategies_smoke_on_real_rule_data(self):
        query = "病假需要提交什么材料？"

        parent_child = _quiet(lambda: self.enhancer.parent_child_retrieve(query, k=2))
        summary = _quiet(lambda: self.enhancer.summary_retrieve(query, k=2))
        hypothetical = _quiet(lambda: self.enhancer.hypothetical_question_retrieve(query, k=2))
        multi = _quiet(lambda: self.enhancer.multi_index_retrieve(query, k=3))

        self.assertGreater(len(parent_child.docs), 0)
        self.assertGreater(len(summary.docs), 0)
        self.assertGreater(len(hypothetical.docs), 0)
        self.assertGreater(len(multi.docs), 0)

    def test_rerank_and_pipeline_smoke_on_real_rule_data(self):
        docs = self.index_manager._search_rules("病假需要提交什么材料？", k=3)

        ranked = _quiet(lambda: self.enhancer.rerank_with_llm("病假需要提交什么材料？", docs, top_n=2))
        batch_ranked = _quiet(lambda: self.enhancer.rerank_with_llm_batch("病假需要提交什么材料？", docs, top_n=2))
        answer, context = self.enhancer.run_rag_pipeline(
            query="病假需要提交什么材料？",
            context_query="病假需要提交什么材料？",
            k=3,
        )

        self.assertGreater(len(ranked), 0)
        self.assertGreater(len(batch_ranked), 0)
        self.assertIn("病假", context)
        self.assertIn("病假", answer)

    def test_self_rag_langgraph_smoke_on_real_rule_data(self):
        result = _quiet(lambda: self.enhancer.self_rag_answer_langgraph("病假需要提交什么材料？", k=2))

        self.assertIn("病假", result["answer"])
        self.assertGreater(len(result["docs"]), 0)
        self.assertEqual(result["debug_note"], "generation is useful")


if __name__ == "__main__":
    unittest.main()
