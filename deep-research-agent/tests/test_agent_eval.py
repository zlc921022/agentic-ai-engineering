import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from benchmarks.agent_eval import load_cases, run_case, run_suite


class AgentEvalTest(unittest.TestCase):
    def test_fixed_agent_cases_all_pass_offline(self):
        cases = load_cases(ROOT_DIR / "benchmarks" / "agent_cases.json")

        results = [run_case(case) for case in cases]

        self.assertEqual(len(cases), 8)
        self.assertTrue(all(result["passed"] for result in results))

    def test_suite_writes_machine_readable_report(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "agent_eval.json"
            report = run_suite(
                cases_file=ROOT_DIR / "benchmarks" / "agent_cases.json",
                output_file=output,
            )

            self.assertTrue(output.exists())
            self.assertEqual(report["summary"]["case_pass_rate"], 1.0)
            self.assertEqual(report["summary"]["behavior_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
