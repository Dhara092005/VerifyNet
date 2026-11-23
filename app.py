"""Local-only VerifyNet workbench. Run: python app.py"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import threading
import tempfile
from urllib.parse import urlparse
import webbrowser

from verifynet.benchmark import live_ablation, offline_benchmark
from verifynet.domain import BROKEN_IPV6_TEMPLATE, BROKEN_TEMPLATE, BROKEN_VLAN_TEMPLATE, BROKEN_OSPF_TEMPLATE, GOOD_IPV6_TEMPLATE, GOOD_MULTI_TEMPLATE, GOOD_OSPF_TEMPLATE, GOOD_TEMPLATE, GOOD_VLAN_TEMPLATE, IPv6Intent, Intent, MultiIntent, OspfIntent, VendorIntent, VlanIntent, check_ipv6_template, check_multi_template, check_ospf_template, check_vendor_template, check_template, check_vlan_template
from verifynet.pipeline import run_pipeline
from verifynet.providers import ProviderError, live_available
from verifynet.retrieval import DATA, retrieve, retrieve_with_snapshot
from verifynet.documents import import_document, library, set_enabled
from verifynet.settings import connect, connection_status, disconnect
from verifynet.router_lab import readiness, run_lab
from verifynet.history import list_runs, record
from verifynet.feedback import add_feedback, feedback_summary
from verifynet.reports import html_report
from verifynet.pdf_report import pdf_report

ROOT = Path(__file__).resolve().parent
RUN_LOCK = threading.Lock()


class LocalServer(ThreadingHTTPServer):
    # Windows otherwise permits competing development servers to share this port.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep prompts, templates, and credentials out of access logs.
        pass

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        remote_mode = os.environ.get("VERIFYNET_ALLOW_REMOTE", "0").lower() in {"1", "true", "yes"}
        if not remote_mode and self.headers.get("Host") not in allowed:
            self.send(403, {"error": "This workbench accepts local requests only."})
            return False
        origin = self.headers.get("Origin")
        if not remote_mode and origin and origin not in {f"http://{host}" for host in allowed}:
            self.send(403, {"error": "Cross-origin requests are not allowed."})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            self.send(200, {"live_available": live_available(), "intent": Intent().data(),
                            "connection": connection_status(), "version": "0.3",
                            "broken_template": BROKEN_TEMPLATE, "reference_template": GOOD_TEMPLATE,
                            "multi_intent": {"interfaces": [{"name": "eth1", "cidr": "10.10.0.1/30"}, {"name": "eth2", "cidr": "10.20.0.1/30"}], "routes": [{"destination": "192.168.20.0/24", "next_hop": "10.10.0.2"}, {"destination": "192.168.30.0/24", "next_hop": "10.20.0.2"}]},
                            "multi_template": GOOD_MULTI_TEMPLATE, "ipv6_intent": IPv6Intent().data(),
                            "ipv6_template": GOOD_IPV6_TEMPLATE, "ipv6_broken_template": BROKEN_IPV6_TEMPLATE,
                            "vlan_intent": VlanIntent().data(), "vlan_template": GOOD_VLAN_TEMPLATE, "vlan_broken_template": BROKEN_VLAN_TEMPLATE,
                            "ospf_intent": OspfIntent().data(), "ospf_template": GOOD_OSPF_TEMPLATE, "ospf_broken_template": BROKEN_OSPF_TEMPLATE,
                            "documents": retrieve("interface IPv4 static route next hop template")})
            return
        if path == "/api/library":
            self.send(200, {"documents": library(), "built_in": json.loads(DATA.read_text(encoding="utf-8"))})
            return
        if path == "/api/router/status":
            self.send(200, readiness())
            return
        if path == "/api/history":
            self.send(200, {"runs": list_runs()})
            return
        if path == "/api/feedback":
            self.send(200, {"summary": feedback_summary()})
            return
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8"),
                 "/library.css": ("library.css", "text/css; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/README.md": ("README.md", "text/markdown; charset=utf-8")}
        if path not in files:
            self.send(404, {"error": "Not found."})
            return
        name, mime = files[path]
        file_path = ROOT / "README.md" if name == "README.md" else ROOT / "web" / name
        self.send(200, file_path.read_bytes(), mime)

    def do_POST(self):
        # Consume bounded bodies before rejection so Windows can deliver the HTTP
        # error instead of resetting a connection with unread incoming bytes.
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            maximum = 1_000_000 if path == "/api/documents/import" else 20000
            if not 0 < length <= maximum:
                raise ValueError(f"Request must be between 1 and {maximum:,} bytes.")
            self.connection.settimeout(15)
            raw = self.rfile.read(length)
        except (ValueError, TimeoutError) as exc:
            self.send(400, {"error": str(exc)})
            return
        if not self.local_request():
            return
        if self.headers.get("X-VerifyNet") != "1" or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.send(415, {"error": "Use the local workbench to submit JSON requests."})
            return
        if path not in ("/api/run", "/api/validate", "/api/benchmark", "/api/live-benchmark", "/api/feedback", "/api/documents/import", "/api/documents/state", "/api/retrieve", "/api/connection", "/api/disconnect", "/api/router/run", "/api/report/html", "/api/report/pdf"):
            self.send(404, {"error": "Not found."})
            return
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
        except (ValueError, UnicodeDecodeError) as exc:
            self.send(400, {"error": str(exc)})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self.send(429, {"error": "Another run is in progress. Wait for it to finish."})
            return
        try:
            if path == "/api/run":
                result = run_pipeline(payload)
                result["history_id"] = record(result)["id"]
            elif path == "/api/validate":
                if payload.get("task_profile", "single_route") == "multi_route":
                    result = check_multi_template(payload.get("template"), MultiIntent.from_dict(payload.get("intent")))
                elif payload.get("task_profile") == "ipv6_static":
                    result = check_ipv6_template(payload.get("template"), IPv6Intent.from_dict(payload.get("intent")))
                elif payload.get("task_profile") == "vlan_static":
                    result = check_vlan_template(payload.get("template"), VlanIntent.from_dict(payload.get("intent")))
                elif payload.get("task_profile") == "ospf":
                    result = check_ospf_template(payload.get("template"), OspfIntent.from_dict(payload.get("intent")))
                elif payload.get("task_profile") in ("cisco_ios", "juniper_junos"):
                    result = check_vendor_template(payload.get("template"), VendorIntent.from_dict(payload.get("intent")))
                else:
                    result = check_template(payload.get("template"), Intent.from_dict(payload.get("intent")))
            elif path == "/api/benchmark":
                result = offline_benchmark()
            elif path == "/api/live-benchmark":
                result = live_ablation(payload.get("limit", 3), payload.get("split", "evaluation"))
            elif path == "/api/documents/import":
                result = import_document(payload)
            elif path == "/api/documents/state":
                result = set_enabled(payload)
            elif path == "/api/retrieve":
                query = payload.get("query")
                if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
                    raise ValueError("Enter a search query of 1–2,000 characters.")
                result = retrieve_with_snapshot(query, limit=5)
            elif path == "/api/connection":
                result = connect(payload)
            elif path == "/api/router/run":
                result = run_lab(payload)
                result["history_id"] = record(result, "router")["id"]
            elif path == "/api/feedback":
                result = add_feedback(payload)
            elif path == "/api/report/html":
                self.send(200, html_report(payload.get("report", payload)), "text/html; charset=utf-8")
                return
            elif path == "/api/report/pdf":
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
                    target = Path(temp.name)
                try:
                    pdf_report(payload.get("report", payload), target)
                    self.send(200, target.read_bytes(), "application/pdf")
                finally:
                    target.unlink(missing_ok=True)
                return
            else:
                result = disconnect()
            self.send(200, result)
        except ValueError as exc:
            self.send(400, {"error": str(exc)})
        except ProviderError as exc:
            self.send(502, {"error": str(exc)})
        except Exception:
            self.send(500, {"error": "An unexpected error interrupted the run. See the test suite and README for troubleshooting."})
        finally:
            RUN_LOCK.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("VERIFYNET_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--open", action="store_true", help="Open the workbench in your browser.")
    args = parser.parse_args()
    try:
        server = LocalServer((args.host, args.port), Handler)
    except OSError:
        parser.exit(1, f"Could not start on port {args.port}. Close the existing server or choose another --port.\n")
    print(f"VerifyNet is ready at http://127.0.0.1:{args.port}", flush=True)
    print("Demo is local and scripted. Live AI is " + ("configured." if live_available() else "not configured."), flush=True)
    if args.open:
        threading.Timer(0.7, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
