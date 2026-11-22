import unittest

from verifynet.domain import GOOD_MULTI_TEMPLATE, MultiIntent, check_multi_template
from verifynet.pipeline import run_pipeline


MULTI = {"interfaces": [{"name": "eth1", "cidr": "10.10.0.1/30"}, {"name": "eth2", "cidr": "10.20.0.1/30"}],
         "routes": [{"destination": "192.168.20.0/24", "next_hop": "10.10.0.2"}, {"destination": "192.168.30.0/24", "next_hop": "10.20.0.2"}]}


class MultiIntentTests(unittest.TestCase):
    def test_multiple_interfaces_and_routes_pass_three_cases(self):
        result = check_multi_template(GOOD_MULTI_TEMPLATE, MultiIntent.from_dict(MULTI))
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["rendered"]), 3)
        self.assertEqual(len(result["states"][0]["interfaces"]), 2)
        self.assertEqual(len(result["states"][0]["routes"]), 2)

    def test_missing_second_route_fails_intent(self):
        result = check_multi_template(GOOD_MULTI_TEMPLATE.replace("ip route {{ route_2_destination }} {{ route_2_next_hop }}", ""), MultiIntent.from_dict(MULTI))
        self.assertFalse(result["passed"])
        self.assertTrue(any("route mismatch" in error for error in result["errors"]))

    def test_scripted_advanced_pipeline_repairs_candidate(self):
        result = run_pipeline({"task_profile": "multi_route", "intent": MULTI, "mode": "demo", "strategy": "rag_repair", "max_repairs": 2})
        self.assertFalse(result["first_pass"])
        self.assertTrue(result["final_pass"])
        self.assertEqual(result["task_profile"], "multi_route")


if __name__ == "__main__":
    unittest.main()
