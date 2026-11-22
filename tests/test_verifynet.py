import json
import os
import random
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from http.server import ThreadingHTTPServer
from app import Handler
from verifynet.benchmark import cases, offline_benchmark
from verifynet.domain import BROKEN_TEMPLATE, GOOD_TEMPLATE, Intent, check_template
from verifynet.pipeline import run_pipeline
from verifynet.providers import OpenAIProvider, ProviderError
from verifynet.retrieval import retrieve
from verifynet import documents


def payload(**kwargs):
    return {"intent": Intent().data(), "mode": "demo", "strategy": "rag_repair", "max_repairs": 2, **kwargs}


class CheckerTests(unittest.TestCase):
    def test_reference_passes_three_distinct_inputs(self):
        result = check_template(GOOD_TEMPLATE, Intent())
        self.assertTrue(result["passed"])
        self.assertEqual(len(set(result["rendered"])), 3)
        self.assertFalse(result["device_tested"])

    def test_broken_gateway_fails_command_structure(self):
        result = check_template(BROKEN_TEMPLATE, Intent())
        self.assertFalse(result["passed"])
        self.assertEqual(result["stages"][-1]["name"], "Command structure")

    def test_valid_syntax_wrong_gateway_fails_intent(self):
        result = check_template(GOOD_TEMPLATE.replace("{{ next_hop }}", "10.10.0.1"), Intent())
        self.assertEqual(result["stages"][-1]["name"], "Intent agreement")
        self.assertFalse(result["passed"])

    def test_hardcoded_first_example_does_not_pass(self):
        fixed = "interface eth1\n ip address 10.10.0.1/30\nexit\nip route 192.168.20.0/24 10.10.0.2"
        result = check_template(fixed, Intent())
        self.assertFalse(result["passed"])
        self.assertTrue(any("Case 2" in e for e in result["errors"]))

    def test_missing_extra_and_duplicate_commands_fail(self):
        for source in [GOOD_TEMPLATE.split("ip route")[0], GOOD_TEMPLATE + "\nrouter ospf", GOOD_TEMPLATE + "\nip route {{ destination_cidr }} {{ next_hop }}", GOOD_TEMPLATE.replace("exit", "")]:
            with self.subTest(source=source):
                self.assertFalse(check_template(source, Intent())["passed"])

    def test_unknown_variables_and_expressions_fail(self):
        for source in ["{{ mystery }}", "{{ interface.upper() }}", "{% for n in range(1000000) %}x{% endfor %}", "{{ interface | upper }}", "{{ cycler.__init__.__globals__ }}"]:
            with self.subTest(source=source):
                result = check_template(source, Intent())
                self.assertFalse(result["passed"])
                self.assertEqual(len(result["stages"]), 1)

    def test_empty_large_and_nontext_templates_fail_cleanly(self):
        for source in ["", "x" * 8001, None, 14]:
            self.assertFalse(check_template(source, Intent())["passed"])

    def test_invalid_contracts_are_rejected(self):
        overrides = [{"next_hop": "10.10.0.1"}, {"next_hop": "10.20.0.2"}, {"next_hop": "10.10.0.3"},
                     {"interface": "eth1\nshutdown"}, {"interface_cidr": "10.10.0.0/30"},
                     {"destination_cidr": "192.168.20.7/24"}, {"destination_cidr": "10.10.0.0/30"},
                     {"interface_cidr": "::1/64"}, {"interface_cidr": "10.10.0.1/32"}]
        for override in overrides:
            with self.subTest(override=override), self.assertRaises(ValueError):
                Intent.from_dict({**Intent().data(), **override})

    def test_parameter_variation(self):
        rng = random.Random(42)
        for index in range(25):
            octet = rng.randint(1, 250)
            intent = Intent(f"uplink{index}", f"10.{octet}.0.1/29", f"172.20.{index}.0/24", f"10.{octet}.0.6")
            self.assertTrue(check_template(GOOD_TEMPLATE, intent)["passed"])

    def test_fixture_regression_expected_verdicts(self):
        result = offline_benchmark()
        self.assertEqual(result["cases"], 100)
        self.assertEqual(result["correct_verdicts"], 100)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        corpus = patch.object(documents, "STORE", Path(isolated.name) / "references.json")
        corpus.start()
        self.addCleanup(corpus.stop)

    def test_demo_is_labeled_and_repairs_real_checker_failure(self):
        result = run_pipeline(payload())
        self.assertFalse(result["first_pass"])
        self.assertTrue(result["final_pass"])
        self.assertEqual(result["repairs"], 1)
        self.assertIn("Scripted", result["notice"])
        self.assertIn("-ip route", result["attempts"][1]["diff"])

    def test_zero_budget_stops_on_failure(self):
        result = run_pipeline(payload(max_repairs=0))
        self.assertFalse(result["final_pass"])
        self.assertEqual(result["repairs"], 0)

    def test_strategies_actually_change_documents_and_retries(self):
        for strategy in ["llm_only", "rag"]:
            result = run_pipeline(payload(strategy=strategy))
            self.assertEqual(len(result["attempts"]), 1)
            self.assertEqual(bool(result["documents"]), strategy == "rag")

    def test_passing_user_candidate_stops_without_model_call(self):
        class NeverCalled:
            def generate(self, *args, **kwargs):
                raise AssertionError("Passing input should not trigger generation")
        result = run_pipeline(payload(template=GOOD_TEMPLATE), NeverCalled())
        self.assertTrue(result["first_pass"])
        self.assertEqual(result["repairs"], 0)

    def test_exhausted_repair_budget_preserves_failure(self):
        class AlwaysBroken:
            def generate(self, *args):
                return {"template": BROKEN_TEMPLATE, "usage": {}, "explanation": "Still broken."}
        result = run_pipeline(payload(max_repairs=3), AlwaysBroken())
        self.assertEqual(len(result["attempts"]), 4)
        self.assertFalse(result["final_pass"])

    def test_provider_error_during_repair_keeps_evidence(self):
        class Unavailable:
            def generate(self, *args):
                raise ProviderError("Provider unavailable.")
        result = run_pipeline(payload(template=BROKEN_TEMPLATE), Unavailable())
        self.assertFalse(result["final_pass"])
        self.assertEqual(result["provider_error"], "Provider unavailable.")
        self.assertEqual(len(result["attempts"]), 1)

    def test_invalid_payloads(self):
        for invalid in [payload(mode="fake"), payload(strategy="anything"), payload(max_repairs=True), payload(max_repairs=9), payload(requirement=""), payload(template=123)]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                run_pipeline(invalid)

    def test_retrieval_returns_source_provenance(self):
        result = retrieve("static route gateway")
        self.assertEqual(result[0]["id"], "frr-static")
        self.assertTrue(result[0]["url"].startswith("https://docs.frrouting.org/"))

    def test_development_and_evaluation_ids_disjoint(self):
        dataset = list(cases())
        dev = {c["id"] for c in dataset if c["split"] == "development"}
        test = {c["id"] for c in dataset if c["split"] == "evaluation"}
        self.assertEqual(len(dev), 40)
        self.assertEqual(len(test), 60)
        self.assertFalse(dev & test)


class ProviderTests(unittest.TestCase):
    def test_missing_configuration_fails_instead_of_using_demo(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ProviderError):
            OpenAIProvider().generate(Intent(), "test", [])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key", "VERIFYNET_MODEL": "test-model"})
    def test_responses_contract_and_citation_filter(self):
        from io import BytesIO
        output = {"template": GOOD_TEMPLATE, "explanation": "Example.", "assumptions": [], "source_ids": ["invented"]}
        body = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}], "usage": {"total_tokens": 50}}
        with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(body).encode())) as mocked:
            result = OpenAIProvider().generate(Intent(), "test", [])
        self.assertEqual(result["source_ids"], [])
        self.assertEqual(result["usage"]["total_tokens"], 50)
        request = mocked.call_args.args[0]
        sent = json.loads(request.data)
        self.assertFalse(sent["store"])
        self.assertTrue(sent["text"]["format"]["strict"])
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key", "VERIFYNET_MODEL": "test-model"})
    def test_refusal_incomplete_and_malformed_responses(self):
        from io import BytesIO
        for body in [{"status": "incomplete"}, {"status": "completed", "output": [{"content": [{"type": "refusal"}]}]}, {"status": "completed", "output": []}]:
            with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(body).encode())), self.assertRaises(ProviderError):
                OpenAIProvider().generate(Intent(), "test", [])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, data=None, headers=None):
        merged = {"Content-Type": "application/json", "X-VerifyNet": "1", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers=merged)
        return urllib.request.urlopen(req, timeout=5)

    def test_status_does_not_expose_secrets(self):
        with self.request("/api/status") as response:
            data = json.load(response)
        self.assertIn("live_available", data)
        self.assertNotIn("OPENAI_API_KEY", data)

    def test_full_demo_over_http(self):
        with self.request("/api/run", payload()) as response:
            result = json.load(response)
        self.assertTrue(result["final_pass"])
        self.assertFalse(result["first_pass"])

    def test_validate_and_benchmark_endpoints(self):
        with self.request("/api/validate", {"intent": Intent().data(), "template": GOOD_TEMPLATE}) as response:
            self.assertTrue(json.load(response)["passed"])
        with self.request("/api/benchmark", {}) as response:
            self.assertEqual(json.load(response)["correct_verdicts"], 100)

    def test_static_files_and_not_found(self):
        for path in ["/", "/style.css", "/app.js"]:
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/../../README.md")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()

    def test_bad_origin_bad_host_and_bad_intent(self):
        for data, headers, code in [(payload(), {"Origin": "https://other.example"}, 403),
                                    (payload(), {"Host": "other.example"}, 403),
                                    ({"intent": {}}, {}, 400)]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/run", data, headers)
            self.assertEqual(error.exception.code, code)
            error.exception.close()


if __name__ == "__main__":
    unittest.main()
