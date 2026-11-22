"""Self-contained, thesis-friendly HTML evidence export."""
from html import escape
import json


def html_report(report):
    if not isinstance(report, dict):
        raise ValueError("Expected a report object.")
    title = escape(str(report.get("task_profile", "VerifyNet")))
    sections = [f"<h1>VerifyNet evidence report</h1><p><strong>Profile:</strong> {title}</p>"]
    for key in ("created_at", "mode", "strategy", "first_pass", "final_pass", "repairs", "duration_seconds", "device_tested"):
        if key in report:
            sections.append(f"<p><strong>{escape(key.replace('_',' ').title())}:</strong> {escape(str(report[key]))}</p>")
    sections.append("<h2>Intent</h2><pre>" + escape(json.dumps(report.get("intent", {}), indent=2)) + "</pre>")
    for attempt in report.get("attempts", []):
        sections.append("<h2>Attempt " + escape(str(attempt.get("number", "?"))) + "</h2>")
        sections.append("<h3>Generated configuration</h3><pre>" + escape(str(attempt.get("template", ""))) + "</pre>")
        sections.append("<h3>Validation</h3><pre>" + escape(json.dumps(attempt.get("validation", {}), indent=2)) + "</pre>")
        sections.append("<h3>References</h3><pre>" + escape(json.dumps(attempt.get("source_ids", []), indent=2)) + "</pre>")
    if report.get("router_report"):
        sections.append("<h2>Virtual-router evidence</h2><pre>" + escape(json.dumps(report["router_report"], indent=2)) + "</pre>")
    return "<!doctype html><html><head><meta charset='utf-8'><title>VerifyNet evidence</title><style>body{font:15px system-ui;max-width:980px;margin:40px auto;color:#17202a}pre{background:#f4f6f8;padding:16px;overflow:auto;border-radius:8px}h1,h2{color:#125f68}</style></head><body>" + "".join(sections) + "</body></html>"
