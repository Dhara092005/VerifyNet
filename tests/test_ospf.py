import unittest

from verifynet.domain import BROKEN_OSPF_TEMPLATE, GOOD_OSPF_TEMPLATE, OspfIntent, check_ospf_template
from verifynet.pipeline import run_pipeline


class OspfTests(unittest.TestCase):
    def test_ospf_reference_passes(self):
        self.assertTrue(check_ospf_template(GOOD_OSPF_TEMPLATE, OspfIntent())["passed"])

    def test_ospf_area_error_is_rejected(self):
        self.assertFalse(check_ospf_template(BROKEN_OSPF_TEMPLATE, OspfIntent())["passed"])

    def test_demo_pipeline_repairs_ospf(self):
        result = run_pipeline({"task_profile": "ospf", "intent": OspfIntent().data(), "mode": "demo", "strategy": "rag_repair", "max_repairs": 2})
        self.assertTrue(result["final_pass"])


if __name__ == "__main__":
    unittest.main()
