"""FastAPI entrypoint for the deep research workbench.

前端使用浏览器原生 EventSource 连接后端，所以这里提供 GET 形式的 SSE 接口。
接口只负责 HTTP/SSE 适配，不掺入研究流程细节；真正流程仍由 DeepResearchAgent.run_stream()
产生标准事件。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.api.sse_stream import ResearchSseStreamer
from backend.workflow.agent import DeepResearchAgent
from backend.core.app_logger import get_logger
from backend.llm.client import QwenChatClient
from backend.core.config import Config
from backend.search.search_tool import SUPPORTED_BACKENDS
from backend.tools.tool_registry import ToolRegistry

api_logger = get_logger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用。

    这个函数只负责 HTTP 层：
    - 配置 CORS；
    - 暴露健康检查；
    - 暴露搜索后端列表；
    - 把 DeepResearchAgent.run_stream() 产出的 dict 事件包装成 SSE。

    举例：
    前端访问 /api/research/stream?topic=... 后，这里会创建一次新的
    DeepResearchAgent，并将 workflow_started、task_done、evaluator_done 等事件
    逐条推给浏览器。
    """
    app = FastAPI(title="Deep Research Assistant")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """基础健康检查，返回服务名称。"""
        return {
            "status": "ok",
            "service": "deep-research-assistant",
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """轻量健康检查，适合脚本或容器探针。"""
        return {"status": "ok"}

    @app.get("/api/backends")
    def list_backends() -> dict[str, Any]:
        """返回前端搜索后端下拉框需要的数据。"""
        config = Config.from_env()
        labels = {
            "hybrid": ("hybrid", "自动选择可用搜索后端"),
            "duckduckgo": ("duckduckgo", "无需 Key 的 DuckDuckGo 搜索"),
            "tavily": ("tavily", "Tavily 搜索，需要 TAVILY_API_KEY"),
            "serpapi": ("serpapi", "SerpApi 搜索，需要 SERPAPI_API_KEY"),
        }
        ordered = ["hybrid", "duckduckgo", "tavily", "serpapi"]

        return {
            "default": config.default_search_backend,
            "backends": [
                {
                    "value": backend,
                    "label": labels.get(backend, (backend, backend))[0],
                    "description": labels.get(backend, (backend, backend))[1],
                }
                for backend in ordered
                if backend in SUPPORTED_BACKENDS
            ],
        }

    @app.get("/api/research/stream")
    def stream_research(
        topic: str = Query(..., min_length=1),
        backend: str | None = Query(default=None),
    ) -> StreamingResponse:
        """启动一次研究流程，并把 DeepResearchAgent 事件转成 SSE。

        前端 EventSource 只能发 GET 请求，所以 topic/backend 放在 query string。
        每条事件使用 event: research_event，和前端 addEventListener("research_event") 对齐。
        """
        config = Config.from_env()
        config.ensure_dirs()
        resolved_backend = backend or config.default_search_backend
        api_logger.info(
            "research request config topic=%s backend=%s model=%s base_url=%s "
            "fetch_full_page=%s max_tokens_per_source=%s search_max_results=%s "
            "task_max_workers=%s notes_enabled=%s",
            topic,
            resolved_backend,
            config.chat_model,
            config.base_url,
            config.fetch_full_page,
            config.max_tokens_per_source,
            config.search_max_results,
            config.task_max_workers,
            config.notes_enabled,
        )
        agent = DeepResearchAgent(
            config=config,
            llm=QwenChatClient(config),
            tool_registry=ToolRegistry(),
        )
        warnings = config.validation_warnings(backend=resolved_backend)
        streamer = ResearchSseStreamer(
            agent=agent,
            config=config,
            logger=api_logger,
        )

        return StreamingResponse(
            streamer.stream(
                topic=topic,
                backend=resolved_backend,
                warnings=warnings,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
