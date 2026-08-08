"""Markdown Note 的轻量元数据索引。

当前阶段使用单个 notes/index.json：
- 一条 run 代表一次完整研究；
- task_notes 和 report_note 内嵌在所属 run 中；
- Markdown 正文仍保存在独立文件，不重复写入索引。

以后数据量明显增大时，可以整体迁移到 SQLite；当前不做 runs/notes 两张表。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from uuid import uuid4


INDEX_VERSION = 1

# DeepResearchAgent 每个请求都会创建一个 NoteService。不同请求可能同时写同一个
# index.json，因此锁必须按索引路径在进程内共享，不能只放在 NoteService 实例上。
_LOCKS_GUARD = Lock()
_PATH_LOCKS: dict[str, Lock] = {}


def _lock_for(path: Path) -> Lock:
    """按索引文件路径获取进程内共享锁。"""
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, Lock())


def _now_iso() -> str:
    """生成带时区的秒级 ISO 时间。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class NotesIndex:
    """维护一个按研究运行分组的扁平 JSON 索引。"""

    def __init__(self, index_path: str | Path):
        """初始化索引路径和路径级共享锁。"""
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.index_path)

    def start_run(self, run_id: str, topic: str) -> None:
        """登记一次新研究，并将 latest_run_id 指向它。"""

        def mutate(data: dict[str, Any]) -> None:
            """写入或更新 run 基础元数据。"""
            now = _now_iso()
            run = self._find_run(data, run_id)
            if run is None:
                data["runs"].append(
                    {
                        "run_id": run_id,
                        "topic": topic,
                        "status": "running",
                        "created_at": now,
                        "updated_at": now,
                        "task_notes": [],
                        "report_note": None,
                    }
                )
            else:
                run["topic"] = topic
                run["status"] = "running"
                run["updated_at"] = now
            data["latest_run_id"] = run_id

        self._update(mutate)

    def update_run_status(self, run_id: str, status: str) -> None:
        """更新整次研究状态，例如 completed、failed。"""

        def mutate(data: dict[str, Any]) -> None:
            """修改指定 run 的状态和更新时间。"""
            run = self._require_run(data, run_id)
            run["status"] = status
            run["updated_at"] = _now_iso()

        self._update(mutate)

    def upsert_task_note(
        self,
        *,
        run_id: str,
        note_id: str,
        task_id: int,
        title: str,
        note_path: str,
        status: str,
        source_count: int | None = None,
        summary_chars: int | None = None,
    ) -> None:
        """创建或更新某个任务 Note 的元数据。"""

        def mutate(data: dict[str, Any]) -> None:
            """在 run.task_notes 中 upsert 任务笔记。"""
            run = self._require_run(data, run_id)
            now = _now_iso()
            task_note = next(
                (
                    item
                    for item in run["task_notes"]
                    if item.get("note_id") == note_id
                ),
                None,
            )
            if task_note is None:
                task_note = {
                    "note_id": note_id,
                    "task_id": task_id,
                    "title": title,
                    "note_path": note_path,
                    "status": status,
                    "source_count": 0,
                    "summary_chars": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                run["task_notes"].append(task_note)

            task_note.update(
                {
                    "task_id": task_id,
                    "title": title,
                    "note_path": note_path,
                    "status": status,
                    "updated_at": now,
                }
            )
            if source_count is not None:
                task_note["source_count"] = source_count
            if summary_chars is not None:
                task_note["summary_chars"] = summary_chars
            run["updated_at"] = now

        self._update(mutate)

    def set_report_note(
        self,
        *,
        run_id: str,
        note_id: str,
        title: str,
        note_path: str,
        report_chars: int,
        evaluator_score: int | float | None,
        warning_count: int,
    ) -> None:
        """登记一次研究的最终报告 Note。"""

        def mutate(data: dict[str, Any]) -> None:
            """写入 run.report_note 元数据。"""
            run = self._require_run(data, run_id)
            now = _now_iso()
            previous = run.get("report_note")
            created_at = (
                previous.get("created_at")
                if isinstance(previous, dict)
                else now
            )
            run["report_note"] = {
                "note_id": note_id,
                "title": title,
                "note_path": note_path,
                "report_chars": report_chars,
                "evaluator_score": evaluator_score,
                "warning_count": warning_count,
                "created_at": created_at,
                "updated_at": now,
            }
            run["updated_at"] = now

        self._update(mutate)

    def read(self) -> dict[str, Any]:
        """返回当前完整索引；主要用于查询、调试和测试。"""
        with self._lock:
            return self._read_unlocked()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """按 run_id 查询一次研究。"""
        data = self.read()
        return self._find_run(data, run_id)

    def _update(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        """在同一把锁内完成 read-modify-write，避免并发更新互相覆盖。"""
        with self._lock:
            data = self._read_unlocked()
            mutate(data)
            self._write_unlocked(data)

    def _read_unlocked(self) -> dict[str, Any]:
        """读取索引文件。

        调用方必须已经持有 self._lock；方法名里的 unlocked 是提醒不要在这里重复加锁。
        """
        if not self.index_path.exists():
            return {
                "version": INDEX_VERSION,
                "latest_run_id": None,
                "runs": [],
            }

        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
            raise ValueError(f"Note 索引格式无效：{self.index_path}")
        if data.get("version") != INDEX_VERSION:
            raise ValueError(
                f"Note 索引版本不支持：{data.get('version')}"
            )
        return data

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        """先写临时文件再原子替换，避免进程中断留下半截 JSON。"""
        temp_path = self.index_path.with_name(
            f".{self.index_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.index_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _find_run(
        data: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any] | None:
        """在索引数据中查找指定 run。"""
        return next(
            (
                run
                for run in data.get("runs", [])
                if isinstance(run, dict) and run.get("run_id") == run_id
            ),
            None,
        )

    @classmethod
    def _require_run(
        cls,
        data: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        """查找 run，不存在时抛出明确错误。"""
        run = cls._find_run(data, run_id)
        if run is None:
            raise KeyError(f"Note 索引中不存在 run_id={run_id}")
        return run
