import unittest
from unittest.mock import patch

from verifynet.benchmark import live_ablation


class LiveBenchmarkTests(unittest.TestCase):
    def test_live_ablation_compares_three_strategies_without_real_api(self):
        def fake_run(payload):
            passed = payload["strategy"] != "llm_only"
            return {"strategy": payload["strategy"], "first_pass": passed, "final_pass": passed,
                    "repairs": 0 if passed else 1, "duration_seconds": 0.25,
                    "attempts": [{"usage": {"total_tokens": 12}}], "documents": [],
                    "mode": "live", "device_tested": False}
        with patch("verifynet.benchmark.run_pipeline", side_effect=fake_run) as mocked:
            report = live_ablation(limit=1)
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(set(report["metrics"]), {"llm_only", "rag", "rag_repair"})
        self.assertEqual(report["metrics"]["llm_only"]["final_pass_rate"], 0)
        self.assertEqual(report["metrics"]["rag"]["final_pass_rate"], 1)

    def test_live_ablation_has_a_small_bound(self):
        with self.assertRaises(ValueError):
            live_ablation(limit=6)


if __name__ == "__main__":
    unittest.main()
