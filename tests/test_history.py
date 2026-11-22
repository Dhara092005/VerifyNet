import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verifynet.domain import Intent
from verifynet.history import list_runs, record


class HistoryTests(unittest.TestCase):
    def test_history_stores_summary_without_template(self):
        report = {"mode": "demo", "strategy": "rag_repair", "first_pass": False, "final_pass": True,
                  "repairs": 1, "attempts": [{}, {}], "documents": [{"id": "frr-static"}],
                  "device_tested": False, "duration_seconds": 0.42, "intent": Intent().data(),
                  "created_at": "2026-11-19T10:00:00+00:00", "notice": "demo", "requirement": "route",
                  "attempt_template_secret": "must not be stored"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            with patch("verifynet.history.HISTORY_PATH", path):
                entry = record(report)
                self.assertEqual(list_runs()[0]["id"], entry["id"])
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("template", raw)
            self.assertNotIn("must not be stored", raw)

    def test_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.json"
            with patch("verifynet.history.HISTORY_PATH", path), patch("verifynet.history.MAX_RUNS", 2):
                for i in range(4):
                    record({"mode": "demo", "strategy": "llm_only", "first_pass": True, "final_pass": True,
                            "repairs": 0, "attempts": [{}], "documents": [], "device_tested": False,
                            "duration_seconds": i, "intent": Intent().data(), "created_at": str(i)})
                self.assertEqual(len(list_runs(2)), 2)


if __name__ == "__main__":
    unittest.main()
