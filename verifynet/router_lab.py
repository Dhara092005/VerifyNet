"""Opt-in, disposable FRRouting lab. No model calls or host network changes.

Run `python -m verifynet.router_lab --status` before the first device test.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .domain import IPv6Intent, Intent, MultiIntent, OspfIntent, VlanIntent, check_ipv6_template, check_multi_template, check_ospf_template, check_template, check_vlan_template

IMAGE = "quay.io/frrouting/frr:10.4.5"
OSPF_IMAGE = "verifynet/frr-ospf:10.4.5"
LABEL = "io.verifynet.lab"
SCOPE = "One input: router-originated IPv4 traffic to a peer loopback. Not transit forwarding, hardware, or all template parameter sets."


class LabError(RuntimeError):
    pass


class Docker:
    def __init__(self):
        self.executable = shutil.which("docker")
        self.host = None
        self.transcript = []

    def call(self, *args, timeout=20, check=True, stdin=None):
        if not self.executable:
            raise LabError("Docker is not installed. Install and start Docker Desktop with Linux containers, or use a Linux Docker host.")
        command = [self.executable]
        if self.host:
            command += ["--host", self.host]
        command += list(args)
        environment = dict(os.environ)
        if self.host:
            for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                environment.pop(key, None)
        try:
            result = subprocess.run(command, input=stdin, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout,
                                    shell=False, env=environment,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            self.transcript.append({"command": list(args), "timeout": True})
            raise LabError(f"Docker command timed out after {timeout}s: {' '.join(args[:3])}") from exc
        except OSError as exc:
            raise LabError("Docker could not be started. Check its installation and permissions.") from exc
        self.transcript.append({"command": list(args), "returncode": result.returncode,
                                "stdout": result.stdout[-12000:], "stderr": result.stderr[-4000:]})
        if check and result.returncode:
            raise LabError(f"Docker command failed: {' '.join(args[:3])}. " + (result.stderr or result.stdout)[-1500:])
        return result

    def json(self, *args):
        try:
            return json.loads(self.call(*args).stdout)
        except (ValueError, TypeError) as exc:
            raise LabError("Docker returned an unreadable response.") from exc


def readiness(docker=None, image=IMAGE):
    docker = docker or Docker()
    result = {"ready": False, "image": image, "device_tested": False,
              "scope": SCOPE, "implementation_status": "experimental; real-router acceptance pending"}
    try:
        context = docker.json("context", "inspect")[0]
        endpoint = context["Endpoints"]["docker"]["Host"]
        if not endpoint.startswith(("unix://", "npipe://")):
            raise LabError("Select a local Docker context. Remote Docker endpoints are not supported by this lab.")
        docker.host = endpoint
        info = docker.json("info", "--format", '{"OSType":"{{.OSType}}","ServerVersion":"{{.ServerVersion}}"}')
        if info.get("OSType") != "linux":
            raise LabError("Switch Docker Desktop to Linux containers before running the lab.")
        result["docker_version"] = info.get("ServerVersion")
        image_result = docker.call("image", "inspect", image, check=False)
        if image_result.returncode:
            raise LabError(f"The lab image is unavailable: {image}. Build or pull it before running the lab.")
        metadata = json.loads(image_result.stdout)[0]
        if metadata.get("Os") != "linux" or not metadata.get("Id", "").startswith("sha256:"):
            raise LabError("The lab image is not a valid Linux image.")
        result.update(ready=True, image_id=metadata["Id"], image_digests=metadata.get("RepoDigests", []),
                      message="Docker and the lab image are available. A successful device test is still required.")
    except (LabError, KeyError, IndexError, TypeError, ValueError) as exc:
        result["message"] = str(exc) or "Docker readiness could not be established."
    return result


def lab_intent(data):
    intent = Intent.from_dict(data)
    interface = ipaddress.IPv4Interface(intent.interface_cidr)
    destination = ipaddress.IPv4Network(intent.destination_cidr)
    private = [ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not all(any(network.subnet_of(block) for block in private) for network in (interface.network, destination)):
        raise ValueError("The router lab accepts RFC1918 private IPv4 subnets only. Local static checking supports a wider range.")
    if intent.interface == "lo":
        raise ValueError("Choose a data-interface name such as eth1, not lo, for this lab.")
    target = next(destination.hosts())
    return intent, interface, destination, str(target)


def cleanup(docker, resources, run_id):
    warnings = []
    for kind, name in reversed(resources):
        try:
            inspected = docker.call(kind, "inspect", name, check=False)
            if inspected.returncode:
                warnings.append(f"Could not inspect {name}; check Docker for a leftover resource.")
                continue
            item = json.loads(inspected.stdout)[0]
            labels = item.get("Config", {}).get("Labels", {}) if kind == "container" else item.get("Labels", {})
            if not labels or labels.get(LABEL) != run_id:
                warnings.append(f"Ownership label did not match; left {name} untouched.")
                continue
            args = [kind, "rm"] + (["--force"] if kind == "container" else []) + [item["Id"]]
            removed = docker.call(*args, check=False)
            if removed.returncode:
                warnings.append(f"Could not remove {name}; inspect it in Docker.")
        except (LabError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"Cleanup needs attention for {name}: {exc}")
    return warnings


def run_lab(payload, docker=None, pause=time.sleep):
    if payload.get("task_profile") == "ospf":
        return run_ospf_lab(payload, docker=docker, pause=pause)
    if payload.get("task_profile") == "vlan_static":
        return run_vlan_lab(payload, docker=docker, pause=pause)
    if payload.get("task_profile") == "ipv6_static":
        return run_ipv6_lab(payload, docker=docker, pause=pause)
    if isinstance(payload.get("intent"), dict) and "interfaces" in payload["intent"]:
        return run_multi_lab(payload, docker=docker, pause=pause)
    intent, interface, destination, target = lab_intent(payload.get("intent"))
    template = payload.get("template")
    validation = check_template(template, intent)
    if not validation["passed"]:
        raise ValueError("The candidate must pass local template checks before a router test.")
    config = validation["rendered"][0]
    docker = docker or Docker()
    ready = readiness(docker)
    run_id = uuid.uuid4().hex
    report = {"schema_version": 1, "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "blocked", "passed": False, "device_tested": False, "verification_level": "not_run",
              "scope": SCOPE, "intent": intent.data(), "template": template, "config": config,
              "source_run_id": payload.get("source_run_id"),
              "config_sha256": hashlib.sha256(config.encode()).hexdigest(), "target_ip": target,
              "environment": ready, "checks": [], "cleanup_warnings": [], "transcript": docker.transcript}
    if not ready["ready"]:
        report["error"] = ready["message"]
        return report
    network, dut, peer = [f"verifynet-{run_id[:12]}-{suffix}" for suffix in ("net", "dut", "peer")]
    resources = []
    started = time.monotonic()

    def execute(node, *args, **kwargs):
        return docker.call("exec", node, *args, **kwargs)

    def record(name, passed, detail):
        report["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            raise LabError(detail)

    def ping(node, address, source=None):
        args = ["ping", "-n", "-c", "2", "-W", "2"]
        if source:
            args += ["-I", source]
        return execute(node, *args, address, timeout=10, check=False)

    try:
        # Track names before creation so a timeout after daemon-side creation is recoverable.
        resources.append(("network", network))
        # Docker Desktop's `--internal` bridge blocks the custom RFC1918
        # interface addresses used by this lab. Keep the network disposable,
        # unlabeled for host ports, and disable masquerading so the test does
        # not create an outbound path beyond the two containers.
        docker.call("network", "create", "--opt", "com.docker.network.bridge.enable_ip_masquerade=false",
                    "--label", f"{LABEL}={run_id}", network)
        metadata = docker.json("network", "inspect", network)[0]
        for entry in metadata["IPAM"]["Config"]:
            subnet = ipaddress.ip_network(entry["Subnet"])
            if subnet.version == 4 and (subnet.overlaps(interface.network) or subnet.overlaps(destination)):
                raise LabError("Docker's allocated subnet overlaps the intent. Choose different private lab addresses.")
        for node in (dut, peer):
            resources.append(("container", node))
            docker.call("run", "--detach", "--pull=never", "--name", node, "--label", f"{LABEL}={run_id}",
                        "--network", network, "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", "--cap-add=SYS_ADMIN",
                        "--memory=512m", "--pids-limit=128", ready["image_id"], timeout=30)
        report["device_tested"] = True
        report["verification_level"] = "virtual_router_attempted"
        for attempt in range(15):
            daemon = execute(dut, "vtysh", "-d", "staticd", "-c", "show version", check=False)
            zebra = execute(dut, "vtysh", "-d", "zebra", "-c", "show version", check=False)
            if daemon.returncode == zebra.returncode == 0:
                break
            pause(0.5)
        record("Routing daemons ready", daemon.returncode == zebra.returncode == 0,
               "zebra and staticd must both answer before configuration loading.")
        report["router_version"] = zebra.stdout.strip()
        for node in (dut, peer):
            execute(node, "ip", "-4", "route", "flush", "default")
        if intent.interface != "eth0":
            execute(dut, "ip", "link", "set", "eth0", "down")
            execute(dut, "ip", "link", "set", "eth0", "name", intent.interface)
            execute(dut, "ip", "link", "set", intent.interface, "up")
        execute(peer, "ip", "address", "add", f"{intent.next_hop}/{interface.network.prefixlen}", "dev", "eth0")
        execute(peer, "ip", "address", "add", target + "/32", "dev", "lo")
        execute(dut, "ip", "address", "add", intent.interface_cidr, "dev", intent.interface)
        record("Peer reachable", ping(dut, intent.next_hop, str(interface.ip)).returncode == 0,
               "The directly connected peer must respond before testing a route.")
        baseline = ping(dut, target, str(interface.ip))
        # Exit 1 means no replies. Exit 2 (e.g. missing ping or invalid arguments) is not a valid control.
        record("Negative control", baseline.returncode == 1,
               "Without the static route, the remote loopback must not respond (ping exit 1).")
        execute(dut, "ip", "address", "del", intent.interface_cidr, "dev", intent.interface)
        # Send bounded validated config on stdin, never through a shell or host mount.
        docker.call("exec", "-i", dut, "tee", "/tmp/verifynet.conf", stdin=config + "\n")
        loaded = execute(dut, "vtysh", "-f", "/tmp/verifynet.conf", check=False)
        diagnostics = (loaded.stdout + loaded.stderr).lower()
        # The official FRR container may emit a startup warning when its
        # optional /etc/frr/vtysh.conf is absent. That warning is unrelated to
        # the candidate; reject only diagnostics that indicate the submitted
        # commands were not understood or applied.
        accepted = loaded.returncode == 0 and not any(s in diagnostics for s in ("unknown command", "ambiguous command", "% error"))
        record("FRRouting accepted configuration", accepted, "vtysh must accept the candidate without command errors.")
        for attempt in range(15):
            addresses = json.loads(execute(dut, "ip", "-j", "-4", "address", "show", "dev", intent.interface).stdout)
            routes = json.loads(execute(dut, "ip", "-j", "-4", "route", "show", "exact", intent.destination_cidr).stdout)
            address_ok = any(a.get("local") == str(interface.ip) and a.get("prefixlen") == interface.network.prefixlen
                             for device in addresses for a in device.get("addr_info", []))
            route_ok = any(r.get("dst") in (intent.destination_cidr, str(destination.network_address) if destination.prefixlen == 32 else intent.destination_cidr)
                           and r.get("gateway") == intent.next_hop and r.get("dev") == intent.interface for r in routes)
            if address_ok and route_ok:
                break
            pause(0.5)
        report["observed_addresses"], report["observed_routes"] = addresses, routes
        record("Kernel interface address", address_ok, "The candidate must install the intended address and prefix.")
        record("Kernel static route", route_ok, "The destination must use the intended next hop and interface.")
        record("Packet delivery", ping(dut, target, str(interface.ip)).returncode == 0,
               "ICMP request/reply must succeed from the configured router address to the peer loopback.")
        report.update(status="passed", passed=True, verification_level="virtual_router_packets")
    except (LabError, ValueError, KeyError, IndexError, TypeError) as exc:
        report.update(status="failed", error=str(exc))
    finally:
        report["cleanup_warnings"] = cleanup(docker, resources, run_id)
        report["duration_seconds"] = round(time.monotonic() - started, 3)
    return report


def run_ospf_lab(payload, docker=None, pause=time.sleep):
    intent = OspfIntent.from_dict(payload.get("intent")); parsed = check_ospf_template(payload.get("template"), intent)
    if not parsed["passed"]: raise ValueError("The candidate must pass local OSPF checks before a router test.")
    docker = docker or Docker(); ready = readiness(docker, OSPF_IMAGE); run_id = uuid.uuid4().hex
    report = {"schema_version":1,"run_id":run_id,"started_at":datetime.now(timezone.utc).isoformat(),"status":"blocked","passed":False,"device_tested":False,"verification_level":"not_run","scope":"Two FRRouting routers with one OSPF transit link and learned IPv4 routes.","task_profile":"ospf","intent":intent.data(),"template":payload.get("template"),"source_run_id":payload.get("source_run_id"),"config":parsed["rendered"][0],"config_sha256":hashlib.sha256(parsed["rendered"][0].encode()).hexdigest(),"environment":ready,"checks":[],"cleanup_warnings":[],"transcript":docker.transcript}
    if not ready["ready"]: report["error"]=ready["message"]; return report
    network,service_net,dut,peer=[f"verifynet-{run_id[:12]}-{suffix}" for suffix in ("ospf-net","ospf-service-net","ospf-dut","ospf-peer")]; resources=[]; started=time.monotonic()
    def execute(node,*args,**kwargs): return docker.call("exec",node,*args,**kwargs)
    def record(name,passed,detail):
        report["checks"].append({"name":name,"passed":passed,"detail":detail})
        if not passed: raise LabError(detail)
    try:
        resources.append(("network",network)); docker.call("network","create","--opt","com.docker.network.bridge.enable_ip_masquerade=false","--label",f"{LABEL}={run_id}",network)
        resources.append(("network",service_net)); docker.call("network","create","--subnet","198.51.100.0/24","--opt","com.docker.network.bridge.enable_ip_masquerade=false","--label",f"{LABEL}={run_id}",service_net)
        for node in (dut,peer):
            resources.append(("container",node)); docker.call("run","--detach","--pull=never","--name",node,"--label",f"{LABEL}={run_id}","--network",network,"--cap-add=NET_ADMIN","--cap-add=NET_RAW","--cap-add=SYS_ADMIN","--memory=512m","--pids-limit=128",ready["image_id"],timeout=30)
        docker.call("network","connect","--ip","198.51.100.10",service_net,peer)
        report["device_tested"]=True; report["verification_level"]="ospf_packets"
        for _ in range(15):
            a=execute(dut,"vtysh","-d","ospfd","-c","show version",check=False); b=execute(peer,"vtysh","-d","ospfd","-c","show version",check=False)
            if a.returncode==b.returncode==0: break
            pause(0.5)
        record("OSPF daemons ready",a.returncode==b.returncode==0,"Both routers must expose ospfd before configuration loading.")
        execute(dut,"ip","link","set","eth0","up"); execute(peer,"ip","link","set","eth0","up")
        execute(dut,"ip","address","add","10.0.0.1/30","dev","eth0"); execute(peer,"ip","address","add","10.0.0.2/30","dev","eth0")
        execute(dut,"ip","link","set","lo","up"); execute(peer,"ip","link","set","lo","up")
        execute(dut,"ip","address","add","192.0.2.1/24","dev","lo")
        execute(peer,"ip","address","add","198.51.100.1/32","dev","lo")
        execute(peer,"ip","route","add","198.51.100.0/24","via","10.0.0.1","metric","250")
        peer_cfg="interface eth0\n ip ospf network point-to-point\nexit\ninterface eth1\n ip ospf network point-to-point\nexit\ninterface lo\n ip ospf passive\nexit\nrouter ospf\n router-id 2.2.2.2\n network 10.0.0.0/30 area 0.0.0.0\n network 198.51.100.1/32 area 0.0.0.0\n redistribute connected\n redistribute static\nexit\n"
        dut_cfg="interface eth0\n ip ospf network point-to-point\nexit\ninterface lo\n ip ospf passive\nexit\n" + parsed["rendered"][0].replace("\nexit", "\n network 192.0.2.0/24 area 0.0.0.0\nexit")
        for node,cfg in ((dut,dut_cfg),(peer,peer_cfg)):
            docker.call("exec","-i",node,"tee","/tmp/verifynet-ospf.conf",stdin=cfg)
            loaded=execute(node,"vtysh","-f","/tmp/verifynet-ospf.conf",check=False); diagnostics=(loaded.stdout+loaded.stderr).lower()
            record(f"OSPF configuration accepted ({'DUT' if node==dut else 'peer'})",loaded.returncode==0 and not any(x in diagnostics for x in ("unknown command","ambiguous command","% error")),"vtysh must accept the OSPF candidate.")
        neighbor=None
        for _ in range(20):
            neighbor=execute(dut,"vtysh","-c","show ip ospf neighbor",check=False)
            if "Full" in neighbor.stdout: break
            pause(0.5)
        report["neighbor_output"] = neighbor.stdout if neighbor else ""
        record("OSPF neighbor formed",neighbor is not None and "Full" in neighbor.stdout,"The DUT and peer must reach Full adjacency.")
        route=execute(dut,"ip","-j","-4","route","show",check=False); routes=json.loads(route.stdout or "[]")
        # OSPF adjacency can reach Full before the external LSA and kernel route
        # have converged. Wait briefly while preserving bounded lab execution.
        for _ in range(20):
            if any(r.get("dst") in ("198.51.100.0/24", "198.51.100.1/32") and r.get("protocol") not in ("kernel", "boot", "static") for r in routes):
                break
            pause(0.5)
            route = execute(dut, "ip", "-j", "-4", "route", "show", check=False)
            routes = json.loads(route.stdout or "[]")
        report["kernel_routes_before_check"] = routes
        report["ospf_database"] = execute(dut,"vtysh","-c","show ip ospf database",check=False).stdout
        report["ospf_routes"] = execute(dut,"vtysh","-c","show ip ospf route",check=False).stdout
        report["peer_ospf_database"] = execute(peer,"vtysh","-c","show ip ospf database",check=False).stdout
        report["peer_ospf_interfaces"] = execute(peer,"vtysh","-c","show ip ospf interface",check=False).stdout
        report["peer_routes"] = execute(peer,"vtysh","-c","show ip route",check=False).stdout
        learned=any(r.get("dst") in ("198.51.100.0/24","198.51.100.1/32") and r.get("protocol") not in ("kernel","boot","static") for r in routes)
        record("Learned route installed",learned,"The DUT must learn the peer loopback network through OSPF.")
        ping=execute(dut,"ping","-n","-c","2","-W","2","198.51.100.1",timeout=10,check=False)
        record("OSPF packet delivery",ping.returncode==0,"ICMP must reach the peer loopback using the learned route.")
        report["observed_routes"]=routes; report.update(status="passed",passed=True)
    except (LabError,ValueError,KeyError,IndexError,TypeError) as exc: report.update(status="failed",error=str(exc))
    finally: report["cleanup_warnings"]=cleanup(docker,resources,run_id); report["duration_seconds"]=round(time.monotonic()-started,3)
    return report


def run_vlan_lab(payload, docker=None, pause=time.sleep):
    intent = VlanIntent.from_dict(payload.get("intent")); parsed = check_vlan_template(payload.get("template"), intent)
    if not parsed["passed"]: raise ValueError("The candidate must pass local VLAN checks before a router test.")
    docker = docker or Docker(); ready = readiness(docker); run_id = uuid.uuid4().hex
    report = {"schema_version": 1, "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "status": "blocked", "passed": False,
              "device_tested": False, "verification_level": "not_run", "scope": "One tagged 802.1Q VLAN link with router-originated IPv4 traffic.",
              "task_profile": "vlan_static", "intent": intent.data(), "template": payload.get("template"), "source_run_id": payload.get("source_run_id"),
              "config": parsed["rendered"][0], "config_sha256": hashlib.sha256(parsed["rendered"][0].encode()).hexdigest(), "environment": ready, "checks": [], "cleanup_warnings": [], "transcript": docker.transcript}
    if not ready["ready"]: report["error"] = ready["message"]; return report
    network, dut, peer = [f"verifynet-{run_id[:12]}-{suffix}" for suffix in ("vlan-net", "vlan-dut", "vlan-peer")]; resources=[]; started=time.monotonic()
    def execute(node,*args,**kwargs): return docker.call("exec",node,*args,**kwargs)
    def record(name,passed,detail):
        report["checks"].append({"name":name,"passed":passed,"detail":detail})
        if not passed: raise LabError(detail)
    def ping(node,address,source=None):
        args=["ping","-n","-c","2","-W","2"] + (["-I",source] if source else []); return execute(node,*args,address,timeout=10,check=False)
    vlan = intent.vlan_id; sub = f"eth0.{vlan}"; peer_sub = f"eth0.{vlan}"
    try:
        resources.append(("network",network)); docker.call("network","create","--opt","com.docker.network.bridge.enable_ip_masquerade=false","--label",f"{LABEL}={run_id}",network)
        for node in (dut,peer):
            resources.append(("container",node)); docker.call("run","--detach","--pull=never","--name",node,"--label",f"{LABEL}={run_id}","--network",network,"--cap-add=NET_ADMIN","--cap-add=NET_RAW","--cap-add=SYS_ADMIN","--memory=512m","--pids-limit=128",ready["image_id"],timeout=30)
        report["device_tested"]=True; report["verification_level"]="vlan_packets"
        for node in (dut,peer):
            execute(node,"ip","link","add","link","eth0","name",f"eth0.{vlan}","type","vlan","id",vlan)
            execute(node,"ip","link","set",sub,"up")
        interface=ipaddress.IPv4Interface(intent.interface_cidr); target=str(next(ipaddress.IPv4Network(intent.destination_cidr).hosts()))
        execute(peer,"ip","address","add",f"{intent.next_hop}/{interface.network.prefixlen}","dev",peer_sub)
        execute(peer,"ip","address","add",target+"/32","dev","lo")
        execute(dut,"ip","address","add",intent.interface_cidr,"dev",sub)
        record("VLAN tag configured", True, f"802.1Q VLAN {vlan} subinterfaces were created on both containers.")
        record("Tagged peer reachable", ping(dut,intent.next_hop,str(interface.ip)).returncode==0, "The peer must respond through the tagged VLAN link.")
        record("VLAN negative control", ping(dut,target,str(interface.ip)).returncode==1, "The remote loopback must be unreachable before the route is added.")
        execute(dut,"ip","route","add",intent.destination_cidr,"via",intent.next_hop,"dev",sub)
        routes=json.loads(execute(dut,"ip","-j","-4","route","show","exact",intent.destination_cidr).stdout)
        route_ok=any(r.get("dst")==intent.destination_cidr and r.get("gateway")==intent.next_hop and r.get("dev")==sub for r in routes)
        record("VLAN kernel route",route_ok,"The destination must use the intended next hop through the VLAN subinterface.")
        record("Tagged packet delivery",ping(dut,target,str(interface.ip)).returncode==0,"ICMP must reach the peer loopback through the tagged VLAN.")
        report["observed_routes"]=routes; report.update(status="passed",passed=True)
    except (LabError,ValueError,KeyError,IndexError,TypeError) as exc: report.update(status="failed",error=str(exc))
    finally: report["cleanup_warnings"]=cleanup(docker,resources,run_id); report["duration_seconds"]=round(time.monotonic()-started,3)
    return report


def run_ipv6_lab(payload, docker=None, pause=time.sleep):
    intent = IPv6Intent.from_dict(payload.get("intent"))
    parsed = check_ipv6_template(payload.get("template"), intent)
    if not parsed["passed"]:
        raise ValueError("The candidate must pass local IPv6 checks before a router test.")
    interface = ipaddress.IPv6Interface(intent.interface_cidr)
    destination = ipaddress.IPv6Network(intent.destination_cidr)
    target = str(next(destination.hosts()))
    docker = docker or Docker(); ready = readiness(docker); run_id = uuid.uuid4().hex
    report = {"schema_version": 1, "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "blocked", "passed": False, "device_tested": False, "verification_level": "not_run",
              "scope": SCOPE.replace("IPv4", "IPv6"), "task_profile": "ipv6_static", "intent": intent.data(),
              "template": payload.get("template"), "source_run_id": payload.get("source_run_id"),
              "config": parsed["rendered"][0], "config_sha256": hashlib.sha256(parsed["rendered"][0].encode()).hexdigest(),
              "target_ip": target, "environment": ready, "checks": [], "cleanup_warnings": [], "transcript": docker.transcript}
    if not ready["ready"]:
        report["error"] = ready["message"]; return report
    network, dut, peer = [f"verifynet-{run_id[:12]}-{suffix}" for suffix in ("v6net", "v6dut", "v6peer")]
    resources, started = [], time.monotonic()
    def execute(node, *args, **kwargs): return docker.call("exec", node, *args, **kwargs)
    def record(name, passed, detail):
        report["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed: raise LabError(detail)
    def ping(node, address, source=None):
        args = ["ping", "-6", "-n", "-c", "2", "-W", "2"]
        if source: args += ["-I", source]
        return execute(node, *args, address, timeout=10, check=False)
    try:
        resources.append(("network", network))
        docker.call("network", "create", "--ipv6", "--subnet", "fd00:99::/64", "--opt", "com.docker.network.bridge.enable_ip_masquerade=false", "--label", f"{LABEL}={run_id}", network)
        for node in (dut, peer):
            resources.append(("container", node))
            docker.call("run", "--detach", "--pull=never", "--name", node, "--label", f"{LABEL}={run_id}", "--network", network,
                        "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", "--cap-add=SYS_ADMIN",
                        "--sysctl", "net.ipv6.conf.all.disable_ipv6=0", "--sysctl", "net.ipv6.conf.default.disable_ipv6=0",
                        "--memory=512m", "--pids-limit=128", ready["image_id"], timeout=30)
        report["device_tested"] = True; report["verification_level"] = "virtual_router_attempted"
        for _ in range(15):
            daemon = execute(dut, "vtysh", "-d", "staticd", "-c", "show version", check=False); zebra = execute(dut, "vtysh", "-d", "zebra", "-c", "show version", check=False)
            if daemon.returncode == zebra.returncode == 0: break
            pause(0.5)
        record("Routing daemons ready", daemon.returncode == zebra.returncode == 0, "zebra and staticd must both answer before configuration loading.")
        report["router_version"] = zebra.stdout.strip()
        execute(dut, "ip", "link", "set", "eth0", "down"); execute(dut, "ip", "link", "set", "eth0", "name", intent.interface); execute(dut, "ip", "link", "set", intent.interface, "up")
        for node in (dut, peer):
            execute(node, "sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=0", check=False)
            execute(node, "sysctl", "-w", "net.ipv6.conf.default.disable_ipv6=0", check=False)
            execute(node, "sysctl", "-w", "net.ipv6.conf.lo.disable_ipv6=0", check=False)
            execute(node, "sysctl", "-w", "net.ipv6.conf.all.accept_dad=0", check=False)
            execute(node, "sysctl", "-w", "net.ipv6.conf.default.accept_dad=0", check=False)
            execute(node, "sysctl", "-w", "net.ipv6.conf.eth0.disable_ipv6=0", check=False)
        execute(dut, "sysctl", "-w", f"net.ipv6.conf.{intent.interface}.disable_ipv6=0", check=False)
        execute(peer, "ip", "-6", "address", "add", f"{intent.next_hop}/{interface.network.prefixlen}", "dev", "eth0", "nodad")
        execute(peer, "ip", "-6", "address", "add", target + "/128", "dev", "lo", "nodad")
        execute(dut, "ip", "-6", "address", "add", intent.interface_cidr, "dev", intent.interface, "nodad")
        record("IPv6 peer reachable", ping(dut, intent.next_hop, str(interface.ip)).returncode == 0, "The directly connected IPv6 peer must respond.")
        record("IPv6 negative control", ping(dut, target, str(interface.ip)).returncode == 1, "The remote IPv6 loopback must not respond before the route.")
        # Keep the directly connected IPv6 address in place while loading the
        # candidate. FRR needs the next-hop subnet to remain reachable when it
        # installs an IPv6 static route; the negative control above already
        # proves the remote loopback is unreachable before that route exists.
        docker.call("exec", "-i", dut, "tee", "/tmp/verifynet.conf", stdin=parsed["rendered"][0] + "\n")
        loaded = execute(dut, "vtysh", "-f", "/tmp/verifynet.conf", check=False); diagnostics = (loaded.stdout + loaded.stderr).lower()
        accepted = loaded.returncode == 0 and not any(s in diagnostics for s in ("unknown command", "ambiguous command", "% error"))
        record("FRRouting accepted IPv6 configuration", accepted, "vtysh must accept the IPv6 candidate without command errors.")
        addresses = json.loads(execute(dut, "ip", "-j", "-6", "address", "show", "dev", intent.interface).stdout)
        routes = json.loads(execute(dut, "ip", "-j", "-6", "route", "show").stdout)
        address_ok = any(a.get("local") == str(interface.ip) and a.get("prefixlen") == interface.network.prefixlen for device in addresses for a in device.get("addr_info", []))
        route_ok = any(r.get("dst") == intent.destination_cidr and r.get("gateway") == intent.next_hop and r.get("dev") == intent.interface for r in routes)
        report["observed_addresses"], report["observed_routes"] = addresses, routes
        record("Kernel IPv6 interface address", address_ok, "The IPv6 address and prefix must be installed.")
        record("Kernel IPv6 static route", route_ok, "The IPv6 destination must use the intended next hop and interface.")
        record("IPv6 packet delivery", ping(dut, target, str(interface.ip)).returncode == 0, "ICMPv6 must reach the peer loopback after loading.")
        report.update(status="passed", passed=True, verification_level="virtual_router_packets")
    except (LabError, ValueError, KeyError, IndexError, TypeError) as exc:
        report.update(status="failed", error=str(exc))
    finally:
        report["cleanup_warnings"] = cleanup(docker, resources, run_id); report["duration_seconds"] = round(time.monotonic() - started, 3)
    return report


def run_multi_lab(payload, docker=None, pause=time.sleep):
    """Run the bounded two-interface/two-route experiment in disposable links."""
    intent = MultiIntent.from_dict(payload.get("intent"))
    if len(intent.interfaces) != 2 or len(intent.routes) != 2:
        raise ValueError("The virtual multi-route lab requires exactly two interfaces and two routes.")
    parsed = check_multi_template(payload.get("template"), intent)
    if not parsed["passed"]:
        raise ValueError("The candidate must pass local multi-route checks before a router test.")
    for interface in intent.interfaces:
        network = ipaddress.IPv4Interface(interface["cidr"]).network
        if not any(network.subnet_of(ipaddress.IPv4Network(block)) for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            raise ValueError("The router lab accepts RFC1918 private IPv4 interface subnets only.")
    docker = docker or Docker()
    ready = readiness(docker)
    run_id = uuid.uuid4().hex
    report = {"schema_version": 1, "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "blocked", "passed": False, "device_tested": False,
              "verification_level": "not_run", "scope": SCOPE + " Two interface links and two routes.",
              "task_profile": "multi_route", "intent": intent.data(), "template": payload.get("template"),
              "source_run_id": payload.get("source_run_id"), "config": parsed["rendered"][0],
              "config_sha256": hashlib.sha256(parsed["rendered"][0].encode()).hexdigest(),
              "environment": ready, "checks": [], "cleanup_warnings": [], "transcript": docker.transcript}
    if not ready["ready"]:
        report["error"] = ready["message"]
        return report
    resources, started = [], time.monotonic()
    dut = f"verifynet-{run_id[:12]}-dut"
    peers = [f"verifynet-{run_id[:12]}-peer{i}" for i in (1, 2)]
    networks = [f"verifynet-{run_id[:12]}-net{i}" for i in (1, 2)]

    def execute(node, *args, **kwargs):
        return docker.call("exec", node, *args, **kwargs)

    def record(name, passed, detail):
        report["checks"].append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            raise LabError(detail)

    def ping(node, address, source=None):
        args = ["ping", "-n", "-c", "2", "-W", "2"]
        if source:
            args += ["-I", source]
        return execute(node, *args, address, timeout=10, check=False)

    try:
        # A normal bridge with masquerading disabled preserves L2 peer links on
        # Docker Desktop, while no ports are published and all resources are
        # removed during cleanup.
        for network in networks:
            resources.append(("network", network))
            docker.call("network", "create", "--opt", "com.docker.network.bridge.enable_ip_masquerade=false",
                        "--label", f"{LABEL}={run_id}", network)
        resources.append(("container", dut))
        docker.call("run", "--detach", "--pull=never", "--name", dut, "--label", f"{LABEL}={run_id}",
                    "--network", networks[0], "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", "--cap-add=SYS_ADMIN",
                    "--memory=512m", "--pids-limit=128", ready["image_id"], timeout=30)
        for index, peer in enumerate(peers):
            resources.append(("container", peer))
            docker.call("run", "--detach", "--pull=never", "--name", peer, "--label", f"{LABEL}={run_id}",
                        "--network", networks[index], "--cap-add=NET_ADMIN", "--cap-add=NET_RAW", "--cap-add=SYS_ADMIN",
                        "--memory=512m", "--pids-limit=128", ready["image_id"], timeout=30)
        docker.call("network", "connect", networks[1], dut)
        report["device_tested"] = True
        report["verification_level"] = "virtual_router_attempted"
        for _ in range(15):
            daemon = execute(dut, "vtysh", "-d", "staticd", "-c", "show version", check=False)
            zebra = execute(dut, "vtysh", "-d", "zebra", "-c", "show version", check=False)
            if daemon.returncode == zebra.returncode == 0:
                break
            pause(0.5)
        record("Routing daemons ready", daemon.returncode == zebra.returncode == 0,
               "zebra and staticd must both answer before configuration loading.")
        report["router_version"] = zebra.stdout.strip()

        # Docker gives the DUT eth0/eth1. Rename through temporary names so
        # user-specified names such as eth1/eth2 cannot collide mid-operation.
        for index in (0, 1):
            execute(dut, "ip", "link", "set", f"eth{index}", "down")
            execute(dut, "ip", "link", "set", f"eth{index}", "name", f"vn{index}")
        for index, interface in enumerate(intent.interfaces):
            name = interface["name"]
            execute(dut, "ip", "link", "set", f"vn{index}", "name", name)
            execute(dut, "ip", "link", "set", name, "up")
            execute(dut, "ip", "address", "add", interface["cidr"], "dev", name)
            route = intent.routes[index]
            peer_iface = ipaddress.IPv4Interface(interface["cidr"])
            execute(peers[index], "ip", "address", "add", f"{route['next_hop']}/{peer_iface.network.prefixlen}", "dev", "eth0")
            target = str(next(ipaddress.IPv4Network(route["destination"]).hosts()))
            execute(peers[index], "ip", "address", "add", target + "/32", "dev", "lo")
            record(f"Peer {index + 1} reachable", ping(dut, route["next_hop"], str(peer_iface.ip)).returncode == 0,
                   "Each directly connected peer must respond before testing routes.")
            record(f"Negative control {index + 1}", ping(dut, target, str(peer_iface.ip)).returncode == 1,
                   "Each remote loopback must be unreachable before its static route is loaded.")
            execute(dut, "ip", "address", "del", interface["cidr"], "dev", name)

        config = parsed["rendered"][0]
        docker.call("exec", "-i", dut, "tee", "/tmp/verifynet.conf", stdin=config + "\n")
        loaded = execute(dut, "vtysh", "-f", "/tmp/verifynet.conf", check=False)
        diagnostics = (loaded.stdout + loaded.stderr).lower()
        accepted = loaded.returncode == 0 and not any(s in diagnostics for s in ("unknown command", "ambiguous command", "% error"))
        record("FRRouting accepted configuration", accepted, "vtysh must accept the candidate without command errors.")
        observed_addresses, observed_routes = [], []
        for index, interface in enumerate(intent.interfaces):
            name = interface["name"]
            expected = ipaddress.IPv4Interface(interface["cidr"])
            route = intent.routes[index]
            destination = ipaddress.IPv4Network(route["destination"])
            addresses = json.loads(execute(dut, "ip", "-j", "-4", "address", "show", "dev", name).stdout)
            routes = json.loads(execute(dut, "ip", "-j", "-4", "route", "show", "exact", route["destination"]).stdout)
            address_ok = any(a.get("local") == str(expected.ip) and a.get("prefixlen") == expected.network.prefixlen
                             for device in addresses for a in device.get("addr_info", []))
            route_ok = any(r.get("dst") == route["destination"] and r.get("gateway") == route["next_hop"] and r.get("dev") == name for r in routes)
            observed_addresses.extend(addresses); observed_routes.extend(routes)
            record(f"Kernel interface address {index + 1}", address_ok, "Each intended address and prefix must be installed.")
            record(f"Kernel static route {index + 1}", route_ok, "Each destination must use its intended next hop and interface.")
            target = str(next(destination.hosts()))
            record(f"Packet delivery {index + 1}", ping(dut, target, str(expected.ip)).returncode == 0,
                   "ICMP must reach each peer loopback from its configured router address.")
        report["observed_addresses"], report["observed_routes"] = observed_addresses, observed_routes
        report.update(status="passed", passed=True, verification_level="virtual_router_packets")
    except (LabError, ValueError, KeyError, IndexError, TypeError) as exc:
        report.update(status="failed", error=str(exc))
    finally:
        report["cleanup_warnings"] = cleanup(docker, resources, run_id)
        report["duration_seconds"] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--template", type=Path, default=Path("examples/interface-static-route.j2"))
    parser.add_argument("--intent", type=Path, default=Path("examples/intent.json"))
    parser.add_argument("--output", type=Path, help="Save the full device-test evidence JSON.")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(readiness(), indent=2))
        return
    try:
        result = run_lab({"template": args.template.read_text(encoding="utf-8"),
                          "intent": json.loads(args.intent.read_text(encoding="utf-8"))})
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] and not result["cleanup_warnings"] else 1)


if __name__ == "__main__":
    main()
