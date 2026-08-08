import logging
from typing import Any, Callable


def run_stage(
        stage: str,
        fn: Callable[[], Any],
        default: Any = None,
        errors: list[dict[str, Any]] | None = None,
        logger: logging.Logger | None = None,
) -> Any:
    """类似 Kotlin runCatching 的阶段执行包装。

    只负责捕获异常、记录日志、收集错误并返回默认值；
    是否中断后续流程由外层业务代码决定。
    """
    try:
        return fn()
    except Exception as exc:
        if logger is not None:
            logger.exception("%s stage failed", stage)

        if errors is not None:
            errors.append({
                "stage": stage,
                "message": str(exc),
            })

        return default


def has_error(errors: list[dict[str, Any]], stage: str) -> bool:
    """判断某个阶段是否已经记录过错误。"""
    return any(error.get("stage") == stage for error in errors)
