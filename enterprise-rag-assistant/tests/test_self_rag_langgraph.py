import contextlib
import io
import unittest

from langchain_core.documents import Document

from src.retrieval_enhance import RetrievalEnhancer


def _doc(text: str, source: str = "rules.md") -> Document:
    return Document(page_content=text, metadata={"file_name": source})


class FakeLLM:
    """Deterministic LLM for self-RAG graph path tests."""

    def __init__(self, *, generations=None, supported=None, useful=None):
        self.generations = list(generations or ["默认生成答案"])
        self.supported = list(supported or ["yes"])
        self.useful = list(useful or ["yes"])
        self.calls = []

    def complete(self, prompt: str, **kwargs) -> str:
        self.calls.append((prompt, kwargs))

        if "请把用户问题扩写成一段像企业制度文档的短文" in prompt:
            return "QUERY2DOC_EXPANDED_POLICY"

        if "请把用户问题改写成适合检索企业制度文档的问题" in prompt:
            return "REWRITE_POLICY_QUERY"

        if "请判断候选文档是否有助于回答用户问题" in prompt:
            if "ALLOW_DOC" in prompt:
                return "yes"
            return "no"

        if "判断答案是否被上下文支持" in prompt:
            return self.supported.pop(0)

        if "判断答案是否被有效回复问题" in prompt:
            return self.useful.pop(0)

        if "你是企业员工助手，必须根据给定上下文回答问题" in prompt:
            return self.generations.pop(0)

        raise AssertionError(f"Unexpected prompt:\n{prompt}")


class FakeEmbeddingClient:
    pass


class SequenceIndexManager:
    """Returns one configured document batch for each search call."""

    def __init__(self, *batches):
        self.batches = list(batches)
        self.search_calls = []

    def _search_rules(self, query: str, k: int = 4):
        self.search_calls.append((query, k))
        if not self.batches:
            return []
        return self.batches.pop(0)[:k]


def _enhancer(llm: FakeLLM, index_manager: SequenceIndexManager) -> RetrievalEnhancer:
    return RetrievalEnhancer(
        llm=llm,
        embedding_client=FakeEmbeddingClient(),
        index_manager=index_manager,
    )


def _run_graph(enhancer: RetrievalEnhancer, query: str, k: int = 4):
    # The teaching implementation prints each streamed LangGraph node.
    # Tests keep stdout quiet so failures stay easy to read.
    with contextlib.redirect_stdout(io.StringIO()):
        return enhancer.self_rag_answer_langgraph(query, k=k)


class SelfRagLangGraphTests(unittest.TestCase):
    def test_returns_answer_when_first_generation_is_useful(self):
        llm = FakeLLM(generations=["病假需要提交病假证明。"], supported=["yes"], useful=["yes"])
        index = SequenceIndexManager([
            _doc("ALLOW_DOC 病假制度：病假需要提交病假证明。")
        ])
        enhancer = _enhancer(llm, index)

        result = _run_graph(enhancer, "病假需要什么材料？", k=1)

        self.assertEqual(result["answer"], "病假需要提交病假证明。")
        self.assertEqual(result["debug_note"], "generation is useful")
        self.assertEqual(len(result["docs"]), 1)
        self.assertEqual(index.search_calls, [("病假需要什么材料？", 1)])

    def test_uses_query2doc_once_when_initial_documents_are_irrelevant(self):
        llm = FakeLLM(generations=["报销需要在规定时限内提交发票。"], supported=["yes"], useful=["yes"])
        index = SequenceIndexManager(
            [_doc("BLOCK_DOC 这段制度和问题无关。")],
            [_doc("ALLOW_DOC 报销制度：报销需要提交发票。")],
        )
        enhancer = _enhancer(llm, index)

        result = _run_graph(enhancer, "报销怎么弄？", k=4)

        self.assertEqual(result["answer"], "报销需要在规定时限内提交发票。")
        self.assertEqual(len(index.search_calls), 2)
        self.assertEqual(index.search_calls[0], ("报销怎么弄？", 4))
        self.assertIn("QUERY2DOC_EXPANDED_POLICY", index.search_calls[1][0])
        self.assertEqual(index.search_calls[1][1], 4)

    def test_falls_back_when_query2doc_still_has_no_documents(self):
        llm = FakeLLM()
        index = SequenceIndexManager(
            [_doc("BLOCK_DOC 这段制度和问题无关。")],
            [],
        )
        enhancer = _enhancer(llm, index)

        result = _run_graph(enhancer, "完全查不到的问题", k=4)

        self.assertEqual(result["answer"], "当前上下文不足以支持明确结论，建议咨询 HR 或相关部门进一步确认。")
        self.assertEqual(result["docs"], [])
        self.assertIn("final_decision=no_documents", result["debug_note"])
        self.assertEqual(len(index.search_calls), 2)
        self.assertFalse(any("必须根据给定上下文回答问题" in prompt for prompt, _ in llm.calls))

    def test_falls_back_when_generation_is_not_supported(self):
        llm = FakeLLM(generations=["公司允许无限期带薪休假。"], supported=["no"], useful=["yes"])
        index = SequenceIndexManager([
            _doc("ALLOW_DOC 年假制度：年假天数按司龄计算。")
        ])
        enhancer = _enhancer(llm, index)

        result = _run_graph(enhancer, "年假怎么算？", k=1)

        self.assertEqual(result["answer"], "当前上下文不足以支持明确结论，建议咨询 HR 或相关部门进一步确认。")
        self.assertIn("final_decision=not_supported", result["debug_note"])
        self.assertEqual(len(index.search_calls), 1)

    def test_rewrites_once_when_supported_generation_is_not_useful(self):
        llm = FakeLLM(
            generations=["请参考公司制度。", "报销需要提交发票并按流程审批。"],
            supported=["yes", "yes"],
            useful=["no", "yes"],
        )
        index = SequenceIndexManager(
            [_doc("ALLOW_DOC 报销制度：报销需要提交发票。")],
            [_doc("ALLOW_DOC 报销流程：提交发票后走审批。")],
        )
        enhancer = _enhancer(llm, index)

        result = _run_graph(enhancer, "报销流程是什么？", k=1)

        self.assertEqual(result["answer"], "报销需要提交发票并按流程审批。")
        self.assertEqual(result["debug_note"], "generation is useful")
        self.assertEqual(len(index.search_calls), 2)
        self.assertEqual(index.search_calls[1], ("REWRITE_POLICY_QUERY", 1))


if __name__ == "__main__":
    unittest.main()
