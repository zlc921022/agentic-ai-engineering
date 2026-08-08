"""项目启动入口。"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from enterprise_employee_assistant.src.client import QwenChatClient, DashScopeEmbeddingClient
from enterprise_employee_assistant.src.config import Config
from enterprise_employee_assistant.src.data_loader import DataLoader
from enterprise_employee_assistant.src.index_manager import ChromaIndexManager
from enterprise_employee_assistant.src.langgraph_enterprise_agent import EnterpriseLangGraphAgent
from enterprise_employee_assistant.src.llamaindex_retrieval_enhance import (
    LlamaIndexRetrievalConfig,
    LlamaIndexRetrievalEnhancer,
)
from enterprise_employee_assistant.src.rag_service import EnterpriseAssistantService
from enterprise_employee_assistant.src.rag_triad import RAGTriadEvaluator
from enterprise_employee_assistant.src.retrieval_enhance import RetrievalEnhancer
from enterprise_employee_assistant.src.ui_app import build_gradio_app


def _sanitize_gradio_config_dict(config: dict) -> dict:
    """关闭 API schema 暴露，减少 Gradio 在某些版本下的 schema 解析报错。"""
    config["show_api"] = False
    for dependency in config.get("dependencies", []):
        dependency["show_api"] = False
    for component in config.get("components", []):
        component.pop("api_info", None)
        component.pop("example_inputs", None)
    return config


def _patch_gradio_app(blocks) -> None:
    """给 Gradio Blocks 打补丁，兜底 get_api_info 的兼容性问题。"""
    blocks.show_api = False
    blocks.config = _sanitize_gradio_config_dict(blocks.config)

    origin_get_config_file = blocks.get_config_file

    def _safe_get_config_file():
        config = origin_get_config_file()
        return _sanitize_gradio_config_dict(config)

    blocks.get_config_file = _safe_get_config_file

    origin_get_api_info = blocks.get_api_info

    def _safe_get_api_info():
        try:
            return origin_get_api_info()
        except Exception:
            # Gradio 某些版本在复杂 schema 下会抛异常，这里兜底避免首页 500。
            return {"named_endpoints": {}, "unnamed_endpoints": {}}

    blocks.get_api_info = _safe_get_api_info


def build_service() -> EnterpriseAssistantService:
    """组装所有组件，返回可直接调用的服务对象。"""
    config = Config()
    config.ensure_dirs()
    config.check()

    llm = QwenChatClient(config)
    embedding_client = DashScopeEmbeddingClient(config)
    loader = DataLoader(chunk_size=700, chunk_overlap=80)
    index_manager = ChromaIndexManager(config, embedding_client, loader)
    # 首次启动会自动构建索引。
    index_manager._ensure_indexes(force=False)
    enhancer = RetrievalEnhancer(llm, embedding_client, index_manager)
    llamaindex_enhancer = LlamaIndexRetrievalEnhancer(
        config=config,
        index_manager=index_manager,
        embedding_client=embedding_client,
        llm=llm,
        retrieval_config=LlamaIndexRetrievalConfig(),
    )
    langgraph_agent = EnterpriseLangGraphAgent(llm, index_manager)
    triad_evaluator = RAGTriadEvaluator(llm)
    service = EnterpriseAssistantService(
        llm,
        index_manager,
        enhancer,
        llamaindex_enhancer=llamaindex_enhancer,
        langgraph_agent=langgraph_agent,
        triad_evaluator=triad_evaluator,
    )
    return service


def _launch_with_network_fallbacks(app, *, server_name: str, server_port: int | None) -> None:
    """启动 Gradio，并在端口占用或 localhost 检查失败时自动回退。"""

    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((server_name, 0))
            return int(sock.getsockname()[1])

    def _launch(port: int | None, *, share: bool = False) -> None:
        app.launch(
            server_name=server_name,
            server_port=port,
            show_api=False,
            share=share,
        )

    try:
        _launch(server_port)
        return
    except OSError as exc:
        if "Cannot find empty port" not in str(exc):
            raise
        server_port = _find_free_port()
        print(f"[启动提示] 默认端口已被占用，自动切换到 {server_port}。")
    except ValueError as exc:
        if "localhost is not accessible" not in str(exc):
            raise
        _launch(server_port, share=True)
        return

    try:
        _launch(server_port)
    except ValueError as exc:
        if "localhost is not accessible" not in str(exc):
            raise
        _launch(server_port, share=True)


def main() -> None:
    # load_dotenv() 放到最上面加载 env环境变量
    service = build_service()
    app = build_gradio_app(service)
    _patch_gradio_app(app)
    # 本地开发优先用 127.0.0.1，避免 0.0.0.0 触发 localhost 可达性检查失败。
    server_name = os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    _launch_with_network_fallbacks(
        app,
        server_name=server_name,
        server_port=server_port,
    )


if __name__ == "__main__":
    main()
