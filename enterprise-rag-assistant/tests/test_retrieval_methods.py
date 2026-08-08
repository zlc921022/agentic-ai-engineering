import contextlib
import io
import logging
import unittest

import jieba
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from src.retrieval_enhance import RetrievalEnhancer
from src.retrieval_types import RetrievalResult


jieba.setLogLevel(logging.ERROR)


def _doc(text: str, source: str = "rules.md") -> Document:
    return Document(page_content=text, metadata={"file_name": source})


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, prompt: str, **kwargs) -> str:
        self.calls.append((prompt, kwargs))

        if "请把用户问题扩写成一段像企业制度文档的短文" in prompt:
            return "扩写后的制度关键词"

        if "请基于常见企业制度，生成一段可能回答该问题的短文" in prompt:
            return "假设答案文本"

        if "请把下面问题拆成最多 3 个子问题" in prompt:
            return "病假需要什么材料\n报销流程是什么\n审批时效多久"

        if "请把用户问题改写成适合检索企业制度文档的问题" in prompt:
            return "正式检索问题"

        if "请把下面问题抽象成一个更通用的制度问题" in prompt:
            return "通用制度问题"

        if "请评估下面文档对问题的相关性" in prompt:
            if "HIGH" in prompt:
                return "95"
            if "MID" in prompt:
                return "60"
            return "10"

        if "请根据用户问题，对候选文档按相关性排序" in prompt:
            return "2,1"

        if "请根据上下文给出简短答案" in prompt:
            return "草稿答案"

        if "你是企业员工助手，需要根据上下文回答问题" in prompt:
            return "基础总入口回答"

        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    def stream(self, prompt: str, **kwargs):
        self.calls.append((prompt, kwargs))
        yield "流式"
        yield "回答"


class FakeEmbeddingClient:
    def __init__(self):
        self.calls = []

    def embed_query(self, text: str):
        self.calls.append(text)
        if text == "假设答案文本":
            return [2.0, 4.0, 6.0]
        return [4.0, 6.0, 8.0]


class FakeRetriever(BaseRetriever):
    docs: list

    def _get_relevant_documents(self, query: str, *, run_manager=None):
        return self.docs


class FakeRuleStore:
    def __init__(self, docs):
        self.docs = docs
        self.search_kwargs = None

    def as_retriever(self, search_kwargs=None):
        self.search_kwargs = search_kwargs
        return FakeRetriever(docs=self.docs)


class FakeIndexManager:
    def __init__(self):
        self.search_calls = []
        self.vector_search_calls = []
        self.all_docs_calls = 0
        self.rule_store = FakeRuleStore([
            _doc("VECTOR_DOC VPN 设备故障处理"),
            _doc("DUPLICATE_DOC 重复文档"),
        ])
        self.query_results = {}
        self.vector_results = []
        self.all_docs = [
            _doc("BM25_DOC VPN 账号申请"),
            _doc("DUPLICATE_DOC 重复文档"),
        ]

    def _search_rules(self, query: str, k: int = 4):
        self.search_calls.append((query, k))
        docs = self.query_results.get(query)
        if docs is None:
            docs = [_doc(f"SEARCH_DOC {query}")]
        return docs[:k]

    def _search_rules_by_vector(self, vector, k: int = 4):
        self.vector_search_calls.append((vector, k))
        docs = self.vector_results or [_doc("VECTOR_SEARCH_DOC")]
        return docs[:k]

    def _all_rule_documents(self):
        self.all_docs_calls += 1
        return list(self.all_docs)


class FakeMultiIndexRetriever:
    def __init__(self):
        self.calls = []

    def parent_child_retrieve(self, query, k):
        self.calls.append(("parent_child", query, k))
        return RetrievalResult("parent_child_retrieve", [_doc("parent child")], "父子块索引检索")

    def summary_retrieve(self, query, k):
        self.calls.append(("summary", query, k))
        return RetrievalResult("summary_retrieve", [_doc("summary")], "摘要索引检索")

    def hypothetical_question_retrieve(self, query, k):
        self.calls.append(("hypothetical_question", query, k))
        return RetrievalResult("hypothetical_question_retrieve", [_doc("hq")], "假设问题索引检索")

    def multi_index_retrieve(self, query, k):
        self.calls.append(("multi_index", query, k))
        return RetrievalResult("multi_index_retrieve", [_doc("multi")], "多索引融合检索")


def _enhancer():
    llm = FakeLLM()
    embedding = FakeEmbeddingClient()
    index = FakeIndexManager()
    enhancer = RetrievalEnhancer(llm=llm, embedding_client=embedding, index_manager=index)
    enhancer.multi_index_retriever = FakeMultiIndexRetriever()
    return enhancer, llm, embedding, index


def _quiet(callable_):
    with contextlib.redirect_stdout(io.StringIO()):
        return callable_()


class RetrievalMethodTests(unittest.TestCase):
    def test_plain_retrieve_uses_original_query(self):
        enhancer, _, _, index = _enhancer()

        result = enhancer.plain_retrieve("VPN 怎么申请？", k=2)

        self.assertEqual(result.strategy, "plain_retrieve")
        self.assertEqual(result.debug_note, "基础向量检索")
        self.assertEqual(index.search_calls, [("VPN 怎么申请？", 2)])
        self.assertEqual(result.docs[0].page_content, "SEARCH_DOC VPN 怎么申请？")

    def test_query2doc_and_query2doc_retrieve(self):
        enhancer, _, _, index = _enhancer()

        expanded = enhancer.query2doc("报销怎么提交？")
        result = enhancer.query2doc_retrieve("报销怎么提交？", k=3)

        self.assertIn("报销怎么提交？", expanded)
        self.assertIn("扩写后的制度关键词", expanded)
        self.assertEqual(result.strategy, "query2doc_retrieve")
        self.assertEqual(index.search_calls, [(expanded, 3)])

    def test_hyde_and_hyde_retrieve(self):
        enhancer, _, embedding, index = _enhancer()
        index.vector_results = [_doc("HyDE 命中文档")]

        vector = enhancer.hyde("发烧怎么请假？", include_query=True)
        result = enhancer.hyde_retrieve("发烧怎么请假？", k=2, include_query=True)

        self.assertEqual(vector, [3.0, 5.0, 7.0])
        self.assertEqual(result.strategy, "hyde_retrieve")
        self.assertEqual(index.vector_search_calls[-1], ([3.0, 5.0, 7.0], 2))
        self.assertEqual(result.docs[0].page_content, "HyDE 命中文档")
        self.assertIn("假设答案文本", embedding.calls)

    def test_sub_question_and_sub_question_retrieve_dedupes_documents(self):
        enhancer, _, _, index = _enhancer()
        shared = _doc("共享命中文档")
        index.query_results = {
            "病假需要什么材料": [shared, _doc("病假材料")],
            "报销流程是什么": [shared, _doc("报销流程")],
            "审批时效多久": [_doc("审批时效")],
        }

        questions = enhancer.sub_question("病假和报销一起问")
        result = enhancer.sub_question_retrieve("病假和报销一起问", k=2)

        self.assertIn("病假需要什么材料", questions)
        self.assertEqual(result.strategy, "sub_question_retrieve")
        self.assertEqual([doc.page_content for doc in result.docs], ["共享命中文档", "病假材料", "报销流程", "审批时效"])

    def test_question_rewrite_and_step_back_retrievals(self):
        enhancer, _, _, index = _enhancer()

        rewrite = enhancer.question_rewrite("我发烧不想来咋办")
        rewrite_result = enhancer.question_rewrite_retrieve("我发烧不想来咋办", k=2)
        step_back = enhancer.take_step_back("今天发烧能远程办公吗")
        step_back_result = enhancer.step_back_retrieve("今天发烧能远程办公吗", k=3)

        self.assertEqual(rewrite, "正式检索问题")
        self.assertEqual(step_back, "通用制度问题")
        self.assertEqual(rewrite_result.strategy, "question_rewrite")
        self.assertEqual(step_back_result.strategy, "step_back_retrieve")
        self.assertIn(("正式检索问题", 2), index.search_calls)
        self.assertIn(("通用制度问题", 3), index.search_calls)

    def test_multi_index_methods_delegate_to_multi_index_retriever(self):
        enhancer, _, _, _ = _enhancer()

        parent = enhancer.parent_child_retrieve("请假", k=2)
        summary = enhancer.summary_retrieve("请假", k=3)
        hq = enhancer.hypothetical_question_retrieve("请假", k=4)
        multi = enhancer.multi_index_retrieve("请假", k=5)

        self.assertEqual(parent.strategy, "parent_child_retrieve")
        self.assertEqual(summary.strategy, "summary_retrieve")
        self.assertEqual(hq.strategy, "hypothetical_question_retrieve")
        self.assertEqual(multi.strategy, "multi_index_retrieve")
        self.assertEqual(
            enhancer.multi_index_retriever.calls,
            [
                ("parent_child", "请假", 2),
                ("summary", "请假", 3),
                ("hypothetical_question", "请假", 4),
                ("multi_index", "请假", 5),
            ],
        )

    def test_hybrid_retrieve_combines_bm25_and_vector_results(self):
        enhancer, _, _, index = _enhancer()

        result = enhancer.hybrid_retrieve("VPN", k=2)

        self.assertEqual(result.strategy, "hybrid_retrieve")
        self.assertEqual(index.rule_store.search_kwargs, {"k": 2})
        self.assertEqual(index.all_docs_calls, 1)
        self.assertLessEqual(len(result.docs), 4)
        self.assertEqual(len({doc.page_content for doc in result.docs}), len(result.docs))

    def test_rerank_with_llm_orders_by_score(self):
        enhancer, _, _, _ = _enhancer()
        docs = [_doc("LOW 文档"), _doc("HIGH 文档"), _doc("MID 文档")]

        ranked = _quiet(lambda: enhancer.rerank_with_llm("报销", docs, top_n=2))

        self.assertEqual([doc.page_content for doc in ranked], ["HIGH 文档", "MID 文档"])

    def test_rerank_with_llm_batch_and_rank_entrypoint(self):
        enhancer, _, _, _ = _enhancer()
        docs = [_doc("第一篇"), _doc("第二篇"), _doc("第三篇")]

        ranked = _quiet(lambda: enhancer.rerank_with_llm_batch("报销", docs, top_n=2))
        ranked_from_entrypoint, note = _quiet(
            lambda: enhancer.rerank("报销", docs, top_n=2, method="llm_batch")
        )

        self.assertEqual([doc.page_content for doc in ranked], ["第二篇", "第一篇"])
        self.assertEqual([doc.page_content for doc in ranked_from_entrypoint], ["第二篇", "第一篇"])
        self.assertEqual(note, "rank_with_llm_batch")

    def test_iterative_retrieve_uses_draft_answer_for_second_search(self):
        enhancer, _, _, index = _enhancer()

        result = enhancer.iterative_retrieve("报销怎么提交？", k=2, max_iters=2)

        self.assertEqual(result.strategy, "iterative_retrieve")
        self.assertEqual(index.search_calls[0], ("报销怎么提交？", 2))
        self.assertEqual(index.search_calls[1], ("报销怎么提交？ 草稿答案", 2))
        self.assertEqual(result.debug_note, "迭代检索轮数=2")

    def test_run_rag_pipeline_supports_query_vector_doc_and_stream_modes(self):
        enhancer, _, _, index = _enhancer()
        doc = _doc("直接传入的文档")

        answer, context = enhancer.run_rag_pipeline("怎么报销？", "报销", k=2)
        vector_answer, vector_context = enhancer.run_rag_pipeline(
            "怎么报销？", [1.0, 2.0, 3.0], k=1, context_query_type="vector"
        )
        doc_answer, doc_context = enhancer.run_rag_pipeline(
            "怎么报销？", [doc], context_query_type="doc"
        )
        stream, stream_context = enhancer.run_rag_pipeline("怎么报销？", "报销", stream=True)

        self.assertEqual(answer, "基础总入口回答")
        self.assertIn("SEARCH_DOC 报销", context)
        self.assertEqual(vector_answer, "基础总入口回答")
        self.assertIn("VECTOR_SEARCH_DOC", vector_context)
        self.assertEqual(doc_answer, "基础总入口回答")
        self.assertIn("直接传入的文档", doc_context)
        self.assertEqual("".join(stream), "流式回答")
        self.assertIn(("报销", 2), index.search_calls)
        self.assertIn(([1.0, 2.0, 3.0], 1), index.vector_search_calls)
        self.assertIn("SEARCH_DOC 报销", stream_context)


if __name__ == "__main__":
    unittest.main()
