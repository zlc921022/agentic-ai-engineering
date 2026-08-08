import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.notes.notes_index import NotesIndex


class NotesIndexTest(unittest.TestCase):
    def test_index_groups_task_and_report_notes_by_run(self):
        with TemporaryDirectory() as tmp:
            index = NotesIndex(Path(tmp) / "index.json")
            index.start_run("run_abc", "RAG 幻觉治理")
            index.upsert_task_note(
                run_id="run_abc",
                note_id="note_a1",
                task_id=1,
                title="数据质量分析",
                note_path="note_a1.md",
                status="pending",
            )
            index.upsert_task_note(
                run_id="run_abc",
                note_id="note_a1",
                task_id=1,
                title="数据质量分析",
                note_path="note_a1.md",
                status="completed",
                source_count=5,
                summary_chars=2200,
            )
            index.set_report_note(
                run_id="run_abc",
                note_id="note_ar",
                title="研究报告：RAG 幻觉治理",
                note_path="note_ar.md",
                report_chars=8449,
                evaluator_score=100,
                warning_count=1,
            )
            index.update_run_status("run_abc", "completed")

            data = index.read()

        self.assertEqual(data["version"], 1)
        self.assertEqual(data["latest_run_id"], "run_abc")
        self.assertEqual(len(data["runs"]), 1)
        run = data["runs"][0]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(run["task_notes"]), 1)
        self.assertEqual(run["task_notes"][0]["source_count"], 5)
        self.assertEqual(run["task_notes"][0]["summary_chars"], 2200)
        self.assertEqual(run["report_note"]["evaluator_score"], 100)

    def test_latest_run_points_to_most_recent_started_run(self):
        with TemporaryDirectory() as tmp:
            index = NotesIndex(Path(tmp) / "index.json")
            index.start_run("run_abc", "第一轮研究")
            index.start_run("run_xyz", "第二轮研究")

            data = index.read()

        self.assertEqual(data["latest_run_id"], "run_xyz")
        self.assertEqual(
            [run["run_id"] for run in data["runs"]],
            ["run_abc", "run_xyz"],
        )

    def test_concurrent_task_updates_do_not_lose_notes(self):
        with TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index.json"
            index = NotesIndex(index_path)
            index.start_run("run_concurrent", "并发研究")

            def add_task(task_id: int) -> None:
                # 模拟多个任务 worker 通过不同 NotesIndex 实例并发写同一文件。
                worker_index = NotesIndex(index_path)
                worker_index.upsert_task_note(
                    run_id="run_concurrent",
                    note_id=f"note_{task_id}",
                    task_id=task_id,
                    title=f"任务 {task_id}",
                    note_path=f"note_{task_id}.md",
                    status="completed",
                    source_count=5,
                    summary_chars=1000 + task_id,
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(add_task, range(1, 21)))

            data = index.read()

        task_notes = data["runs"][0]["task_notes"]
        self.assertEqual(len(task_notes), 20)
        self.assertEqual(
            {item["note_id"] for item in task_notes},
            {f"note_{task_id}" for task_id in range(1, 21)},
        )


if __name__ == "__main__":
    unittest.main()
