import unittest
from unittest.mock import patch

from verifynet.domain import GOOD_TEMPLATE, Intent
from verifynet.router_lab import lab_intent, readiness, run_lab


class RouterLabTests(unittest.TestCase):
    def test_lab_accepts_private_example_and_selects_peer_loopback(self):
        intent, interface, destination, target = lab_intent(Intent().data())
        self.assertEqual(str(interface.ip), "10.10.0.1")
        self.assertEqual(str(destination), "192.168.20.0/24")
        self.assertEqual(target, "192.168.20.1")

    def test_lab_rejects_public_addresses_before_docker(self):
        data = Intent().data()
        data["destination_cidr"] = "203.0.113.0/24"
        with self.assertRaises(ValueError):
            lab_intent(data)

    def test_missing_docker_is_explicit_and_does_not_claim_device_test(self):
        with patch("verifynet.router_lab.shutil.which", return_value=None):
            result = run_lab({"intent": Intent().data(), "template": GOOD_TEMPLATE})
        self.assertFalse(result["passed"])
        self.assertFalse(result["device_tested"])
        self.assertEqual(result["verification_level"], "not_run")
        self.assertIn("Docker is not installed", result["error"])


if __name__ == "__main__":
    unittest.main()
