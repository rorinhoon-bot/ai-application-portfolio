"""D-6 40 例固定离线评估的可重复运行验证。"""
import os, subprocess, sys, unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

class D6EvaluationTests(unittest.TestCase):
    def test_frozen_forty_case_evaluation_passes(self):
        done = subprocess.run(
            [sys.executable, "evals/run_d6_eval.py"], cwd=_ROOT,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 0)
        self.assertIn("D6 EVAL: scenarios: 40 passed: 40 failed: 0", done.stdout)

if __name__ == "__main__":
    unittest.main()
