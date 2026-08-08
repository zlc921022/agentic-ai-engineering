"""Launch the Gradio interface without models or knowledge-base indexing."""

from __future__ import annotations

import os

from app import _patch_gradio_app
from src.ui_app import build_gradio_app


class PreviewService:
    """Fail clearly if someone submits a query from UI-only preview mode."""

    def answer(self, *_args, **_kwargs):
        raise RuntimeError("当前为 UI Preview，请配置 .env 并启动正式服务。")


def main() -> None:
    app = build_gradio_app(PreviewService())
    _patch_gradio_app(app)
    app.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        show_api=False,
    )


if __name__ == "__main__":
    main()
