# self_rag
from typing import Dict, Any, Tuple, List, TypedDict

from langchain_core.documents import Document
from langgraph.constants import END
from langgraph.graph import StateGraph

from enterprise_employee_assistant.src.client import QwenChatClient
from enterprise_employee_assistant.src.index_manager import ChromaIndexManager
from enterprise_employee_assistant.src.retrieval_util import docs_to_context, _is_yes


class SelfRagRetriever:

    def __init__(self,
                 llm: QwenChatClient,
                 index_manager: ChromaIndexManager,
                 ):
        self.llm = llm
        self.index_manager = index_manager

    def query2doc(self, query: str) -> str:
        prompt = f"""
                  请把用户问题扩写成一段像企业制度文档的短文。
                  保留原意，补充可能出现的制度关键词。
                  用户问题：{query}
                  """
        pseudo_doc = self.llm.complete(prompt)
        return query + "\n" + pseudo_doc

    def question_rewrite(self, query: str) -> str:
        prompt = f"""
                    请把用户问题改写成适合检索企业制度文档的问题。
                    保留原意，补充关键词。
                    原问题：{query}
                 """
        return self.llm.complete(prompt).strip()

    def self_rag_answer(self, query: str, k: int = 4) -> Dict[str, Any]:
        """线性版 Self-RAG。
            流程：
            1. 原问题检索
            2. 判断文档是否相关
            3. 文档不够好时，query2doc 再检索一次
            4. 生成答案
            5. 判断答案是否被上下文支持
            6. 判断答案是否真正回答问题
            7. 不够好时 rewrite 再试一次
            8. 仍失败则安全兜底
        """

        # 原问题检索, 返回检索之后的docs和上下文
        def _retrieve(context_query: str) -> Tuple[List[Document], str]:
            docs = self.index_manager._search_rules(context_query, k)
            context = docs_to_context(docs)
            return docs, context

        # 判断文档是否相关, 返回相关文档，相关文档对应上下文，是否需要增强检索
        def _grade_documents(question: str, docs: List[Document]) -> Tuple[List[Document], str, bool]:
            """过滤不相关文档，并判断是否需要增强检索。"""
            filtered_docs = []
            for doc in docs:
                prompt = f"""
                   请判断候选文档是否有助于回答用户问题。
                   判断标准：
                   - 能直接或间接帮助回答问题，输出 yes
                   - 明显无关，输出 no
                   - 只输出 yes 或 no
                   用户问题: {question}
                   候选文档：
                   {doc.page_content}
                   """
                result = self.llm.complete(prompt, temperature=0, max_tokens=8)
                if _is_yes(result):
                    filtered_docs.append(doc)
            # 优化
            need_enhance = len(filtered_docs) < min(2, k)
            context = docs_to_context(filtered_docs)
            return filtered_docs, context, need_enhance

        # 生成答案, 返回大模型生成的答案
        def _generate(question: str, context) -> str:
            """基于上下文生成答案。"""
            prompt = f"""
               你是企业员工助手，必须根据给定上下文回答问题。
               要求：
               1. 如果上下文不足，请明确说“当前上下文不足以确认”
               2. 不要编造制度中没有的信息
               3. 回答要简洁清楚
               4. 优先说明流程、材料、时效、审批链路
               5. 最后给出引用来源
               用户问题：
               {question}
               上下文：
               {context}
               请输出：
               - 结论
               - 操作步骤
               - 引用来源
               """
            return self.llm.complete(prompt, temperature=0.1)

        # 判断生成的答案能否被上下文支持
        def _is_supported(answer: str, context: str) -> bool:
            """判断答案是否被上下文支持。"""
            prompt = f"""
               请判断答案是否被上下文支持。
               判断标准：
               - 如果答案中的关键结论都能从上下文找到依据，输出 yes
               - 如果答案包含上下文没有的信息、编造的制度、编造的数字，输出 no
               - 只输出 yes 或 no
               上下文：
               {context}
               答案：
               {answer}
               """
            result = self.llm.complete(prompt, temperature=0, max_tokens=8)
            return _is_yes(result)

        def _is_useful(question: str, answer: str) -> bool:
            """判断答案是否真正回答了问题。"""
            prompt = f"""
               请判断答案是否真正回答了用户问题。
               判断标准：
               - 如果答案正面回答了用户关心的问题，输出 yes
               - 如果答案答非所问、太泛泛、没有解决用户问题，输出 no
               - 只输出 yes 或 no
               用户问题：
               {question}
               答案：
               {answer}
               """
            result = self.llm.complete(prompt, temperature=0, max_tokens=8)
            return _is_yes(result)

        # 没有命中
        def _fallback(docs: List[Document], context: str, debug_note) -> Dict[str, Any]:
            """安全兜底。"""
            return {
                "answer": "当前上下文不足以支持明确结论，建议咨询 HR 或相关部门进一步确认。",
                "docs": docs,
                "context": context,
                "debug_note": debug_note
            }

        # 定义两个计数器，确保 query_doc 和 rewrite都只执行一次
        query2doc_count = 0
        rewrite_count = 0
        # 原始问题检索，得到文档和上下文
        docs, context = _retrieve(query)
        # 判断文档是否相关, 返回相关文档，相关文档对应上下文，是否需要增强检索
        docs, context, need_enhance = _grade_documents(query, docs)
        # 需要增强检索，就去调用query2doc，重新走_retrieve和_grade_documents方法
        if need_enhance and query2doc_count < 1:
            query_doc = self.query2doc(query)
            docs, context = _retrieve(query_doc)
            docs, context, need_enhance = _grade_documents(query, docs)
            query2doc_count += 1
        # 过滤后仍然没有文档，直接兜底
        if not docs:
            return _fallback(
                docs=docs,
                context=context,
                debug_note=f"self-rag: no relevant docs, query2doc_count={query2doc_count}",
            )
        # 生成答案
        answer = _generate(query, context)
        # 生成的答案不被上下文支持，直接返回
        if not _is_supported(answer, context):
            return _fallback(
                docs=docs,
                context=context,
                debug_note=f"self-rag: first answer not supported, query2doc_count={query2doc_count}",
            )
        # 生成的答案是有效答案，直接返回
        if _is_useful(query, answer):
            return {
                "answer": answer,
                "docs": docs,
                "context": context,
                "debug_note": f"self-rag: first pass useful, query2doc_count={query2doc_count}",
            }
        # 答案是上下文支持，但不是有效答案，则走rewrite
        if rewrite_count < 1:
            rewrite_query = self.question_rewrite(query)
            docs, context = _retrieve(rewrite_query)
            docs, context, need_enhance = _grade_documents(query, docs)
            rewrite_count += 1
        # 再次过滤后仍然没有文档，直接兜底
        if not docs:
            return _fallback(
                docs=docs,
                context=context,
                debug_note=(
                    "self-rag: no relevant docs after rewrite "
                    f"(query2doc_count={query2doc_count}, rewrite_count={rewrite_count})"
                ),
            )
        # 再次生成答案
        answer = _generate(query, context)
        # 答案是上下文支持，并且答案是有效答案，直接返回结果
        if _is_supported(answer, context) and _is_useful(query, answer):
            return {
                "answer": answer,
                "docs": docs,
                "context": context,
                "debug_note": (
                    "self-rag: rewrite pass useful "
                    f"(query2doc_count={query2doc_count}, rewrite_count={rewrite_count})"
                ),
            }
        # 否则返回兜底
        return _fallback(
            docs=docs,
            context=context,
            debug_note=(
                "self-rag: rewrite pass failed "
                f"(query2doc_count={query2doc_count}, rewrite_count={rewrite_count})"
            ),
        )

    def self_rag_answer_langgraph(self, query: str, k: int = 4) -> Dict[str, Any]:
        """LangGraph 版 self-RAG，用来和线性版 self_rag_answer 做对比。
           这版对应 self_rag_answer 的完整流程：
           retrieve -> grade_documents -> query2doc? -> retrieve -> generate
           -> grade_generation -> rewrite? -> retrieve -> ...

           这里把 grade_generation 拆成两个部分：
           - grade_generation 节点：负责调用 LLM 判断，并把 final_decision 写入 state
           - route_after_generation 条件边：只负责根据 final_decision 选下一步
        """

        class _GraphState(TypedDict):
            keys: Dict[str, Any]

        # 安全兜底用
        def _safe_fallback(docs: List[Document], context: str, debug_note: str) -> Dict[str, Any]:
            return {
                "answer": "当前上下文不足以支持明确结论，建议咨询 HR 或相关部门进一步确认。",
                "docs": docs,
                "context": context,
                "debug_note": debug_note,
            }

        # 检索，返回文档docs+文档上下文
        def _retrieve(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            question = keys.get("question", "")
            context_query = keys.get("context_query") or question
            docs = self.index_manager._search_rules(context_query, k=k)
            context = docs_to_context(docs)
            return {
                "keys": {
                    **keys,
                    "context": context,
                    "documents": docs,
                }
            }

        # 检查文档是否相关，返回相关文档+相关文档对应上下文+是否需要query2doc
        def _grade_documents(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            question = keys.get("question", "")
            docs = keys.get("documents", [])
            # 过滤之后文档
            filtered_docs = []
            for doc in docs:
                prompt = f"""
                     请判断候选文档是否有助于回答用户问题。
                      判断标准：
                      - 能直接或间接帮助回答问题，输出 yes
                      - 明显无关，输出 no
                      - 只输出 yes 或 no
                      用户问题: {question}
                      候选文档：
                      {doc.page_content}
                   """
                result = self.llm.complete(prompt, temperature=0, max_tokens=8)
                if _is_yes(result):
                    filtered_docs.append(doc)
            need_enhance = len(filtered_docs) < min(k, 2)
            context = docs_to_context(filtered_docs)
            return {
                "keys": {
                    **keys,
                    "context": context,
                    "documents": filtered_docs,
                    "need_enhance": need_enhance,
                }
            }

        # 根据检索结果，判断下一步是query2doc还是生成答案
        def _decide_to_generate(state: Dict[str, Any]) -> str:
            keys = state.get("keys", {})
            need_enhance = keys.get("need_enhance", False)
            query2doc_count = keys.get("query2doc_count", 0)
            rewrite_count = keys.get("rewrite_count", 0)
            docs = keys.get("documents", [])
            if need_enhance and query2doc_count < 1 and rewrite_count == 0:
                return "transform_query2doc"
            elif not docs:
                return "no_documents"
            else:
                return "generate"

        # query2doc 之后需要重新走_retrieve，返回context_query
        def _transform_query2doc(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            query2doc_count = keys.get("query2doc_count", 0) + 1
            question = keys.get("question", query)
            query_doc = self.query2doc(question)
            return {
                "keys": {
                    **keys,
                    "query2doc_count": query2doc_count,
                    "context_query": query_doc
                }
            }

        # 新增 query2doc只有没有文档的节点
        def _no_documents(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            return {
                "keys": {
                    **keys,
                    "final_decision": "no_documents",
                }
            }

        # 生成答案, 返回问题和答案
        def _generate(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            question = keys.get("question", "")
            context = keys.get("context", "")
            prompt = f"""
                  你是企业员工助手，必须根据给定上下文回答问题。
                  要求：
                  1. 如果上下文不足，请明确说“当前上下文不足以确认”
                  2. 不要编造制度中没有的信息
                  3. 回答要简洁清楚
                  4. 优先说明流程、材料、时效、审批链路
                  5. 最后给出引用来源
                  用户问题：
                  {question}
                  上下文：
                  {context}
                  请输出：
                  - 结论
                  - 操作步骤
                  - 引用来源
                  """
            generation = self.llm.complete(prompt, temperature=0.1)
            return {
                "keys": {
                    **keys,
                    "question": question,
                    "generation": generation
                }
            }

        # 根据问题和答案，判断上下文是否支持，答案是否有效
        def _grade_generation(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            generation = keys.get("generation", "")
            question = keys.get("question", "")
            rewrite_count = keys.get("rewrite_count", 0)
            context = keys.get("context", "")
            # 上下文是否支持
            prompt = f"""
               判断答案是否被上下文支持，
               答案: {generation}
               上下文：{context}
               只回复 yes 和 no
               """
            is_supported_result = self.llm.complete(prompt, temperature=0, max_tokens=8)
            # 答案是否有效
            prompt1 = f"""
               判断答案是否被有效回复问题，
               答案: {generation}
               问题：{question}
               只回复 yes 或 no
               """
            is_useful_result = self.llm.complete(prompt1, temperature=0, max_tokens=8)
            # 转成 bool
            supported = _is_yes(is_supported_result)
            useful = _is_yes(is_useful_result)
            # 最终的结论，是否支持，是否有效
            if not supported:
                final_decision = "not_supported"
            elif useful:
                final_decision = "useful"
            elif rewrite_count < 1:
                final_decision = "transform_rewrite"
            else:
                final_decision = "end"
            return {
                "keys": {
                    **keys,
                    "final_decision": final_decision,
                }
            }

        # 根据_grade_generation结果判断下一步是 end，还是rewrite，还是fallback
        def _route_after_generation(state: Dict[str, Any]) -> str:
            return state.get("keys", {}).get("final_decision", "end")

        # rewrite 之后需要重新走_retrieve，返回rewrite_query
        def _transform_rewrite(state: Dict[str, Any]) -> Dict[str, Any]:
            keys = state.get("keys", {})
            question = keys.get("question", query)
            rewrite_query = self.question_rewrite(question)
            rewrite_count = keys.get("rewrite_count", 0) + 1
            return {
                "keys": {
                    **keys,
                    "rewrite_count": rewrite_count,
                    "context_query": rewrite_query
                }
            }

        # 添加节点
        workflow = StateGraph(_GraphState)
        workflow.add_node("retrieve", _retrieve)
        workflow.add_node("grade_documents", _grade_documents)
        workflow.add_node("transform_query2doc", _transform_query2doc)
        workflow.add_node("no_documents", _no_documents)
        workflow.add_node("generate", _generate)
        workflow.add_node("grade_generation", _grade_generation)
        workflow.add_node("transform_rewrite", _transform_rewrite)
        # 设置起点
        workflow.set_entry_point("retrieve")
        # 添加边，retrieve执行之后一定会执行 grade_documents
        workflow.add_edge("retrieve", "grade_documents")
        # 添加条件边 grade_documents 执行之后，根据条件判断执行 transform_query2doc 还是 generate
        workflow.add_conditional_edges(
            "grade_documents",
            _decide_to_generate,
            {
                "transform_query2doc": "transform_query2doc",
                "generate": "generate",
                "no_documents": "no_documents"
            }
        )
        # 如果query2doc 之后还是没有文档，应该直接end
        workflow.add_edge("no_documents", END)
        # 执行答案生成之后，执行答案判断
        workflow.add_edge("generate", "grade_generation")
        # transform_query2doc 之后重新 retrieve
        workflow.add_edge("transform_query2doc", "retrieve")
        # 生成答案之后，判断答案是否支持上下文和答案是否有效
        workflow.add_conditional_edges(
            "grade_generation",
            _route_after_generation,
            {
                "not_supported": END,
                "end": END,
                "transform_rewrite": "transform_rewrite",
                "useful": END
            }
        )
        # transform_rewrite 之后重新 retrieve
        workflow.add_edge("transform_rewrite", "retrieve")

        input = {
            "keys": {
                "question": query,
                "query2doc_count": 0,
                "rewrite_count": 0,
            }
        }

        app = workflow.compile()
        last_node = None
        for output in app.stream(input):
            print(output)
            for _, node in output.items():
                last_node = node

        if last_node is None:
            return _safe_fallback(
                docs=[],
                context="找不到上下文",
                debug_note="没有结果"
            )

        keys = last_node.get("keys", {})
        question = keys.get("question", "")
        generation = keys.get("generation", "")
        context = keys.get("context", "")
        context_query = keys.get("context_query", "")
        docs = keys.get("documents", [])
        final_decision = keys.get("final_decision", "")
        query2doc_count = keys.get("query2doc_count", 0)
        need_enhance = keys.get("need_enhance", False)
        print(
            f"question: {question}, generation:{generation}, context_query: {context_query}, final_decision: {final_decision}, "
            f"query2doc_count: {query2doc_count}, need_enhance: {need_enhance}, docs: {docs}")
        if final_decision == "useful":
            return {
                "answer": generation,
                "docs": docs,
                "context": context,
                "debug_note": "generation is useful"
            }
        return _safe_fallback(
            docs=docs,
            context=context,
            debug_note=f"generation is not useful, final_decision={final_decision}"
        )
