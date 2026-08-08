import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ResearchEvent:
    """后端对前端输出的统一事件模型。

    所有 SSE 事件最终都会落到这个结构，保证 run_id、seq、stage、status、
    payload、error 等字段稳定存在。
    """
    run_id: str
    seq: int
    type: str
    stage: str = "workflow"
    status: str = "info"
    message: str = ""
    step: int = 0
    task_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转成普通 dict，便于 FastAPI/SSE JSON 序列化。"""
        return asdict(self)
