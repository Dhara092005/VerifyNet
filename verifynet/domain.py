"""The explicit intent contract and independent, bounded template checker."""
from dataclasses import asdict, dataclass
import ipaddress
import re

from jinja2 import StrictUndefined, TemplateError, nodes
from jinja2.sandbox import SandboxedEnvironment


VARIABLES = {"interface", "interface_cidr", "destination_cidr", "next_hop"}
MULTI_VARIABLES = {"interface_1", "interface_1_cidr", "interface_2", "interface_2_cidr",
                   "route_1_destination", "route_1_next_hop", "route_2_destination", "route_2_next_hop"}
IPV6_VARIABLES = {"interface", "interface_cidr", "destination_cidr", "next_hop"}
VLAN_VARIABLES = {"interface", "vlan_id", "interface_cidr", "destination_cidr", "next_hop"}
OSPF_VARIABLES = {"router_id", "area", "network_cidr"}
VENDOR_VARIABLES = {"interface", "interface_cidr", "interface_ip", "interface_mask", "destination_cidr", "next_hop"}
ENV = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
ENV.globals.clear()
ENV.filters.clear()
ENV.tests.clear()
GOOD_TEMPLATE = """interface {{ interface }}
 ip address {{ interface_cidr }}
exit
ip route {{ destination_cidr }} {{ next_hop }}"""
BROKEN_TEMPLATE = GOOD_TEMPLATE.replace("{{ next_hop }}", "{{ interface_cidr }}")
GOOD_MULTI_TEMPLATE = """interface {{ interface_1 }}
 ip address {{ interface_1_cidr }}
exit
interface {{ interface_2 }}
 ip address {{ interface_2_cidr }}
exit
ip route {{ route_1_destination }} {{ route_1_next_hop }}
ip route {{ route_2_destination }} {{ route_2_next_hop }}"""
GOOD_IPV6_TEMPLATE = """interface {{ interface }}
 ipv6 address {{ interface_cidr }}
exit
ipv6 route {{ destination_cidr }} {{ next_hop }}"""
BROKEN_IPV6_TEMPLATE = GOOD_IPV6_TEMPLATE.replace("{{ next_hop }}", "{{ interface_cidr }}")
GOOD_VLAN_TEMPLATE = """interface {{ interface }}
 encapsulation dot1q {{ vlan_id }}
 ip address {{ interface_cidr }}
exit
ip route {{ destination_cidr }} {{ next_hop }}"""
BROKEN_VLAN_TEMPLATE = GOOD_VLAN_TEMPLATE.replace("{{ next_hop }}", "{{ interface_cidr }}")
GOOD_OSPF_TEMPLATE = """router ospf
 router-id {{ router_id }}
 network {{ network_cidr }} area {{ area }}
exit"""
BROKEN_OSPF_TEMPLATE = GOOD_OSPF_TEMPLATE.replace("{{ area }}", "{{ router_id }}")
GOOD_CISCO_TEMPLATE = """interface {{ interface }}
 ip address {{ interface_ip }} {{ interface_mask }}
 no shutdown
exit
ip route {{ destination_cidr }} {{ next_hop }}"""
GOOD_JUNIPER_TEMPLATE = """set interfaces {{ interface }} unit 0 family inet address {{ interface_cidr }}
set routing-options static route {{ destination_cidr }} next-hop {{ next_hop }}"""


@dataclass(frozen=True)
class Intent:
    interface: str = "eth1"
    interface_cidr: str = "10.10.0.1/30"
    destination_cidr: str = "192.168.20.0/24"
    next_hop: str = "10.10.0.2"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != VARIABLES:
            raise ValueError("Provide interface, interface_cidr, destination_cidr, and next_hop.")
        if not all(isinstance(v, str) and len(v) <= 64 for v in value.values()):
            raise ValueError("All network parameters must be short text values.")
        intent = cls(**{k: v.strip() for k, v in value.items()})
        intent.validate()
        return intent

    def validate(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", self.interface):
            raise ValueError("Use an interface name of 1–15 letters, digits, dots, hyphens, or underscores.")
        try:
            iface = ipaddress.IPv4Interface(self.interface_cidr)
            dest = ipaddress.IPv4Network(self.destination_cidr, strict=True)
            hop = ipaddress.IPv4Address(self.next_hop)
        except ValueError as exc:
            raise ValueError("Use valid IPv4 addresses and a destination prefix with no host bits.") from exc
        # This prototype models a normal, single directly connected next hop.
        if iface.network.prefixlen > 30:
            raise ValueError("This prototype supports interface prefixes /0 through /30.")
        if iface.ip in (iface.network.network_address, iface.network.broadcast_address):
            raise ValueError("The interface must use a host address, not a network or broadcast address.")
        if hop not in iface.network or hop in (iface.ip, iface.network.network_address, iface.network.broadcast_address):
            raise ValueError("The next hop must be a different usable host on the interface subnet.")
        if dest.overlaps(iface.network):
            raise ValueError("Use a remote destination that does not overlap the directly connected subnet.")

    def data(self):
        return asdict(self)


@dataclass(frozen=True)
class VendorIntent:
    vendor: str = "cisco_ios"
    interface: str = "GigabitEthernet0/1"
    interface_cidr: str = "10.10.0.1/30"
    destination_cidr: str = "192.168.20.0/24"
    next_hop: str = "10.10.0.2"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"vendor", "interface", "interface_cidr", "destination_cidr", "next_hop"}:
            raise ValueError("Provide vendor, interface, interface_cidr, destination_cidr, and next_hop.")
        item = cls(**{k: str(v).strip() for k, v in value.items()})
        item.validate(); return item

    def validate(self):
        if self.vendor not in {"cisco_ios", "juniper_junos"}:
            raise ValueError("Vendor must be cisco_ios or juniper_junos.")
        if not self.interface or len(self.interface) > 64:
            raise ValueError("Provide a valid vendor interface name.")
        base = Intent("eth1", self.interface_cidr, self.destination_cidr, self.next_hop)
        base.validate()

    def data(self):
        value = asdict(self)
        iface = ipaddress.IPv4Interface(self.interface_cidr)
        value.update(interface_ip=str(iface.ip), interface_mask=str(iface.network.netmask))
        return value


@dataclass(frozen=True)
class IPv6Intent:
    interface: str = "eth1"
    interface_cidr: str = "2001:db8:10::1/64"
    destination_cidr: str = "2001:db8:20::/64"
    next_hop: str = "2001:db8:10::2"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != IPV6_VARIABLES:
            raise ValueError("Provide interface, interface_cidr, destination_cidr, and next_hop.")
        if not all(isinstance(v, str) and len(v) <= 80 for v in value.values()):
            raise ValueError("All IPv6 parameters must be short text values.")
        intent = cls(**{k: v.strip() for k, v in value.items()})
        intent.validate()
        return intent

    def validate(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", self.interface):
            raise ValueError("Use a valid interface name.")
        try:
            iface = ipaddress.IPv6Interface(self.interface_cidr)
            dest = ipaddress.IPv6Network(self.destination_cidr, strict=True)
            hop = ipaddress.IPv6Address(self.next_hop)
        except ValueError as exc:
            raise ValueError("Use valid IPv6 addresses and a destination prefix with no host bits.") from exc
        if iface.network.prefixlen > 127 or iface.ip.is_unspecified or iface.ip.is_multicast:
            raise ValueError("Use a unicast IPv6 interface address with a prefix from /0 through /127.")
        if hop not in iface.network or hop in (iface.ip, iface.network.network_address) or hop.is_multicast:
            raise ValueError("The next hop must be a different usable unicast host on the interface subnet.")
        if dest.overlaps(iface.network):
            raise ValueError("Use a remote destination that does not overlap the directly connected subnet.")

    def data(self):
        return asdict(self)


@dataclass(frozen=True)
class VlanIntent:
    interface: str = "eth1"
    vlan_id: str = "100"
    interface_cidr: str = "10.100.0.1/30"
    destination_cidr: str = "192.168.100.0/24"
    next_hop: str = "10.100.0.2"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != VLAN_VARIABLES:
            raise ValueError("Provide interface, vlan_id, interface_cidr, destination_cidr, and next_hop.")
        if not all(isinstance(v, str) and len(v) <= 80 for v in value.values()):
            raise ValueError("All VLAN parameters must be short text values.")
        intent = cls(**{k: v.strip() for k, v in value.items()}); intent.validate(); return intent

    def validate(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", self.interface):
            raise ValueError("Use a valid interface name.")
        if not self.vlan_id.isdigit() or not 1 <= int(self.vlan_id) <= 4094:
            raise ValueError("VLAN ID must be an integer from 1 through 4094.")
        try:
            iface = ipaddress.IPv4Interface(self.interface_cidr); dest = ipaddress.IPv4Network(self.destination_cidr, strict=True); hop = ipaddress.IPv4Address(self.next_hop)
        except ValueError as exc:
            raise ValueError("Use valid IPv4 addresses and a destination prefix with no host bits.") from exc
        if iface.network.prefixlen > 30 or iface.ip in (iface.network.network_address, iface.network.broadcast_address):
            raise ValueError("Use a usable IPv4 interface host with a prefix from /0 through /30.")
        if hop not in iface.network or hop in (iface.ip, iface.network.network_address, iface.network.broadcast_address):
            raise ValueError("The next hop must be a different usable host on the VLAN subnet.")
        if dest.overlaps(iface.network): raise ValueError("Use a remote destination outside the VLAN subnet.")

    def data(self): return asdict(self)


@dataclass(frozen=True)
class OspfIntent:
    router_id: str = "1.1.1.1"
    area: str = "0.0.0.0"
    network_cidr: str = "10.0.0.0/30"

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != OSPF_VARIABLES: raise ValueError("Provide router_id, area, and network_cidr.")
        if not all(isinstance(v, str) and len(v) <= 64 for v in value.values()): raise ValueError("OSPF parameters must be short text values.")
        intent=cls(**{k:v.strip() for k,v in value.items()}); intent.validate(); return intent
    def validate(self):
        try: rid=ipaddress.IPv4Address(self.router_id); area=ipaddress.IPv4Address(self.area); network=ipaddress.IPv4Network(self.network_cidr, strict=True)
        except ValueError as exc: raise ValueError("Use valid IPv4 router ID, area, and network prefix values.") from exc
        if rid.is_unspecified or area.is_multicast or network.prefixlen > 30: raise ValueError("Use a unicast router ID, valid area, and network prefix /0 through /30.")
    def data(self): return asdict(self)


@dataclass(frozen=True)
class MultiIntent:
    interfaces: tuple
    routes: tuple

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"interfaces", "routes"}:
            raise ValueError("Provide interfaces and routes for the advanced task.")
        interfaces, routes = value["interfaces"], value["routes"]
        if not isinstance(interfaces, list) or not 1 <= len(interfaces) <= 2 or not isinstance(routes, list) or not 1 <= len(routes) <= 2:
            raise ValueError("The advanced task supports one or two interfaces and routes.")
        parsed_interfaces = []
        names = set()
        networks = []
        for item in interfaces:
            if not isinstance(item, dict) or set(item) != {"name", "cidr"}:
                raise ValueError("Each interface needs name and cidr.")
            name = item["name"].strip() if isinstance(item["name"], str) else ""
            try:
                cidr = ipaddress.IPv4Interface(item["cidr"].strip())
            except (AttributeError, ValueError) as exc:
                raise ValueError("Each interface needs a valid IPv4 CIDR.") from exc
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", name) or name in names:
                raise ValueError("Interface names must be unique and 1–15 characters.")
            if cidr.network.prefixlen > 30 or cidr.ip in (cidr.network.network_address, cidr.network.broadcast_address):
                raise ValueError("Interfaces must use usable IPv4 host addresses with prefixes /0 through /30.")
            if any(cidr.network.overlaps(network) for network in networks):
                raise ValueError("Interface subnets must not overlap.")
            names.add(name); networks.append(cidr.network); parsed_interfaces.append({"name": name, "cidr": str(cidr)})
        parsed_routes = []
        for item in routes:
            if not isinstance(item, dict) or set(item) != {"destination", "next_hop"}:
                raise ValueError("Each route needs destination and next_hop.")
            try:
                destination = ipaddress.IPv4Network(item["destination"].strip(), strict=True)
                next_hop = ipaddress.IPv4Address(item["next_hop"].strip())
            except (AttributeError, ValueError) as exc:
                raise ValueError("Each route needs a destination prefix and IPv4 next hop.") from exc
            if any(destination.overlaps(network) for network in networks):
                raise ValueError("Remote destinations must not overlap interface subnets.")
            if not any(next_hop in network and next_hop not in (network.network_address, network.broadcast_address) for network in networks):
                raise ValueError("Every next hop must be a usable host on one interface subnet.")
            if any(destination == prior["destination"] for prior in parsed_routes):
                raise ValueError("Route destinations must be unique.")
            parsed_routes.append({"destination": str(destination), "next_hop": str(next_hop)})
        return cls(tuple(parsed_interfaces), tuple(parsed_routes))

    def data(self):
        return {"interfaces": list(self.interfaces), "routes": list(self.routes)}

    def context(self):
        values = {}
        for index, interface in enumerate(self.interfaces, 1):
            values[f"interface_{index}"] = interface["name"]
            values[f"interface_{index}_cidr"] = interface["cidr"]
        for index, route in enumerate(self.routes, 1):
            values[f"route_{index}_destination"] = route["destination"]
            values[f"route_{index}_next_hop"] = route["next_hop"]
        return values


def multi_parameter_cases(intent):
    cases = [intent]
    if len(intent.interfaces) == 2 and len(intent.routes) == 2:
        cases.append(MultiIntent.from_dict({"interfaces": [{"name": "uplink0", "cidr": "172.18.4.1/29"}, {"name": "uplink1", "cidr": "172.18.5.1/29"}], "routes": [{"destination": "10.200.0.0/16", "next_hop": "172.18.4.6"}, {"destination": "10.201.0.0/16", "next_hop": "172.18.5.6"}]}))
        cases.append(MultiIntent.from_dict({"interfaces": [{"name": "eth7", "cidr": "192.0.2.9/29"}, {"name": "eth8", "cidr": "198.51.100.9/29"}], "routes": [{"destination": "203.0.113.0/24", "next_hop": "192.0.2.10"}, {"destination": "100.64.0.0/10", "next_hop": "198.51.100.10"}]}))
    return cases


def parameter_cases(intent):
    """Cross-input checks catch hardcoded values that only pass the displayed example."""
    return [intent, Intent("uplink0", "172.18.4.1/29", "10.200.0.0/16", "172.18.4.6"),
            Intent("eth7", "192.0.2.9/30", "198.51.100.0/24", "192.0.2.10")]


def compile_template(source, variables=VARIABLES):
    if not isinstance(source, str) or not source.strip() or len(source) > 8000:
        raise ValueError("Provide a nonempty template of at most 8,000 characters.")
    ast = ENV.parse(source)
    allowed = (nodes.Template, nodes.Output, nodes.TemplateData, nodes.Name)
    if any(not isinstance(node, allowed) for node in ast.find_all(nodes.Node)):
        raise ValueError("Only plain text and {{ variable }} placeholders are supported; no loops, calls, or expressions.")
    names = {n.name for n in ast.find_all(nodes.Name)}
    if names - variables:
        raise ValueError("Unknown template variable(s): " + ", ".join(sorted(names - variables)))
    return ENV.from_string(source)


def parse_config(config):
    """Parse only the documented subset. Never execute model output or shell commands."""
    interfaces, routes = {}, []
    current = None
    for number, raw in enumerate(config.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        words = line.split()
        if len(words) == 2 and words[0] == "interface":
            if current is not None or words[1] in interfaces:
                raise ValueError(f"Line {number}: nested or duplicate interface block.")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", words[1]):
                raise ValueError(f"Line {number}: invalid interface name.")
            current = words[1]
            interfaces[current] = None
        elif len(words) == 3 and words[:2] == ["ip", "address"] and current is not None:
            if interfaces[current] is not None:
                raise ValueError(f"Line {number}: multiple interface addresses are outside this prototype's scope.")
            interfaces[current] = str(ipaddress.IPv4Interface(words[2]))
        elif line == "exit" and current is not None:
            current = None
        elif len(words) == 4 and words[:2] == ["ip", "route"] and current is None:
            try:
                routes.append((str(ipaddress.IPv4Network(words[2], strict=True)), str(ipaddress.IPv4Address(words[3]))))
            except ValueError as exc:
                raise ValueError(f"Line {number}: route requires a destination prefix and a next-hop IPv4 address (without /prefix).") from exc
        else:
            raise ValueError(f"Line {number}: command is unsupported or in the wrong context: {line[:100]}")
    if current is not None:
        raise ValueError("Close the interface block with 'exit'.")
    if any(address is None for address in interfaces.values()):
        raise ValueError("Each interface block must contain an IP address.")
    return {"interfaces": interfaces, "routes": routes}


def parse_ipv6_config(config):
    interfaces, routes = {}, []
    current = None
    for number, raw in enumerate(config.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        words = line.split()
        if len(words) == 2 and words[0] == "interface":
            if current is not None or words[1] in interfaces:
                raise ValueError(f"Line {number}: nested or duplicate interface block.")
            current = words[1]; interfaces[current] = None
        elif len(words) == 3 and words[:2] == ["ipv6", "address"] and current is not None:
            if interfaces[current] is not None:
                raise ValueError(f"Line {number}: multiple interface addresses are outside this prototype's scope.")
            try: interfaces[current] = str(ipaddress.IPv6Interface(words[2]))
            except ValueError as exc: raise ValueError(f"Line {number}: invalid IPv6 interface address.") from exc
        elif line == "exit" and current is not None:
            current = None
        elif len(words) == 4 and words[:2] == ["ipv6", "route"] and current is None:
            try: routes.append((str(ipaddress.IPv6Network(words[2], strict=True)), str(ipaddress.IPv6Address(words[3]))))
            except ValueError as exc: raise ValueError(f"Line {number}: route requires an IPv6 destination and next hop.") from exc
        else:
            raise ValueError(f"Line {number}: command is unsupported or in the wrong context: {line[:100]}")
    if current is not None:
        raise ValueError("Close the interface block with 'exit'.")
    if any(address is None for address in interfaces.values()):
        raise ValueError("Each interface block must contain an IPv6 address.")
    return {"interfaces": interfaces, "routes": routes}


def parse_vlan_config(config):
    interfaces, routes = {}, []; current = None
    for number, raw in enumerate(config.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("!"): continue
        words = line.split()
        if len(words) == 2 and words[0] == "interface":
            if current is not None or words[1] in interfaces: raise ValueError(f"Line {number}: nested or duplicate interface block.")
            current = words[1]; interfaces[current] = {"vlan_id": None, "address": None}
        elif len(words) == 3 and words[:2] == ["encapsulation", "dot1q"] and current is not None:
            if interfaces[current]["vlan_id"] is not None or not words[2].isdigit() or not 1 <= int(words[2]) <= 4094: raise ValueError(f"Line {number}: invalid VLAN ID.")
            interfaces[current]["vlan_id"] = words[2]
        elif len(words) == 3 and words[:2] == ["ip", "address"] and current is not None:
            if interfaces[current]["address"] is not None: raise ValueError(f"Line {number}: multiple interface addresses are outside this prototype's scope.")
            try: interfaces[current]["address"] = str(ipaddress.IPv4Interface(words[2]))
            except ValueError as exc: raise ValueError(f"Line {number}: invalid IPv4 interface address.") from exc
        elif line == "exit" and current is not None: current = None
        elif len(words) == 4 and words[:2] == ["ip", "route"] and current is None:
            try: routes.append((str(ipaddress.IPv4Network(words[2], strict=True)), str(ipaddress.IPv4Address(words[3]))))
            except ValueError as exc: raise ValueError(f"Line {number}: invalid static route.") from exc
        else: raise ValueError(f"Line {number}: command is unsupported or in the wrong context: {line[:100]}")
    if current is not None: raise ValueError("Close the interface block with 'exit'.")
    if any(item["vlan_id"] is None or item["address"] is None for item in interfaces.values()): raise ValueError("Each VLAN interface needs encapsulation and an IP address.")
    return {"interfaces": interfaces, "routes": routes}


def intent_errors(state, intent):
    expected_interfaces = {intent.interface: str(ipaddress.IPv4Interface(intent.interface_cidr))}
    expected_routes = [(str(ipaddress.IPv4Network(intent.destination_cidr)), str(ipaddress.IPv4Address(intent.next_hop)))]
    errors = []
    if state["interfaces"] != expected_interfaces:
        errors.append(f"Interface/address mismatch. Expected {expected_interfaces}, received {state['interfaces']}.")
    if state["routes"] != expected_routes:
        errors.append(f"Route mismatch. Expected {expected_routes}, received {state['routes']}.")
    return errors


def check_template(source, intent):
    intent.validate()
    stages, rendered, states, cases = [], [], [], parameter_cases(intent)

    def stage(name, errors, detail):
        stages.append({"name": name, "passed": not errors, "errors": errors, "detail": detail})
        return not errors

    try:
        compiled = compile_template(source)
        stage("Template syntax", [], "Restricted Jinja2 syntax; unknown variables and expressions are rejected.")
    except (TemplateError, ValueError) as exc:
        stage("Template syntax", [str(exc)], "Template could not be compiled.")
        return finish(stages, rendered, states, cases)
    errors = []
    for i, case in enumerate(cases):
        try:
            rendered.append(compiled.render(**case.data()))
        except TemplateError as exc:
            errors.append(f"Case {i + 1}: {exc}")
    if not stage("Parameter rendering", errors, "Rendered against three different parameter sets."):
        return finish(stages, rendered, states, cases)
    errors = []
    for i, config in enumerate(rendered):
        try:
            states.append(parse_config(config))
        except ValueError as exc:
            errors.append(f"Case {i + 1}: {exc}")
    if not stage("Command structure", errors, "Local parser for a small FRRouting command subset; not the FRR compiler."):
        return finish(stages, rendered, states, cases)
    errors = []
    for i, (state, case) in enumerate(zip(states, cases)):
        errors.extend(f"Case {i + 1}: {e}" for e in intent_errors(state, case))
    if not stage("Intent agreement", errors, "Checks exact interface and route intent, including absence of extra configuration."):
        return finish(stages, rendered, states, cases)
    errors = []
    for i, state in enumerate(states):
        for _, hop in state["routes"]:
            hop_ip = ipaddress.IPv4Address(hop)
            if not any(hop_ip in ipaddress.IPv4Interface(address).network and hop_ip != ipaddress.IPv4Interface(address).ip
                       for address in state["interfaces"].values()):
                errors.append(f"Case {i + 1}: next hop has no directly connected path in the local model.")
    stage("Local route model", errors, "Checks next-hop subnet reachability only. No packets, return paths, device state, or live router are tested.")
    return finish(stages, rendered, states, cases)


def check_ipv6_template(source, intent):
    intent.validate(); stages, rendered, states = [], [], []
    cases = [intent, IPv6Intent("uplink0", "2001:db8:40::1/64", "2001:db8:50::/64", "2001:db8:40::2"),
             IPv6Intent("eth7", "2001:db8:60::9/126", "2001:db8:70::/64", "2001:db8:60::a")]
    def stage(name, errors, detail):
        stages.append({"name": name, "passed": not errors, "errors": errors, "detail": detail}); return not errors
    try:
        compiled = compile_template(source, IPV6_VARIABLES); stage("Template syntax", [], "Restricted IPv6 placeholders; unknown variables are rejected.")
    except (TemplateError, ValueError) as exc:
        stage("Template syntax", [str(exc)], "Template could not be compiled."); return finish(stages, rendered, states, cases)
    errors = []
    for i, case in enumerate(cases):
        try: rendered.append(compiled.render(**case.data()))
        except TemplateError as exc: errors.append(f"Case {i + 1}: {exc}")
    if not stage("Parameter rendering", errors, "Rendered against three different IPv6 parameter sets."): return finish(stages, rendered, states, cases)
    errors = []
    for i, config in enumerate(rendered):
        try: states.append(parse_ipv6_config(config))
        except ValueError as exc: errors.append(f"Case {i + 1}: {exc}")
    if not stage("Command structure", errors, "Parser checks IPv6 interface and route commands."): return finish(stages, rendered, states, cases)
    for i, (state, case) in enumerate(zip(states, cases), 1):
        expected_i = {case.interface: str(ipaddress.IPv6Interface(case.interface_cidr))}
        expected_r = [(str(ipaddress.IPv6Network(case.destination_cidr)), str(ipaddress.IPv6Address(case.next_hop)))]
        if state["interfaces"] != expected_i: errors.append(f"Case {i}: Interface/address mismatch.")
        if state["routes"] != expected_r: errors.append(f"Case {i}: Route mismatch.")
    stage("Intent agreement", errors, "Checks the IPv6 interface and static route exactly.")
    stage("Local route model", [], "Checks that the IPv6 next hop belongs to the configured interface subnet.")
    return finish(stages, rendered, states, cases)


def check_vlan_template(source, intent):
    intent.validate(); stages, rendered, states = [], [], []
    cases = [intent, VlanIntent("uplink0", "200", "172.18.40.1/29", "10.240.0.0/16", "172.18.40.6"), VlanIntent("eth7", "409", "192.0.2.9/30", "198.51.100.0/24", "192.0.2.10")]
    def stage(name, errors, detail): stages.append({"name": name, "passed": not errors, "errors": errors, "detail": detail}); return not errors
    try: compiled = compile_template(source, VLAN_VARIABLES); stage("Template syntax", [], "Restricted VLAN placeholders; unknown variables are rejected.")
    except (TemplateError, ValueError) as exc: stage("Template syntax", [str(exc)], "Template could not be compiled."); return finish(stages, rendered, states, cases)
    errors = []
    for i, case in enumerate(cases):
        try: rendered.append(compiled.render(**case.data()))
        except TemplateError as exc: errors.append(f"Case {i + 1}: {exc}")
    if not stage("Parameter rendering", errors, "Rendered against three different VLAN parameter sets."): return finish(stages, rendered, states, cases)
    for i, config in enumerate(rendered):
        try: states.append(parse_vlan_config(config))
        except ValueError as exc: errors.append(f"Case {i + 1}: {exc}")
    if not stage("Command structure", errors, "Parser checks VLAN encapsulation, interface address, and route commands."): return finish(stages, rendered, states, cases)
    errors = []
    for i, (state, case) in enumerate(zip(states, cases), 1):
        expected_i = {case.interface: {"vlan_id": case.vlan_id, "address": case.interface_cidr}}
        expected_r = [(case.destination_cidr, case.next_hop)]
        if state["interfaces"] != expected_i: errors.append(f"Case {i}: VLAN interface mismatch.")
        if state["routes"] != expected_r: errors.append(f"Case {i}: Route mismatch.")
    stage("Intent agreement", errors, "Checks VLAN ID, interface address, destination, and next hop exactly.")
    stage("Local route model", [], "Checks that the next hop belongs to the VLAN interface subnet.")
    return finish(stages, rendered, states, cases)


def check_ospf_template(source, intent):
    intent.validate(); stages=[]; rendered=[]; states=[]
    cases=[intent,OspfIntent("2.2.2.2","0.0.0.1","172.18.4.0/29"),OspfIntent("3.3.3.3","0.0.0.0","192.0.2.0/30")]
    def stage(name,errors,detail): stages.append({"name":name,"passed":not errors,"errors":errors,"detail":detail}); return not errors
    try: compiled=compile_template(source,OSPF_VARIABLES); stage("Template syntax",[],"Restricted OSPF placeholders; unknown variables are rejected.")
    except (TemplateError,ValueError) as exc: stage("Template syntax",[str(exc)],"Template could not be compiled."); return finish(stages,rendered,states,cases)
    errors=[]
    for i,case in enumerate(cases):
        try: rendered.append(compiled.render(**case.data()))
        except TemplateError as exc: errors.append(f"Case {i+1}: {exc}")
    if not stage("Parameter rendering",errors,"Rendered against three OSPF parameter sets."): return finish(stages,rendered,states,cases)
    for i,config in enumerate(rendered):
        lines=[line.strip() for line in config.splitlines() if line.strip() and not line.strip().startswith("!")]
        try:
            if lines[0]!="router ospf" or lines[-1]!="exit": raise ValueError("OSPF block must open with router ospf and close with exit.")
            rid=lines[1].split(); net=lines[2].split()
            if rid[:1]!=["router-id"] or net[:1]!=["network"] or len(rid)!=2 or len(net)!=4 or net[2]!="area": raise ValueError("OSPF block requires router-id and network ... area ... commands.")
            states.append({"router_id":rid[1],"network_cidr":str(ipaddress.IPv4Network(net[1],strict=True)),"area":net[3]})
        except (ValueError,IndexError) as exc: errors.append(f"Case {i+1}: {exc}")
    if not stage("Command structure",errors,"Parser checks router ID, network, area, and block structure."): return finish(stages,rendered,states,cases)
    errors=[]
    for i,(state,case) in enumerate(zip(states,cases),1):
        if state!={"router_id":case.router_id,"network_cidr":case.network_cidr,"area":case.area}: errors.append(f"Case {i}: OSPF intent mismatch.")
    stage("Intent agreement",errors,"Checks router ID, area, and advertised network exactly.")
    stage("Local route model",[],"OSPF neighbor and learned-route checks require the virtual two-router lab.")
    return finish(stages,rendered,states,cases)


def finish(stages, rendered, states, cases):
    return {"passed": len(stages) == 5 and all(s["passed"] for s in stages), "stages": stages,
            "rendered": rendered, "states": states, "parameter_sets": [c.data() for c in cases],
            "errors": [e for s in stages for e in s["errors"]],
            "verification_level": "local_static_checks", "device_tested": False}


def check_multi_template(source, intent):
    if not isinstance(intent, MultiIntent):
        raise ValueError("Expected an advanced multi-interface intent.")
    stages, rendered, states, cases = [], [], [], multi_parameter_cases(intent)

    def stage(name, errors, detail):
        stages.append({"name": name, "passed": not errors, "errors": errors, "detail": detail})
        return not errors
    try:
        compiled = compile_template(source, MULTI_VARIABLES)
        stage("Template syntax", [], "Restricted placeholders for multiple interfaces and routes.")
    except (TemplateError, ValueError) as exc:
        stage("Template syntax", [str(exc)], "Template could not be compiled.")
        return finish(stages, rendered, states, cases)
    errors = []
    for index, case in enumerate(cases):
        try:
            rendered.append(compiled.render(**case.context()))
        except TemplateError as exc:
            errors.append(f"Case {index + 1}: {exc}")
    if not stage("Parameter rendering", errors, "Rendered against three multi-interface parameter sets."):
        return finish(stages, rendered, states, cases)
    errors = []
    for index, config in enumerate(rendered):
        try:
            states.append(parse_config(config))
        except ValueError as exc:
            errors.append(f"Case {index + 1}: {exc}")
    if not stage("Command structure", errors, "Parser checks every interface block and route command."):
        return finish(stages, rendered, states, cases)
    errors = []
    for index, (state, case) in enumerate(zip(states, cases)):
        expected_interfaces = {item["name"]: item["cidr"] for item in case.interfaces}
        expected_routes = [(item["destination"], item["next_hop"]) for item in case.routes]
        errors.extend(f"Case {index + 1}: interface/address mismatch." for _ in [0] if state["interfaces"] != expected_interfaces)
        errors.extend(f"Case {index + 1}: route mismatch." for _ in [0] if state["routes"] != expected_routes)
    if not stage("Intent agreement", errors, "Checks every interface and static route exactly."):
        return finish(stages, rendered, states, cases)
    errors = []
    for index, state in enumerate(states):
        for _, hop in state["routes"]:
            hop_ip = ipaddress.IPv4Address(hop)
            if not any(hop_ip in ipaddress.IPv4Interface(address).network for address in state["interfaces"].values()):
                errors.append(f"Case {index + 1}: next hop has no directly connected path.")
    stage("Local route model", errors, "Checks each next hop against all configured interface subnets.")
    return finish(stages, rendered, states, cases)


def check_vendor_template(source, intent):
    """Validate the bounded vendor syntax without executing vendor commands."""
    if not isinstance(intent, VendorIntent):
        raise ValueError("Expected a vendor intent.")
    intent.validate(); stages=[]; rendered=[]
    def stage(name, errors, detail):
        stages.append({"name": name, "passed": not errors, "errors": errors, "detail": detail}); return not errors
    try:
        compiled = compile_template(source, VENDOR_VARIABLES); stage("Template syntax", [], "Restricted vendor placeholders.")
    except (TemplateError, ValueError) as exc:
        stage("Template syntax", [str(exc)], "Template could not be compiled."); return finish(stages, rendered, [], [intent])
    try: rendered = [compiled.render(**intent.data())]
    except TemplateError as exc:
        stage("Parameter rendering", [str(exc)], "Template did not render for the requested intent."); return finish(stages, rendered, [], [intent])
    stage("Parameter rendering", [], "Rendered for the requested vendor intent.")
    text = rendered[0]; lines = [line.strip() for line in text.splitlines() if line.strip()]
    errors=[]
    if intent.vendor == "cisco_ios":
        if not lines or lines[0] != f"interface {intent.interface}" or "no shutdown" not in lines or not any(line.startswith("ip route ") for line in lines):
            errors.append("Cisco IOS requires an interface block, no shutdown, and ip route.")
    else:
        if not text.startswith(f"set interfaces {intent.interface} unit 0") or f"set routing-options static route {intent.destination_cidr} next-hop {intent.next_hop}" not in text:
            errors.append("Junos requires set interfaces and set routing-options static route commands.")
    stage("Vendor command structure", errors, "Checks the selected vendor's required command forms.")
    iface_values = (intent.interface, str(ipaddress.IPv4Interface(intent.interface_cidr).ip), str(ipaddress.IPv4Interface(intent.interface_cidr).network.netmask)) if intent.vendor == "cisco_ios" else (intent.interface, intent.interface_cidr)
    stage("Intent agreement", [] if all(value in text for value in (*iface_values, intent.destination_cidr, intent.next_hop)) else ["Rendered commands do not contain every intent value."], "Checks vendor output against the explicit intent.")
    stage("Safety boundary", [], "Vendor syntax is statically checked; no device command is executed.")
    return finish(stages, rendered, [], [intent])
