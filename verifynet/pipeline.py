import difflib
from datetime import datetime, timezone
import time

from .domain import GOOD_IPV6_TEMPLATE, GOOD_MULTI_TEMPLATE, IPv6Intent, Intent, MultiIntent, OspfIntent, VendorIntent, VlanIntent, check_ipv6_template, check_multi_template, check_ospf_template, check_vendor_template, check_template, check_vlan_template
from .providers import DemoProvider, OpenAIProvider, ProviderError
from .retrieval import retrieve_with_snapshot

STRATEGIES = {"llm_only", "rag", "rag_repair"}


def run_pipeline(payload, provider_override=None):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    task_profile = payload.get("task_profile", "single_route")
    if task_profile not in ("single_route", "multi_route", "ipv6_static", "vlan_static", "ospf", "cisco_ios", "juniper_junos"):
        raise ValueError("Choose a supported task profile.")
    intent = MultiIntent.from_dict(payload.get("intent")) if task_profile == "multi_route" else IPv6Intent.from_dict(payload.get("intent")) if task_profile == "ipv6_static" else VlanIntent.from_dict(payload.get("intent")) if task_profile == "vlan_static" else OspfIntent.from_dict(payload.get("intent")) if task_profile == "ospf" else VendorIntent.from_dict(payload.get("intent")) if task_profile in ("cisco_ios", "juniper_junos") else Intent.from_dict(payload.get("intent"))
    mode = payload.get("mode", "demo")
    strategy = payload.get("strategy", "rag_repair")
    if mode not in ("demo", "live") or strategy not in STRATEGIES:
        raise ValueError("Choose a supported mode and strategy.")
    requirement = payload.get("requirement", "Configure an interface and a static IPv4 route.")
    if not isinstance(requirement, str) or not requirement.strip() or len(requirement) > 2000:
        raise ValueError("Provide a requirement of 1–2,000 characters.")
    budget = payload.get("max_repairs", 2)
    if type(budget) is not int or budget not in range(4):
        raise ValueError("Repair attempts must be between 0 and 3.")
    initial = payload.get("template")
    if initial is not None and (not isinstance(initial, str) or not initial.strip() or len(initial) > 8000):
        raise ValueError("A pasted template must contain 1–8,000 characters.")
    retrieved = retrieve_with_snapshot(requirement + " interface IPv4 static route next hop template") if strategy != "llm_only" else {"documents": [], "snapshot": None}
    docs = retrieved["documents"]
    provider = provider_override or (DemoProvider() if mode == "demo" else OpenAIProvider())
    attempts, start = [], time.monotonic()
    candidate = {"template": initial, "explanation": "User-supplied candidate.", "source_ids": [], "assumptions": [], "provider": "user", "usage": {}} if initial is not None else None
    provider_error = None
    for index in range((budget if strategy == "rag_repair" else 0) + 1):
        if index or candidate is None:
            previous = attempts[-1] if attempts else None
            try:
                candidate = provider.generate(intent, requirement, docs,
                                              previous["template"] if previous else None,
                                              previous["validation"]["errors"] if previous else None)
            except ProviderError as exc:
                if not attempts:
                    raise
                provider_error = str(exc)
                break
        result = check_multi_template(candidate["template"], intent) if task_profile == "multi_route" else check_ipv6_template(candidate["template"], intent) if task_profile == "ipv6_static" else check_vlan_template(candidate["template"], intent) if task_profile == "vlan_static" else check_ospf_template(candidate["template"], intent) if task_profile == "ospf" else check_vendor_template(candidate["template"], intent) if task_profile in ("cisco_ios", "juniper_junos") else check_template(candidate["template"], intent)
        previous_text = attempts[-1]["template"] if attempts else ""
        delta = "\n".join(difflib.unified_diff(previous_text.splitlines(), candidate["template"].splitlines(),
                                             fromfile="before", tofile="after", lineterm="")) if attempts else ""
        attempts.append({**candidate, "number": index + 1, "validation": result, "diff": delta})
        if result["passed"]:
            break
    return {"created_at": datetime.now(timezone.utc).isoformat(), "mode": mode, "strategy": strategy, "task_profile": task_profile,
            "requirement": requirement, "intent": intent.data(), "documents": docs, "retrieval_snapshot": retrieved["snapshot"], "attempts": attempts,
            "first_pass": attempts[0]["validation"]["passed"], "final_pass": attempts[-1]["validation"]["passed"],
            "repairs": len(attempts) - 1, "provider_error": provider_error,
            "duration_seconds": round(time.monotonic() - start, 3), "device_tested": False,
            "notice": "Scripted walkthrough, not measured AI performance." if mode == "demo" else "Real AI responses; local static checks only. No virtual or physical device was tested."}
