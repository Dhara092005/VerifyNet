import unittest
from verifynet.reports import html_report


class ReportTests(unittest.TestCase):
    def test_html_report_contains_escaped_evidence(self):
        html = html_report({"task_profile": "cisco_ios", "intent": {"interface": "Gi0/1"}, "attempts": [{"number": 1, "template": "<unsafe>", "validation": {"passed": False}}]})
        self.assertIn("VerifyNet evidence report", html)
        self.assertIn("&lt;unsafe&gt;", html)
        self.assertNotIn("<unsafe>", html)


if __name__ == "__main__":
    unittest.main()
