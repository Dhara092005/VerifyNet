"""Offline checker fixtures and opt-in live ablations are different experiments."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .domain import GOOD_IPV6_TEMPLATE, GOOD_MULTI_TEMPLATE, GOOD_OSPF_TEMPLATE, GOOD_TEMPLATE, GOOD_VLAN_TEMPLATE, IPv6Intent, Intent, MultiIntent, OspfIntent, VlanIntent, check_ipv6_template, check_multi_template, check_ospf_template, check_template, check_vlan_template
from .pipeline import run_pipeline


def cases():
    prompts = ["Configure a router interface and a static route to the remote network.",
               "Generate a reusable IPv4 uplink and static routing template.",
               "Set the interface address and route remote traffic through the specified gateway.",
               "Prepare a reusable edge-router template for a directly connected next hop."]
    for i in range(100):
        if i < 10:
            yield {"id": f"case-{i + 1:03}", "split": "evaluation", "task_profile": "ipv6_static",
                   "requirement": "Configure IPv6 static routing to a remote prefix.",
                   "intent": IPv6Intent(f"eth{i + 1}", f"2001:db8:{i + 1}::1/64", f"2001:db8:{100 + i}::/64", f"2001:db8:{i + 1}::2").data()}
        elif i < 40:
            yield {"id": f"case-{i + 1:03}", "split": "development" if i < 30 else "evaluation", "task_profile": "single_route",
                   "requirement": prompts[i % len(prompts)],
                   "intent": Intent(f"eth{i % 8 + 1}", f"10.{i + 1}.0.1/30", f"172.{16 + i % 16}.{i}.0/24", f"10.{i + 1}.0.2").data()}
        elif i < 60:
            base = i - 40
            yield {"id": f"case-{i + 1:03}", "split": "evaluation", "task_profile": "multi_route",
                   "requirement": "Configure two router interfaces and static routes to two remote networks.",
                   "intent": MultiIntent.from_dict({"interfaces": [{"name": f"eth{base % 6 + 1}", "cidr": f"10.{base + 30}.0.1/30"}, {"name": f"eth{base % 6 + 7}", "cidr": f"10.{base + 60}.0.1/30"}], "routes": [{"destination": f"172.{16 + base % 16}.0.0/24", "next_hop": f"10.{base + 30}.0.2"}, {"destination": f"172.{32 + base % 16}.0.0/24", "next_hop": f"10.{base + 60}.0.2"}]}).data()}
        elif i < 80:
            base = i - 60
            yield {"id": f"case-{i + 1:03}", "split": "development" if base < 10 else "evaluation", "task_profile": "vlan_static",
                   "requirement": "Configure an 802.1Q VLAN interface and a static route.",
                   "intent": VlanIntent(f"eth{base % 6 + 1}", str(100 + base), f"10.{100 + base}.0.1/30", f"192.168.{100 + base}.0/24", f"10.{100 + base}.0.2").data()}
        else:
            base = i - 80
            yield {"id": f"case-{i + 1:03}", "split": "development" if base < 10 else "evaluation", "task_profile": "ospf",
                   "requirement": "Configure OSPF with the requested router ID, area, and advertised network.",
                   "intent": OspfIntent(f"{base + 1}.{base + 1}.{base + 1}.{base + 1}", "0.0.0.0", f"10.{base + 1}.0.0/30").data()}


def offline_benchmark():
    variants = [
        ("reference", GOOD_TEMPLATE, True),
        ("unknown variable", GOOD_TEMPLATE.replace("next_hop", "gateway_typo"), False),
        ("gateway with prefix", GOOD_TEMPLATE.replace("{{ next_hop }}", "{{ interface_cidr }}"), False),
        ("missing route", GOOD_TEMPLATE.split("ip route")[0], False),
        ("wrong fixed gateway", GOOD_TEMPLATE.replace("{{ next_hop }}", "203.0.113.254"), False),
        ("unexpected extra command", GOOD_TEMPLATE + "\nrouter ospf", False),
    ]
    results = []
    for case in cases():
        index = int(case["id"].split("-")[-1]) - 1
        if case["task_profile"] == "multi_route":
            multi_variants = [("reference", GOOD_MULTI_TEMPLATE, True),
                              ("gateway with prefix", GOOD_MULTI_TEMPLATE.replace("{{ route_2_next_hop }}", "{{ interface_2_cidr }}"), False),
                              ("missing route", GOOD_MULTI_TEMPLATE.split("ip route {{ route_2_destination }}")[0], False),
                              ("wrong fixed gateway", GOOD_MULTI_TEMPLATE.replace("{{ route_2_next_hop }}", "203.0.113.254"), False),
                              ("unexpected extra command", GOOD_MULTI_TEMPLATE + "\nrouter ospf", False)]
            name, candidate, expected = multi_variants[index % len(multi_variants)]
            checked = check_multi_template(candidate, MultiIntent.from_dict(case["intent"]))
        elif case["task_profile"] == "ipv6_static":
            ipv6_variants = [("reference", GOOD_IPV6_TEMPLATE, True), ("wrong gateway", GOOD_IPV6_TEMPLATE.replace("{{ next_hop }}", "{{ interface_cidr }}"), False), ("missing route", GOOD_IPV6_TEMPLATE.split("ipv6 route")[0], False), ("wrong fixed gateway", GOOD_IPV6_TEMPLATE.replace("{{ next_hop }}", "2001:db8:ffff::1"), False)]
            name, candidate, expected = ipv6_variants[index % len(ipv6_variants)]; checked = check_ipv6_template(candidate, IPv6Intent.from_dict(case["intent"]))
        elif case["task_profile"] == "vlan_static":
            vlan_variants = [("reference", GOOD_VLAN_TEMPLATE, True), ("wrong vlan", GOOD_VLAN_TEMPLATE.replace("{{ vlan_id }}", "{{ interface_cidr }}"), False), ("missing encapsulation", GOOD_VLAN_TEMPLATE.replace(" encapsulation dot1q {{ vlan_id }}\n", ""), False), ("wrong gateway", GOOD_VLAN_TEMPLATE.replace("{{ next_hop }}", "203.0.113.254"), False)]
            name, candidate, expected = vlan_variants[index % len(vlan_variants)]; checked = check_vlan_template(candidate, VlanIntent.from_dict(case["intent"]))
        elif case["task_profile"] == "ospf":
            ospf_variants = [("reference", GOOD_OSPF_TEMPLATE, True), ("wrong area", GOOD_OSPF_TEMPLATE.replace("{{ area }}", "{{ router_id }}"), False), ("missing network", GOOD_OSPF_TEMPLATE.replace(" network {{ network_cidr }} area {{ area }}\n", ""), False), ("extra command", GOOD_OSPF_TEMPLATE + "\nrouter bgp 65000", False)]
            name, candidate, expected = ospf_variants[index % len(ospf_variants)]; checked = check_ospf_template(candidate, OspfIntent.from_dict(case["intent"]))
        else:
            name, candidate, expected = variants[index % len(variants)]
            checked = check_template(candidate, Intent.from_dict(case["intent"]))
        results.append({"id": case["id"], "fault": name, "expected_pass": expected,
                        "actual_pass": checked["passed"], "correct_verdict": checked["passed"] == expected,
                        "errors": checked["errors"]})
    return {"kind": "offline_checker_regression", "created_at": datetime.now(timezone.utc).isoformat(),
            "notice": "Synthetic checker fixtures across IPv4, IPv6, VLAN, and OSPF profiles; no model was called.",
            "cases": len(results), "correct_verdicts": sum(r["correct_verdict"] for r in results), "results": results}


def live_ablation(limit=3, split="evaluation"):
    """Run a bounded three-strategy comparison against the configured live provider."""
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Live benchmark limit must be between 1 and 5.")
    if split not in ("development", "evaluation"):
        raise ValueError("Choose development or evaluation split.")
    results = []
    selected = [case for case in cases() if case["split"] == split][:limit]
    for case in selected:
        for strategy in ("llm_only", "rag", "rag_repair"):
            result = run_pipeline({**case, "mode": "live", "strategy": strategy, "max_repairs": 2})
            results.append({"case_id": case["id"], **result})
    metrics = {}
    for strategy in ("llm_only", "rag", "rag_repair"):
        rows = [row for row in results if row["strategy"] == strategy]
        metrics[strategy] = {"runs": len(rows),
                             "first_pass_rate": round(sum(row["first_pass"] for row in rows) / len(rows), 4),
                             "final_pass_rate": round(sum(row["final_pass"] for row in rows) / len(rows), 4),
                             "repairs": sum(row["repairs"] for row in rows),
                             "average_duration_seconds": round(sum(row["duration_seconds"] for row in rows) / len(rows), 4),
                             "total_tokens": sum(attempt["usage"].get("total_tokens", 0) for row in rows for attempt in row["attempts"])}
    return {"kind": "live_ai_ablation", "split": split, "limit": limit,
            "created_at": datetime.now(timezone.utc).isoformat(), "metrics": metrics,
            "results": results,
            "notice": "Small bounded comparison. Inputs share a narrow task structure; results are local static checks unless Router Lab is run separately."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Call the configured AI API; consumes credits.")
    parser.add_argument("--split", choices=["development", "evaluation"], default="evaluation")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", default="reports/benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.limit <= (5 if args.live else 30):
        parser.error("--limit must be between 1 and 5 for live runs, or 1 and 30 for offline runs")
    if args.live:
        report = live_ablation(args.limit, args.split)
    else:
        report = offline_benchmark()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {target.resolve()}")


if __name__ == "__main__":
    main()
