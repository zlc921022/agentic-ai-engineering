"""深度研究助手的运行配置。

配置优先级：
1. 代码中的安全默认值；
2. deep-research-agent/.env 或当前进程环境变量；
3. 调用 Config.from_env(...) 时显式传入的覆盖值。

这里只维护当前工作台真正需要的运行参数，不把 prompt、评分规则等业务策略
全部做成环境变量，避免配置层重新膨胀。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
if load_dotenv is not None:
    # 终端临时 export 的变量优先级高于项目 .env。
    load_dotenv(PACKAGE_ROOT / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量，无法识别时使用默认值。"""
    value = os.getenv(name)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """读取正整数环境变量，非法或过小时使用默认值。"""
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _env_nonnegative_float(name: str, default: float = 0.0) -> float:
    """读取非负浮点数；主要用于可选的 Token 单价配置。"""
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _env_path(name: str, default: Path) -> Path:
    """读取路径配置；相对路径统一相对于项目根目录解析。"""
    raw_value = os.getenv(name)
    if not raw_value:
        return default

    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = PACKAGE_ROOT / path
    return path


def _env_choice(
        name: str,
        default: str,
        *,
        choices: set[str],
) -> str:
    """读取枚举配置，未知值回退到安全默认策略。"""
    value = str(os.getenv(name, default) or default).strip().lower()
    return value if value in choices else default


@dataclass(frozen=True, slots=True)
class Config:
    """深度研究助手的单次进程配置。

    `Config()` 和 `Config.from_env()` 都会读取当前环境变量，保留现有调用方式，
    同时让 main.py 可以通过 from_env() 明确表达配置来源。
    """

    # 运行目录不参与构造，也不会被 HTTP 请求覆盖。
    base_dir: ClassVar[Path] = PACKAGE_ROOT
    storage_dir: ClassVar[Path] = PACKAGE_ROOT / "storage"
    chroma_dir: ClassVar[Path] = storage_dir / "chroma"
    logs_dir: ClassVar[Path] = PACKAGE_ROOT / "logs"

    # LLM
    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv(
            "OPENAI_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/",
        )
    )
    chat_model: str = field(
        default_factory=lambda: os.getenv(
            "CHAT_MODEL",
            "qwen3.7-max-2026-05-17",
        )
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
    )
    llm_timeout_seconds: int = field(
        default_factory=lambda: _env_int("LLM_TIMEOUT_SECONDS", 180)
    )
    llm_stream_idle_timeout_seconds: int = field(
        default_factory=lambda: _env_int("LLM_STREAM_IDLE_TIMEOUT_SECONDS", 90)
    )
    # 单位：每 100 万 Token。价格默认为 0，未配置时只统计精确 Token，
    # 不生成容易误导的成本数字。
    llm_input_price_per_million: float = field(
        default_factory=lambda: _env_nonnegative_float(
            "LLM_INPUT_PRICE_PER_MILLION",
        )
    )
    llm_output_price_per_million: float = field(
        default_factory=lambda: _env_nonnegative_float(
            "LLM_OUTPUT_PRICE_PER_MILLION",
        )
    )
    llm_price_currency: str = field(
        default_factory=lambda: (
            os.getenv("LLM_PRICE_CURRENCY", "CNY").strip().upper() or "CNY"
        )
    )

    # 搜索后端与上下文
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    serpapi_api_key: str = field(default_factory=lambda: os.getenv("SERPAPI_API_KEY", ""))
    default_search_backend: str = field(
        default_factory=lambda: os.getenv("DEFAULT_SEARCH_BACKEND", "hybrid").strip().lower()
        or "hybrid"
    )
    search_max_results: int = field(
        default_factory=lambda: _env_int("SEARCH_MAX_RESULTS", 5)
    )
    search_timeout_seconds: int = field(
        default_factory=lambda: _env_int("SEARCH_TIMEOUT_SECONDS", 30)
    )
    enable_multi_query_search: bool = field(
        default_factory=lambda: _env_bool("ENABLE_MULTI_QUERY_SEARCH", True)
    )
    search_query_variant_count: int = field(
        default_factory=lambda: _env_int("SEARCH_QUERY_VARIANT_COUNT", 3, minimum=1)
    )
    fetch_full_page: bool = field(
        default_factory=lambda: _env_bool("FETCH_FULL_PAGE", True)
    )
    max_tokens_per_source: int = field(
        default_factory=lambda: _env_int("MAX_TOKENS_PER_SOURCE", 1000)
    )
    enable_search_quality_retry: bool = field(
        default_factory=lambda: _env_bool("ENABLE_SEARCH_QUALITY_RETRY", True)
    )
    search_retry_mode: str = field(
        default_factory=lambda: _env_choice(
            "SEARCH_RETRY_MODE",
            "rule",
            choices={"rule", "function_calling"},
        )
    )
    function_calling_max_steps: int = field(
        default_factory=lambda: _env_int(
            "FUNCTION_CALLING_MAX_STEPS",
            2,
            minimum=1,
        )
    )

    # 多任务并发
    task_max_workers: int = field(
        default_factory=lambda: _env_int("TASK_MAX_WORKERS", 4)
    )
    workflow_timeout_seconds: int = field(
        default_factory=lambda: _env_int("WORKFLOW_TIMEOUT_SECONDS", 900)
    )
    sse_heartbeat_seconds: int = field(
        default_factory=lambda: _env_int("SSE_HEARTBEAT_SECONDS", 15)
    )

    # Note MVP
    notes_enabled: bool = field(
        default_factory=lambda: _env_bool("NOTES_ENABLED", True)
    )
    notes_workspace: Path = field(
        default_factory=lambda: _env_path("NOTES_WORKSPACE", PACKAGE_ROOT / "notes")
    )

    enable_llm_judge: bool = field(
        default_factory=lambda: _env_bool("ENABLE_LLM_JUDGE", False)
    )
    # judge_model: str = field(
    #     default_factory=lambda: os.getenv("JUDGE_MODEL", "").strip()
    # )
    # judge_min_score: int = field(
    #     default_factory=lambda: _env_int("JUDGE_MIN_SCORE", 85, minimum=1)
    # )

    @classmethod
    def from_env(cls, **overrides: Any) -> "Config":
        """从环境变量构造配置，并允许调用方覆盖少量字段。

        当前 HTTP 接口只覆盖搜索 backend；这个入口主要方便测试和未来扩展，
        不代表所有参数都需要暴露给前端。
        """
        values = {
            key: value
            for key, value in overrides.items()
            if value is not None
        }
        return cls(**values)

    def ensure_dirs(self) -> None:
        """确保运行时目录存在。"""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if self.notes_enabled:
            self.notes_workspace.mkdir(parents=True, exist_ok=True)

    def validation_warnings(self, backend: str | None = None) -> list[str]:
        """生成可展示给前端的配置告警，不直接让页面崩溃。"""
        resolved_backend = (backend or self.default_search_backend).strip().lower()
        warnings: list[str] = []

        if not self.api_key:
            warnings.append("缺少 OPENAI_API_KEY，无法调用模型生成 planner / summary / report。")

        if self.search_retry_mode == "function_calling" and not self.api_key:
            warnings.append(
                "补检索已选择 Function Calling，但缺少 OPENAI_API_KEY；"
                "运行时会自动回退到规则补检索。"
            )

        if resolved_backend == "tavily" and not self.tavily_api_key:
            warnings.append("缺少 TAVILY_API_KEY，Tavily 搜索会自动降级到其他可用后端。")
        elif resolved_backend == "serpapi" and not self.serpapi_api_key:
            warnings.append("缺少 SERPAPI_API_KEY，SerpApi 搜索会自动降级到其他可用后端。")
        elif (
            resolved_backend == "hybrid"
            and not self.tavily_api_key
            and not self.serpapi_api_key
        ):
            warnings.append("未配置 TAVILY_API_KEY / SERPAPI_API_KEY，搜索将使用 DuckDuckGo 兜底。")

        return warnings
