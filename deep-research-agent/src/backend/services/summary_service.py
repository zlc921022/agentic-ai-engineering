import time
from typing import Callable, Iterator

from backend.core.app_logger import get_logger
from backend.domain.models import SearchResult
from backend.llm.prompts import ResearchPrompts
from backend.llm.simple_agent import SimpleAgent


AgentFactory = Callable[[str, str], SimpleAgent]
SUMMARY_MAX_TOKENS = 4096


class SummaryService:
    """任务总结服务：把一个子任务的搜索上下文压缩成结构化研究结论。

    TaskExecutor 每完成一个 search，就会调用 SummaryService。
    这个服务会为每个任务创建独立 summary agent，避免不同任务的 LLM
    message history 互相污染。

    举例：
    某个任务检索到 5 个来源后，SummaryService 会要求模型输出：
    任务总结、核心发现、工程落地建议、证据边界和检索来源。
    """

    def __init__(
            self,
            agent_factory: AgentFactory,
    ):
        """注入 agent_factory，用于按 task_id 创建独立 summary agent。"""
        self.agent_factory = agent_factory
        self.logger = get_logger(__name__)

    def run_summary(self, search_result: SearchResult) -> str:
        """非流式生成任务总结。

        当前主流程使用 stream_summary() 给前端展示增量输出；
        这个方法主要保留给测试或未来批处理场景。
        """
        prompt = self.build_summary_prompt(search_result)
        started_at = time.perf_counter()
        self.logger.info(
            "summary llm started task_id=%s title=%s prompt_chars=%s max_tokens=%s",
            search_result.task_id,
            search_result.title,
            len(prompt),
            SUMMARY_MAX_TOKENS,
        )
        agent = self.agent_factory(
            f"summary_task_{search_result.task_id}",
            ResearchPrompts.SUMMARY_SYSTEM,
        )
        summary = agent.run(prompt, max_tokens=SUMMARY_MAX_TOKENS)
        self.logger.info(
            "summary llm done task_id=%s summary_chars=%s elapsed=%.2fs",
            search_result.task_id,
            len(summary or ""),
            time.perf_counter() - started_at,
        )
        return summary

    def stream_summary(self, search_result: SearchResult) -> tuple[Iterator[str], Callable[[], str]]:
        """流式总结任务。
        - build_summary_prompt() 生成完整任务提示词；
        - 直接把 prompt 当作 input_text 传给 agent.stream_run()；
        - 不额外传 system_prompt，避免 stream_run 把 system_prompt 透传给 llm.stream。
        """
        prompt = self.build_summary_prompt(search_result)
        started_at = time.perf_counter()
        self.logger.info(
            "summary stream started task_id=%s title=%s prompt_chars=%s max_tokens=%s",
            search_result.task_id,
            search_result.title,
            len(prompt),
            SUMMARY_MAX_TOKENS,
        )
        agent = self.agent_factory(
            f"summary_task_{search_result.task_id}",
            ResearchPrompts.SUMMARY_SYSTEM,
        )
        chunks: list[str] = []
        chunk_count = 0

        def generator() -> Iterator[str]:
            """逐块转发 summary 输出，同时缓存完整任务总结。"""
            nonlocal chunk_count
            failed = False
            try:
                for chunk in agent.stream_run(prompt, max_tokens=SUMMARY_MAX_TOKENS):
                    if not chunk:
                        continue

                    chunk_count += 1
                    chunks.append(chunk)
                    yield chunk
            except Exception:
                failed = True
                self.logger.exception(
                    "summary stream failed task_id=%s title=%s elapsed=%.2fs",
                    search_result.task_id,
                    search_result.title,
                    time.perf_counter() - started_at,
                )
                raise
            finally:
                summary_chars = len("".join(chunks))
                self.logger.info(
                    "summary stream %s task_id=%s chunks=%s summary_chars=%s elapsed=%.2fs",
                    "failed" if failed else "done",
                    search_result.task_id,
                    chunk_count,
                    summary_chars,
                    time.perf_counter() - started_at,
                )

        def get_summary() -> str:
            """返回已经累计完成的完整任务总结。"""
            return "".join(chunks).strip()

        return generator(), get_summary

    @staticmethod
    def build_summary_prompt(search_result: SearchResult):
        """根据 SearchResult 组装 SUMMARY prompt。

        search_results_text 是 SearchService 构建的长研究上下文，
        包含来源 ID、标题、URL、来源类型、评分和正文片段。
        """
        return ResearchPrompts.SUMMARY.format(
            task_title=search_result.title,
            task_intent=search_result.intent,
            task_query=search_result.query,
            search_results=search_result.search_results_text,
        )
