import time
from typing import Any

from backend.core.app_logger import get_logger
from backend.core.config import Config
from backend.core.safe_runner import run_stage, has_error
from backend.domain.events import EventEmitter
from backend.domain.models import ResearchState, TodoItem
from backend.llm.client import QwenChatClient
from backend.llm.function_calling_agent import FunctionCallingAgent
from backend.llm.simple_agent import SimpleAgent
from backend.llm.usage import usage_run_scope
from backend.notes.note_service import NoteService
from backend.search.search_tool import SearchTool
from backend.services.planer_service import PlanerService
from backend.services.report_evaluator import ReportEvaluatorService
from backend.services.report_judge_service import ReportJudgeService
from backend.services.report_reflection_service import ReportReflectionService
from backend.services.report_service import ReportService
from backend.services.search_quality_retry_service import SearchQualityRetryService
from backend.services.search_service import SearchService
from backend.services.summary_service import SummaryService
from backend.tools.tool_registry import ToolRegistry
from backend.tools.supplemental_search_tool import SupplementalSearchTool
from backend.workflow.research_event_builder import ResearchEventBuilder
from backend.workflow.research_run_context import ResearchRunContext
from backend.workflow.research_stage_logger import ResearchStageLogger
from backend.workflow.result_builder import ResultBuilder
from backend.workflow.task_executor import TaskExecutor


class DeepResearchAgent:
    """深度研究主编排器，负责串起一次完整研究流程。

    这个类只做“流程编排”，尽量不承载具体业务细节：
    - planner 阶段交给 PlanerService 生成 TodoItem；
    - 多个子任务交给 TaskExecutor 并发执行；
    - reporter 阶段交给 ReportService 生成最终报告；
    - evaluator / judge / reflection 负责质量检查和一次性修正。

    举例：
    用户输入“AI Agent 在生产环境中如何评测和调试？”
    DeepResearchAgent 会先拆成多个研究任务，再并行检索和总结，
    最后汇总成带证据表、质检结果和运行记录的研究结果。
    """

    def __init__(
            self,
            llm: QwenChatClient,
            tool_registry: ToolRegistry,
            config: Config | None = None,
    ):
        """初始化主 Agent 依赖。

        参数说明：
        - llm：统一的大模型客户端，planner / summary / reporter / judge 都复用它。
        - tool_registry：工具注册表，SimpleAgent 通过它执行工具调用。
        - config：运行配置；为空时从环境变量加载，方便本地调试和部署切换。
        """
        self.config = config or Config.from_env()
        self.llm = llm
        self.tool_registry = tool_registry
        self.search_tool = SearchTool(self.config)
        self.planer = PlanerService(self.create_agent(
            name="planner",
            system_prompt=""
        ))
        # 补检索质量门仍使用确定性规则；只有真正执行补搜时，才根据配置选择
        # 原规则 query 或原生 Function Calling。
        retry_service = SearchQualityRetryService()
        function_calling_agent = self._create_search_retry_agent()
        self.search_service = SearchService(
            self.search_tool,
            self.config,
            retry_service,
            function_calling_agent=function_calling_agent,
        )
        self.summary_service = SummaryService(self.agent_factory)
        self.reporter = ReportService(
            self.create_agent(
                name="reporter",
                system_prompt=""
            )
        )
        self.report_reflection_service = ReportReflectionService(
            self.create_agent(
                name="reflection",
                system_prompt=""
            )
        )

        self.report_judge_service = ReportJudgeService(
            self.create_agent(
                name="judge",
                system_prompt=""
            )
        )

        self.note_service = (
            NoteService(self.config.notes_workspace)
            if self.config.notes_enabled
            else None
        )
        self.logger = get_logger(__name__)

        # 根据当前注入的配置和服务刷新拆分后的辅助组件。
        self.result_builder = ResultBuilder()

    def _create_search_retry_agent(self) -> FunctionCallingAgent | None:
        """按配置创建可插拔补检索 Agent。

        默认 ``SEARCH_RETRY_MODE=rule`` 时不创建额外 Agent，现有行为完全不变；
        开启 Function Calling 后只注册受限的 supplemental_search 工具。
        """
        if self.config.search_retry_mode != "function_calling":
            return None

        registry = ToolRegistry()
        registry.register_tool(SupplementalSearchTool(self.search_tool))
        return FunctionCallingAgent(
            llm=self.llm,
            tool_registry=registry,
            max_steps=self.config.function_calling_max_steps,
            system_prompt=(
                "你是深度研究任务的补检索决策器。当前系统已经完成第一轮检索，"
                "但来源质量规则判断证据仍不足。你必须调用 supplemental_search "
                "生成一条与原始 query 不重复、且能补齐关键证据缺口的查询。"
            ),
        )

    def create_agent(
            self,
            name: str,
            system_prompt: str,
    ) -> SimpleAgent:
        """创建一个带名称的 SimpleAgent。

        不同阶段使用不同 agent name，主要是为了日志和调试时能看出
        当前 LLM 调用属于 planner、summary、reporter、judge 还是 reflection。
        """
        return SimpleAgent(
            name=name,
            llm=self.llm,
            tool_registry=self.tool_registry,
            system_prompt=system_prompt,
        )

    def agent_factory(self, name: str, system_prompt: str) -> SimpleAgent:
        """给其它服务使用的 Agent 工厂。

        SummaryService 每个任务会创建独立 summary agent，避免多个任务共用
        一份 message history 导致上下文串扰。
        """
        return self.create_agent(
            name=name,
            system_prompt=system_prompt,
        )

    def _create_run_context(
            self,
            topic: str,
            backend: str,
    ) -> ResearchRunContext:
        """为单次研究创建 per-run context。

        这里刻意把 emitter、state、event_builder、stage_logger、task_executor
        放进本次 run 的上下文，而不是挂到 DeepResearchAgent 全局实例上。
        好处是：如果以后 Agent 变成单例或多个请求并发执行，每次 run 仍然
        拿到独立状态，避免事件序号、任务状态、日志上下文互相污染。
        """
        emitter = EventEmitter()
        state = ResearchState(topic=topic, backend=backend)

        event_builder = ResearchEventBuilder(self.result_builder)
        event_builder.register(emitter, state)

        stage_logger = ResearchStageLogger(self.logger)
        stage_logger.init_logger(emitter, state)

        task_executor = TaskExecutor(
            config=self.config,
            logger=self.logger,
            search_service=self.search_service,
            summary_service=self.summary_service,
            note_service=self.note_service,
        )
        task_executor.bind(event_builder, stage_logger)

        return ResearchRunContext(
            emitter=emitter,
            state=state,
            event_builder=event_builder,
            stage_logger=stage_logger,
            task_executor=task_executor,
        )

    def run_stream(
            self,
            topic: str,
            backend: str | None = None,
    ):
        """以生成器形式执行完整研究流程并持续产出 SSE 事件。

        核心顺序：
        1. 初始化 run / note / workflow_started；
        2. planner 生成研究任务；
        3. TaskExecutor 并发执行 search -> summary；
        4. reporter 汇总最终报告；
        5. evaluator + 可选 LLM Judge 质检；
        6. reflection 按质检结果最多修正一次，并复检；
        7. 创建报告笔记并产出 workflow_done。

        前端的“运行记录”基本就是消费这里一路 yield 出去的事件。
        """
        resolved_backend = backend or self.config.default_search_backend
        ctx = self._create_run_context(topic, resolved_backend)
        # run_id 只作为 Usage 旁路采集的关联键；真正研究流程仍由原方法执行。
        with usage_run_scope(ctx.emitter.run_id):
            try:
                yield from self._run_stream_in_usage_scope(ctx)
            finally:
                clear_usage = getattr(
                    getattr(self, "llm", None),
                    "clear_usage",
                    None,
                )
                if callable(clear_usage):
                    try:
                        clear_usage(ctx.emitter.run_id)
                    except Exception:
                        # 兼容未来注入的自定义 LLM Client：即使它没有像
                        # QwenChatClient 一样自行 Fail-Open，也不能影响 SSE 收尾。
                        self.logger.exception(
                            "llm usage cleanup failed run_id=%s",
                            ctx.emitter.run_id,
                        )

    def _run_stream_in_usage_scope(
            self,
            ctx: ResearchRunContext,
    ):
        """执行原有研究流程；拆成内部生成器只为包裹 per-run Usage 上下文。"""
        emitter = ctx.emitter
        state = ctx.state
        run_started_at = time.perf_counter()

        if self.note_service:
            self.note_service.start_run(emitter.run_id, state.topic)

        ctx.stage_logger.research_started()

        yield ctx.event_builder.workflow_started()

        planner_ok = yield from self.run_plan(ctx)
        if not planner_ok:
            if self.note_service:
                self.note_service.finish_run(emitter.run_id, "failed")
            ctx.stage_logger.research_stop(
                run_started_at=run_started_at,
                msg="research run stopped run_id=%s stage=planner errors=%s elapsed=%.2fs"
            )
            return

        # Note 可通过配置关闭；关闭后不影响研究主流程。
        if self.note_service:
            for task in state.tasks:
                note = self.note_service.create_task_note(
                    task,
                    run_id=emitter.run_id,
                )
                yield ctx.event_builder.create_plan_note(
                    task_id=task.id,
                    payload=self.note_service.build_event_payload(
                        note,
                        action="create",
                        label="planner 创建任务笔记",
                    )
                )

        yield from ctx.task_executor.execute_tasks_stream(state, emitter)

        report_ok = yield from self.run_report(ctx)
        if not report_ok:
            if self.note_service:
                self.note_service.finish_run(emitter.run_id, "failed")
            ctx.stage_logger.research_stop(
                run_started_at=run_started_at,
                msg="research run stopped run_id=%s stage=reporter errors=%s elapsed=%.2fs"
            )
            return

        initial_evaluator = yield from self.run_evaluator(ctx, "initial")
        reflection_ran = yield from self.run_report_reflection(ctx, initial_evaluator)
        # 需要复检
        if reflection_ran:
            final_evaluator = yield from self.run_evaluator(ctx, "final")
            state.reflection["after"] = ReportReflectionService.snapshot_evaluator(final_evaluator)
            state.reflection["status"] = "completed"
            yield ctx.event_builder.reflection_done()

        if self.note_service:
            report_note = self.note_service.create_report_note(
                state.topic,
                state.report,
                run_id=emitter.run_id,
                evaluator=state.evaluator,
            )
            yield ctx.event_builder.create_report_note(
                payload=self.note_service.build_event_payload(
                    report_note,
                    action="create",
                    label="report 创建报告笔记",
                )
            )

            final_status = "completed_with_errors" if state.errors else "completed"
            self.note_service.finish_run(emitter.run_id, final_status)

        self._refresh_llm_usage(ctx)
        yield ctx.event_builder.workflow_done()

        ctx.stage_logger.research_done(
            run_started_at=run_started_at
        )

    def run_plan(
            self,
            ctx: ResearchRunContext
    ):
        """执行 planner 阶段。
        返回值：
        - True：planner 成功，外层继续执行任务
        - False：planner 失败，外层直接 return，中断流程
        """
        state = ctx.state
        started_at = time.perf_counter()

        ctx.stage_logger.planner_started()

        tasks = run_stage(
            stage="planner",
            fn=lambda: self.planer.run_plan(state),
            default=[],
            errors=state.errors,
            logger=self.logger,
        )
        state.tasks = tasks

        if not state.tasks:
            if not any(error.get("stage") == "planner" for error in state.errors):
                state.errors.append({
                    "stage": "planner",
                    "message": "planner 没有生成可执行任务",
                })
            state.report = self.result_builder.build_error_report("planner", state.errors)

            message = self._last_error_message(
                state.errors,
                "planner",
                "研究任务规划失败",
            )
            ctx.stage_logger.planner_failed(
                message=message,
                started_at=started_at,
            )

            self._refresh_llm_usage(ctx)
            yield from ctx.event_builder.planner_failed(message)
            return False

        ctx.stage_logger.planner_done(
            started_at=started_at,
        )

        yield ctx.event_builder.planner_done()

        return True

    def run_report(
            self,
            ctx: ResearchRunContext
    ):
        """执行最终报告生成阶段。

        只有至少一个任务完成时才生成正常报告；如果所有任务都失败，
        这里会生成错误报告并终止后续质检，避免 reporter 基于空任务硬编内容。
        """
        state = ctx.state
        started_at = time.perf_counter()
        completed_tasks = [task for task in state.tasks if task.status == "completed"]
        if not completed_tasks:
            # 所有任务都执行失败了
            yield from self._handle_all_tasks_failed(ctx, started_at)
            return False

        ctx.stage_logger.reporter_started(
            completed_tasks=completed_tasks,
        )

        yield ctx.event_builder.reporter_start(completed_tasks)

        report_stream, get_report = self.reporter.stream_report(state.topic, completed_tasks)
        try:
            for chunk in report_stream:
                yield ctx.event_builder.reporter_doing(chunk)

        except Exception as exc:
            state.errors.append({
                "stage": "reporter",
                "message": str(exc),
            })
        finally:
            state.report = get_report() or ""

        if not state.report.strip():
            if not has_error(state.errors, "reporter"):
                state.errors.append({
                    "stage": "reporter",
                    "message": "reporter 没有生成有效报告",
                })

        if has_error(state.errors, "reporter"):
            message = self._last_error_message(
                state.errors,
                "reporter",
                "最终报告生成失败"
            )
            state.report = self.result_builder.build_error_report("reporter", state.errors)
            ctx.stage_logger.reporter_failed(message, started_at)

            self._refresh_llm_usage(ctx)
            yield from ctx.event_builder.reporter_failed(message)
            return False

        state.report = self.result_builder.append_task_failure_warning(
            report=state.report,
            tasks=state.tasks,
            errors=state.errors,
        )

        ctx.stage_logger.reporter_done(
            started_at=started_at,
        )
        yield ctx.event_builder.reporter_done()
        return True

    def _refresh_llm_usage(self, ctx: ResearchRunContext) -> None:
        """把 Collector 快照写入最终结果；读取失败也不能影响研究主流程。"""
        usage_summary = getattr(
            getattr(self, "llm", None),
            "usage_summary",
            None,
        )
        if not callable(usage_summary):
            return
        try:
            ctx.state.llm_usage = usage_summary(ctx.emitter.run_id)
        except Exception:
            self.logger.exception(
                "llm usage summary failed run_id=%s",
                ctx.emitter.run_id,
            )

    def _handle_all_tasks_failed(
            self,
            ctx: ResearchRunContext,
            started_at: float
    ):
        """处理“所有子任务都失败”的降级路径。

        这是失败策略的核心边界：completed_tasks == 0 时不生成正常报告，
        直接构建错误报告，并向前端发 report_failed / workflow_failed。
        """
        state = ctx.state
        message = "所有研究任务均执行失败，跳过最终报告生成"
        if not any(error.get("stage") == "task" for error in state.errors):
            state.errors.append({
                "stage": "task",
                "message": message,
            })
        state.report = self.result_builder.build_error_report("task", state.errors)
        ctx.stage_logger.reporter_failed(message, started_at)
        self._refresh_llm_usage(ctx)
        yield from ctx.event_builder.reporter_failed(message)

    @staticmethod
    def _last_error_message(
            errors: list[dict[str, Any]],
            stage: str,
            default: str,
    ) -> str:
        """取指定阶段最近一次错误信息。"""
        for error in reversed(errors):
            if error.get("stage") == stage:
                return str(error.get("message") or default)
        return default

    def evaluate(
            self,
            report_result: str,
            errors: list[dict[str, Any]],
            topic: str,
            tasks: list[TodoItem],
    ) -> dict[str, Any]:
        """执行报告质检。

        质检分两层：
        - ReportEvaluatorService：规则质检，检查证据表、引用完整性、来源质量等硬指标；
        - ReportJudgeService：可选 LLM-as-a-Judge，检查语义质量、结构完整性和工程建议。

        返回值会写入 state.evaluator，供前端质检器、反思服务和最终 result 使用。
        """
        evaluator = ReportEvaluatorService()
        evaluation_result = run_stage(
            "evaluator",
            lambda: evaluator.run(report_result),
            default={},
            errors=errors,
            logger=self.logger,
        )
        if not self.config.enable_llm_judge:
            evaluation_result["judge"] = {
                "enabled": False,
                "status": "disabled",
            }
            return evaluation_result

        completed_tasks = [
            task for task in (tasks or [])
            if getattr(task, "status", "") == "completed"
        ]
        # 新增llm质检
        judge_result = run_stage(
            "judge",
            lambda: self.report_judge_service.run(
                rule_evaluator=evaluation_result,
                topic=topic,
                tasks=completed_tasks,
                report=report_result
            ),
            default={
                "enabled": True,
                "status": "failed",
                "score": 0,
                "verdict": "fail",
                "warnings": ["LLM Judge 调用失败"],
                "revision_advice": ["请检查报告语义质量和工程建议是否完整"],
            },
            errors=errors,
            logger=self.logger,
        )
        evaluation_result["judge"] = judge_result
        evaluation_result["hybrid_score"] = self._hybrid_score(evaluation_result, judge_result)
        return evaluation_result

    @staticmethod
    def _hybrid_score(
            rule_evaluator: dict[str, Any],
            judge_result: dict[str, Any],
    ) -> int:
        """计算规则质检和 LLM Judge 的混合分。

        当前权重是规则 60% + LLM Judge 40%：
        - 规则质检更稳定，适合作为硬约束；
        - LLM Judge 能补充语义维度，但存在模型波动，所以权重略低。
        """
        rule_score = rule_evaluator.get("overall_score") or 0
        judge_score = judge_result.get("score") or 0
        try:
            rule_score = float(rule_score)
            judge_score = float(judge_score)
        except (TypeError, ValueError):
            return int(rule_score or judge_score or 0)

        return round(rule_score * 0.6 + judge_score * 0.4)

    def run_evaluator(self, ctx: ResearchRunContext, pass_name: str):
        """运行一次 evaluator 并发出 evaluator_done 事件。

        pass_name 用来区分 initial / final：
        - initial：reporter 生成报告后的第一次质检；
        - final：reflection 修正报告后的复检。
        """
        started_at = time.perf_counter()
        ctx.stage_logger.evaluator_started()
        ctx.state.evaluator = self.evaluate(
            report_result= ctx.state.report,
            errors=ctx.state.errors,
            topic=ctx.state.topic,
            tasks =ctx.state.tasks,
        )
        ctx.stage_logger.evaluator_done(started_at)
        yield ctx.event_builder.evaluator_done(pass_name)
        return ctx.state.evaluator

    def run_report_reflection(self, ctx: ResearchRunContext, evaluator):
        """根据质检结果决定是否触发报告反思修正。

        当前实现是 MVP：最多修正一次。
        如果质检通过，则记录 reflection_skipped；
        如果触发修正，则调用 ReportReflectionService 生成修正版报告，
        后续由 run_stream 再执行一次 final evaluator。
        """
        state = ctx.state
        decision = self.report_reflection_service.decide(evaluator)
        before = ReportReflectionService.snapshot_evaluator(evaluator)

        if not decision.should_reflect:
            ctx.state.reflection = {
                "attempted": False,
                "attempts": 0,
                "status": "skipped",
                "triggers": decision.triggers,
                "before": before,
            }
            ctx.stage_logger.reflection_skipped()
            yield ctx.event_builder.reflection_skipped(state.reflection, decision.reasons)
            return False

        state.reflection = {
            "attempted": True,
            "attempts": 1,
            "status": "running",
            "triggers": decision.triggers,
            "reasons": decision.reasons,
            "before": before,
        }

        ctx.stage_logger.reflection_started(decision.triggers)
        yield ctx.event_builder.reflection_started()

        started_at = time.perf_counter()
        try:
            completed_tasks = [
                task for task in state.tasks
                if task.status == "completed"
            ]
            # 反思修正报告一次
            revised_report = self.report_reflection_service.revise_report(
                state.topic,
                completed_tasks,
                state.report,
                state.evaluator,
                decision.triggers,
            )
            if not revised_report.strip():
                raise ValueError("reflection 没有生成有效修正版报告")

            ctx.state.report = self.result_builder.append_task_failure_warning(
                revised_report,
                state.tasks,
                state.errors
            )
            state.reflection["status"] = "revised"
            state.reflection["report_chars"] = len(state.report or "")
            ctx.stage_logger.reflection_done(started_at)
            return True
        except Exception as exc:
            message = str(exc)
            state.errors.append({
                "stage": "reflection",
                "message": message,
            })
            state.reflection["status"] = "failed"
            state.reflection["error"] = message
            ctx.stage_logger.reflection_failed(message, started_at)
            yield ctx.event_builder.reflection_failed(message)
            return False
