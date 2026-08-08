from dataclasses import dataclass

from backend.domain.events import EventEmitter
from backend.domain.models import ResearchState
from backend.workflow.research_event_builder import ResearchEventBuilder
from backend.workflow.research_stage_logger import ResearchStageLogger
from backend.workflow.task_executor import TaskExecutor


@dataclass(frozen=True)
class ResearchRunContext:
    """单次研究运行上下文。

    这个 dataclass 把一次 run 内共享的状态对象打包传递，避免 DeepResearchAgent
    上挂太多临时属性。

    举例：
    run_stream() 创建一个 ResearchRunContext 后，run_plan、run_report、
    run_evaluator 都只接收 ctx，就能拿到 emitter、state、event_builder、
    stage_logger 和 task_executor。
    """
    emitter: EventEmitter
    state: ResearchState
    event_builder: ResearchEventBuilder
    stage_logger: ResearchStageLogger
    task_executor: TaskExecutor
