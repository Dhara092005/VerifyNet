import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verifynet.feedback import add_feedback, feedback_summary


class FeedbackTests(unittest.TestCase):
    def test_feedback_is_stored_and_summarized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "feedback.json"
            with patch("verifynet.feedback.FEEDBACK_PATH", path):
                entry = add_feedback({"run_id": "run-123", "verdict": "partially_correct", "note": "Needs a VLAN check."})
                self.assertEqual(entry["verdict"], "partially_correct")
                self.assertEqual(feedback_summary()["partially_correct"], 1)

    def test_feedback_rejects_unknown_verdict_and_bad_run_id(self):
        with self.assertRaises(ValueError):
            add_feedback({"run_id": "run-123", "verdict": "maybe"})
        with self.assertRaises(ValueError):
            add_feedback({"run_id": "run/123", "verdict": "correct"})


if __name__ == "__main__":
    unittest.main()
