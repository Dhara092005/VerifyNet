import unittest

from verifynet.domain import GOOD_CISCO_TEMPLATE, GOOD_JUNIPER_TEMPLATE, VendorIntent, check_vendor_template


class VendorTests(unittest.TestCase):
    def test_cisco_ios_template_passes(self):
        intent = VendorIntent("cisco_ios", "GigabitEthernet0/1", "10.10.0.1/30", "192.168.20.0/24", "10.10.0.2")
        self.assertTrue(check_vendor_template(GOOD_CISCO_TEMPLATE, intent)["passed"])

    def test_juniper_template_passes(self):
        intent = VendorIntent("juniper_junos", "ge-0/0/1", "10.10.0.1/30", "192.168.20.0/24", "10.10.0.2")
        self.assertTrue(check_vendor_template(GOOD_JUNIPER_TEMPLATE, intent)["passed"])

    def test_vendor_rejects_unknown_vendor(self):
        with self.assertRaises(ValueError):
            VendorIntent.from_dict({"vendor":"arista_eos", "interface":"Ethernet1", "interface_cidr":"10.10.0.1/30", "destination_cidr":"192.168.20.0/24", "next_hop":"10.10.0.2"})


if __name__ == "__main__":
    unittest.main()
