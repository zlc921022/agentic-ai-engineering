import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backend.core.app_logger import get_logger
from backend.domain.models import TodoItem
from backend.notes.notes_index import NotesIndex


@dataclass
class NoteItem:
    """一条笔记的元信息。
    只记录笔记身份和文件位置。
    具体内容直接写入 markdown 文件，不长期塞在内存对象里。
    """
    note_id: str
    title: str
    note_path: str
    note_type: str = "task_state"
    task_id: int | None = None
    content_preview: str = ""


class NoteService:
    """最小 MVP 版笔记服务。
    目标：
    - 不让 LLM 主动调用 note 工具；
    - 由后端在 planner/search/summary/report 阶段主动写笔记；
    - 用一个 index.json 按 run_id 组织新生成的任务笔记和报告；
    - 每次写入后返回 note 元信息，由 agent.py 统一发 note_event。
    """

    def __init__(self, workspace: str | Path | None = None):
        """初始化笔记工作区和 notes/index.json。"""
        # 默认写到 deep-research-agent/notes，避免启动目录不同导致笔记散落到不同位置。
        self.workspace = Path(workspace) if workspace else Path(__file__).resolve().parents[2] / "notes"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.index = NotesIndex(self.workspace / "index.json")
        self.logger = get_logger(__name__)

    def start_run(self, run_id: str, topic: str) -> None:
        """在索引里登记一次新的研究运行。"""
        self._safe_index_update(
            "start_run",
            lambda: self.index.start_run(run_id, topic),
        )

    def finish_run(self, run_id: str, status: str) -> None:
        """更新一次研究运行的最终状态。"""
        self._safe_index_update(
            "finish_run",
            lambda: self.index.update_run_status(run_id, status),
        )

    def create_task_note(
            self,
            task: TodoItem,
            *,
            run_id: str,
    ) -> NoteItem:
        """为 planner 生成的任务创建 Markdown 笔记。"""
        note_id = self._make_note_id(task.id)
        note_path = self.workspace / f"{note_id}.md"

        task.note_path = str(note_path)
        task.note_id = note_id

        content = (
            f"# 任务 {task.id}: {task.title}\n\n"
            f"## 任务概览\n\n"
            f"- 意图：{task.intent}\n"
            f"- 查询：{task.query}\n"
            f"- 状态：{task.status}\n"
        )

        note_path.write_text(content, encoding="utf-8")

        note = NoteItem(
            note_id=note_id,
            title=f"任务 {task.id}: {task.title}",
            note_path=str(note_path),
            task_id=task.id,
            content_preview=self._preview(content),
        )
        self._safe_index_update(
            "create_task_note",
            lambda: self.index.upsert_task_note(
                run_id=run_id,
                note_id=note.note_id,
                task_id=task.id,
                title=note.title,
                note_path=note_path.name,
                status=task.status,
                source_count=len(task.search_results),
                summary_chars=len(task.summary or ""),
            ),
        )
        return note

    def update_note_sources(
            self,
            task: TodoItem,
            *,
            run_id: str,
    ) -> NoteItem | None:
        """把任务检索来源追加写入任务笔记。"""
        if not task.note_path:
            return None

        content = (
            f"\n## 最新来源\n\n"
            f"{task.source_summary or '暂无来源'}\n\n"
        )

        self._append(task.note_path, content)
        note = self._task_note_item(task, content)
        self._update_task_index(note, task, run_id)
        return note

    def update_note_summary(
            self,
            task: TodoItem,
            *,
            run_id: str,
    ) -> NoteItem | None:
        """把任务总结追加写入任务笔记。"""
        if not task.note_path:
            return None

        content = (
            f"\n## 任务总结\n\n"
            f"{task.summary or '暂无总结'}\n\n"
        )

        self._append(task.note_path, content)
        note = self._task_note_item(task, content)
        self._update_task_index(note, task, run_id)
        return note

    def update_task_status(
            self,
            task: TodoItem,
            *,
            run_id: str,
    ) -> None:
        """任务异常时也同步索引状态，不额外修改 Markdown 正文。"""
        note = self._task_note_item(task)
        if note.note_id:
            self._update_task_index(note, task, run_id)

    def create_report_note(
            self,
            topic: str,
            report: str,
            *,
            run_id: str,
            evaluator: dict[str, Any],
    ) -> NoteItem:
        """创建最终报告笔记，并在索引中登记报告元数据。"""
        note_id = self._make_note_id("report")
        note_path = self.workspace / f"{note_id}.md"

        title = f"研究报告：{topic}"
        content = f"# {title}\n\n{report or '暂无报告'}\n"

        note_path.write_text(content, encoding="utf-8")

        note = NoteItem(
            note_id=note_id,
            title=title,
            note_path=str(note_path),
            note_type="report",
            content_preview=self._preview(content),
        )
        score = evaluator.get("overall_score")
        if not isinstance(score, (int, float)):
            score = None
        warnings = evaluator.get("warnings")
        warning_count = len(warnings) if isinstance(warnings, list) else 0
        self._safe_index_update(
            "create_report_note",
            lambda: self.index.set_report_note(
                run_id=run_id,
                note_id=note.note_id,
                title=note.title,
                note_path=note_path.name,
                report_chars=len(report or ""),
                evaluator_score=score,
                warning_count=warning_count,
            ),
        )
        return note

    def _append(self, note_path: str, content: str):
        """向已有 Markdown 笔记追加内容。"""
        with open(note_path, "a", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def build_event_payload(
            note: NoteItem,
            *,
            action: str,
            label: str,
    ) -> dict[str, Any]:
        """把 NoteItem 转成前端 note_event payload。"""
        return {
            "action": action,
            "label": label,
            "note_id": note.note_id,
            "note_path": note.note_path,
            "note_type": note.note_type,
            "task_id": note.task_id,
            "title": note.title,
            "content_preview": note.content_preview,
        }

    def _task_note_item(self, task: TodoItem, content: str = "") -> NoteItem:
        """根据 TodoItem 构造任务笔记元信息。"""
        return NoteItem(
            note_id=task.note_id or "",
            title=f"任务 {task.id}: {task.title}",
            note_path=task.note_path or "",
            task_id=task.id,
            content_preview=self._preview(content),
        )

    def _update_task_index(
            self,
            note: NoteItem,
            task: TodoItem,
            run_id: str,
    ) -> None:
        """把任务笔记的最新状态同步到 index.json。"""
        self._safe_index_update(
            "update_task_note",
            lambda: self.index.upsert_task_note(
                run_id=run_id,
                note_id=note.note_id,
                task_id=task.id,
                title=note.title,
                note_path=Path(note.note_path).name,
                status=task.status,
                source_count=len(task.search_results),
                summary_chars=len(task.summary or ""),
            ),
        )

    def _safe_index_update(
            self,
            action: str,
            update: Callable[[], None],
    ) -> None:
        """索引是辅助目录；写入失败只记日志，不能打断研究和 Markdown 写入。"""
        try:
            update()
        except Exception:
            self.logger.exception(
                "note index update failed action=%s index_path=%s",
                action,
                self.index.index_path,
            )

    @staticmethod
    def _make_note_id(value: int | str) -> str:
        """生成带时间戳和随机后缀的 note_id，降低重复概率。"""
        return f"note_{int(time.time() * 1000)}_{value}_{uuid4().hex[:8]}"

    @staticmethod
    def _preview(content: str, limit: int = 220) -> str:
        """生成 note_event 中使用的短内容预览。"""
        text = " ".join(str(content or "").split())
        if len(text) <= limit:
            return text
        return text[:limit] + "..."
