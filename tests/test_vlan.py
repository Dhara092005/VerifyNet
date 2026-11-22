import unittest

from verifynet.domain import BROKEN_VLAN_TEMPLATE, GOOD_VLAN_TEMPLATE, VlanIntent, check_vlan_template
from verifynet.pipeline import run_pipeline


class VlanTests(unittest.TestCase):
    def test_vlan_reference_passes(self):
        self.assertTrue(check_vlan_template(GOOD_VLAN_TEMPLATE, VlanIntent())["passed"])

    def test_vlan_gateway_error_is_rejected(self):
        self.assertFalse(check_vlan_template(BROKEN_VLAN_TEMPLATE, VlanIntent())["passed"])

    def test_demo_pipeline_repairs_vlan(self):
        result = run_pipeline({"task_profile": "vlan_static", "intent": VlanIntent().data(), "mode": "demo", "strategy": "rag_repair", "max_repairs": 2})
        self.assertTrue(result["final_pass"])
        self.assertEqual(result["task_profile"], "vlan_static")


if __name__ == "__main__":
    unittest.main()
