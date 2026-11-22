import unittest

from verifynet.domain import BROKEN_IPV6_TEMPLATE, GOOD_IPV6_TEMPLATE, IPv6Intent, check_ipv6_template
from verifynet.pipeline import run_pipeline


class IPv6Tests(unittest.TestCase):
    def test_ipv6_reference_passes(self):
        self.assertTrue(check_ipv6_template(GOOD_IPV6_TEMPLATE, IPv6Intent())["passed"])

    def test_ipv6_gateway_error_is_rejected(self):
        result = check_ipv6_template(BROKEN_IPV6_TEMPLATE, IPv6Intent())
        self.assertFalse(result["passed"])

    def test_demo_pipeline_repairs_ipv6(self):
        result = run_pipeline({"task_profile": "ipv6_static", "intent": IPv6Intent().data(), "mode": "demo", "strategy": "rag_repair", "max_repairs": 2})
        self.assertTrue(result["final_pass"])
        self.assertEqual(result["task_profile"], "ipv6_static")


if __name__ == "__main__":
    unittest.main()
