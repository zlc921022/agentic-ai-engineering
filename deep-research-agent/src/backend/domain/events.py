from uuid import uuid4
from typing import Any

from backend.domain.event_models import ResearchEvent


class EventEmitter:
    """单次研究运行的事件发射器。

    它负责给每个事件补 run_id 和递增 seq。
    EventEmitter 本身不决定事件内容，具体内容由 ResearchEventBuilder 组装。
    """

    def __init__(self, run_id: str | None = None):
        """初始化 run_id 和事件序号。"""
        self.run_id = run_id or str(uuid4())
        self.seq = 0

    def emit(
        self,
        event_type: str,
        *,
        stage: str = "workflow",
        status: str = "info",
        message: str = "",
        step: int = 0,
        task_id: int | None = None,
        payload: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建一个 ResearchEvent 并转成 dict。

        TaskExecutor 并发执行时会用 event_lock 包住 emit()，
        确保 seq 在多线程场景下仍然按发射顺序递增。
        """
        self.seq += 1
        event = ResearchEvent(
            run_id=self.run_id,
            seq=self.seq,
            type=event_type,
            stage=stage,
            status=status,
            message=message,
            step=step,
            task_id=task_id,
            error=error,
            payload=payload or {},
        )
        return event.to_dict()
