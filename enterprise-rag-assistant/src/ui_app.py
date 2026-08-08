# Gradio界面
import gradio as gr

from src.rag_service import EnterpriseAssistantService
from src.rag_types import RetrievalStrategy, RetrievalOptions, RerankMethod


def build_gradio_app(service: EnterpriseAssistantService) -> gr.Blocks:
    """构建 Gradio 应用。"""
    implementation_choices = ["langchain", "llamaindex", "langgraph"]
    langchain_strategy_choices = [
        RetrievalStrategy.PLAIN.value,
        RetrievalStrategy.QUERY2DOC.value,
        RetrievalStrategy.HYDE.value,
        RetrievalStrategy.REWRITE.value,
        RetrievalStrategy.STEP_BACK.value,
        RetrievalStrategy.SUB_QUESTION.value,
        RetrievalStrategy.PARENT_CHILD.value,
        RetrievalStrategy.SUMMARY_INDEX.value,
        RetrievalStrategy.HYPOTHETICAL_QUESTION.value,
        RetrievalStrategy.MULTI_INDEX.value,
        RetrievalStrategy.HYBRID.value,
        RetrievalStrategy.ITERATIVE.value,
        RetrievalStrategy.SENTENCE_WINDOW.value,
        RetrievalStrategy.AUTO_MERGING.value,
        RetrievalStrategy.SELF_RAG.value,
        RetrievalStrategy.SELF_RAG_LANGGRAPH.value,
    ]
    llamaindex_strategy_choices = [
        RetrievalStrategy.LLAMA_PLAIN.value,
        RetrievalStrategy.LLAMA_SENTENCE_WINDOW.value,
        RetrievalStrategy.LLAMA_AUTO_MERGING.value,
        RetrievalStrategy.LLAMA_HYDE.value,
        RetrievalStrategy.LLAMA_QUERY_FUSION.value,
        RetrievalStrategy.LLAMA_HYBRID.value,
        RetrievalStrategy.LLAMA_RERANK.value,
        RetrievalStrategy.LLAMA_ROUTER.value,
        RetrievalStrategy.LLAMA_RECURSIVE.value,
        RetrievalStrategy.LLAMA_SUMMARY.value,
        RetrievalStrategy.LLAMA_AUTO_RETRIEVAL.value,
        RetrievalStrategy.LLAMA_GRAPH.value,
    ]
    langgraph_strategy_choices = [
        RetrievalStrategy.LANGGRAPH_AGENT.value,
    ]

    def _strategy_choices(implementation):
        if implementation == "langgraph":
            return langgraph_strategy_choices, RetrievalStrategy.LANGGRAPH_AGENT.value
        if implementation == "llamaindex":
            return llamaindex_strategy_choices, RetrievalStrategy.LLAMA_HYBRID.value
        return langchain_strategy_choices, RetrievalStrategy.HYBRID.value

    def _change_implementation(implementation):
        choices, default_strategy = _strategy_choices(implementation)
        return (
            gr.update(choices=choices, value=default_strategy),
            gr.update(value=implementation == "langchain"),
        )

    def _chat(
            message,
            history,
            implementation,
            strategy,
            top_k,
            use_rerank,
            rerank_top_n,
            rerank_method,
            bm25_weight,
            vector_weight,
            enable_triad_eval,
    ):
        if not message.strip():
            return history, "请输入问题。", "", ""
        options = RetrievalOptions(
            strategy=RetrievalStrategy(strategy),
            top_k=int(top_k),
            enable_rerank=use_rerank,
            rerank_top_n=int(rerank_top_n),
            rerank_method=RerankMethod(rerank_method),
            bm25_weight=float(bm25_weight),
            vector_weight=float(vector_weight),
            enable_triad_eval=enable_triad_eval,
        )
        try:
            pack = service.answer(message, options)
        except Exception as exc:
            err = f"执行失败：{exc}"
            history = history + [(message, err)]
            return history, err, "", ""
        ref_text = "\n".join(f"- {r}" for r in pack.references) if pack.references else "- 无"
        debug_text = (
            f"route={pack.route}\n"
            f"implementation={implementation}\n"
            f"strategy={pack.strategy}\n"
            f"debug={pack.debug_note}\n"
        )
        if pack.triad_report:
            debug_text += f"\n{pack.triad_report}\n"
        bot_text = f"{pack.answer}\n\n【引用来源】\n{ref_text}"
        history = history + [(message, bot_text)]
        return history, debug_text, pack.context, ""

    with gr.Blocks(title="企业知识库 RAG 助手") as demo:
        gr.Markdown("# 企业知识库 RAG 助手")
        gr.Markdown(
            "策略说明：`langgraph_agent` 是 Agentic RAG；`self_rag` 需要 `langgraph`，`llama_*` 需要 LlamaIndex 依赖。"
        )
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="对话区", height=520)
                msg = gr.Textbox(label="你的问题", placeholder="比如：病假需要什么材料？")
                send_btn = gr.Button("发送", variant="primary")
            with gr.Column(scale=2):
                implementation = gr.Dropdown(
                    label="检索实现",
                    choices=implementation_choices,
                    value="langchain",
                )
                strategy = gr.Dropdown(
                    label="检索增强策略",
                    choices=langchain_strategy_choices,
                    value="hybrid",
                )
                top_k = gr.Slider(label="Top K", minimum=1, maximum=10, value=3, step=1)
                use_rerank = gr.Checkbox(label="启用 Rerank", value=True)
                rerank_top_n = gr.Slider(label="Rerank Top N", minimum=1, maximum=10, value=4, step=1)
                rerank_method = gr.Dropdown(
                    label="Rerank 方法",
                    choices=[RerankMethod.LLM.value, RerankMethod.LLM_BATCH.value],
                    value=RerankMethod.LLM.value,
                )
                bm25_weight = gr.Slider(label="Hybrid: BM25 权重", minimum=0.0, maximum=1.0, value=0.35, step=0.05)
                vector_weight = gr.Slider(label="Hybrid: 向量权重", minimum=0.0, maximum=1.0, value=0.65, step=0.05)
                enable_triad_eval = gr.Checkbox(
                    label="启用 RAG Triad 评估",
                    value=False,
                )

                debug_box = gr.Textbox(label="调试信息", lines=8)
                context_box = gr.Textbox(label="命中上下文", lines=14)

        send_btn.click(
            _chat,
            inputs=[
                msg,
                chatbot,
                implementation,
                strategy,
                top_k,
                use_rerank,
                rerank_top_n,
                rerank_method,
                bm25_weight,
                vector_weight,
                enable_triad_eval,
            ],
            outputs=[chatbot, debug_box, context_box, msg],
        )
        implementation.change(
            _change_implementation,
            inputs=[implementation],
            outputs=[strategy, use_rerank],
        )
        msg.submit(
            _chat,
            inputs=[
                msg,
                chatbot,
                implementation,
                strategy,
                top_k,
                use_rerank,
                rerank_top_n,
                rerank_method,
                bm25_weight,
                vector_weight,
                enable_triad_eval,
            ],
            outputs=[chatbot, debug_box, context_box, msg],
        )

    return demo
