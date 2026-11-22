from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app import Handler, LocalServer
from verifynet import documents, settings
from verifynet.domain import Intent
from verifynet.pipeline import run_pipeline
from verifynet.retrieval import retrieve, retrieve_with_snapshot
from verifynet.providers import live_available

REFERENCE = "Campus uplink guide\nA gateway marker named quasarhop identifies the next hop for this static route example.\nUse a host address without a prefix as the route gateway.\n"


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Path(self.directory.name) / "references.json"
        self.patch = patch.object(documents, "STORE", self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def add(self, **extra):
        return documents.import_document({"title": "Campus guide", "content": REFERENCE, **extra})

    def test_import_search_and_source_location(self):
        result = self.add(url="https://example.org/guide")
        selected = retrieve("quasarhop")
        self.assertEqual(selected[0]["document_id"], result["id"])
        self.assertEqual(selected[0]["url"], "https://example.org/guide")
        self.assertEqual(selected[0]["start_line"], 1)
        self.assertIn("not independently verified", selected[0]["kind"])
        self.assertEqual(len(selected[0]["sha256"]), 64)

    def test_chunks_are_bounded_exact_slices_with_coverage(self):
        text = "\n".join(f"Line {i}: interface routing and next hop details." for i in range(150))
        self.add(content=text)
        doc = json.loads(self.store.read_text(encoding="utf-8"))[0]
        chunks = documents.active_chunks()
        self.assertGreater(len(chunks), 1)
        covered = set()
        for chunk in chunks:
            self.assertLessEqual(len(chunk["text"]), 1600)
            self.assertEqual(doc["content"][chunk["start_char"]:chunk["end_char"]], chunk["text"])
            self.assertEqual(chunk["start_line"], doc["content"].count("\n", 0, chunk["start_char"]) + 1)
            covered.update(range(chunk["start_char"], chunk["end_char"]))
        self.assertEqual(len(covered), len(doc["content"]))

    def test_duplicate_content_is_not_added_or_reenabled(self):
        first = self.add()
        documents.set_enabled({"id": first["id"], "enabled": False})
        second = self.add(title="Different title")
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(documents.library()), 1)
        self.assertFalse(documents.library()[0]["enabled"])

    def test_disable_preserves_file_and_changes_snapshot(self):
        first = self.add()
        before = retrieve_with_snapshot("quasarhop")
        documents.set_enabled({"id": first["id"], "enabled": False})
        after = retrieve_with_snapshot("quasarhop")
        self.assertTrue(before["documents"])
        self.assertFalse(after["documents"])
        self.assertNotEqual(before["snapshot"]["sha256"], after["snapshot"]["sha256"])
        self.assertEqual(len(json.loads(self.store.read_text(encoding="utf-8"))), 1)

    def test_same_library_has_stable_fingerprint(self):
        self.add()
        self.assertEqual(retrieve_with_snapshot("route")["snapshot"]["sha256"], retrieve_with_snapshot("interface")["snapshot"]["sha256"])

    def test_unsafe_links_binary_and_oversized_text_rejected(self):
        for fields in [{"url": "javascript:alert(1)"}, {"url": "http://example.org"}, {"url": "https://key:secret@example.org"},
                       {"content": "short"}, {"content": "a" * 150001}, {"content": REFERENCE + "\x00"}, {"title": "\n"}]:
            with self.subTest(fields=list(fields)), self.assertRaises(ValueError):
                self.add(**fields)
        self.assertFalse(self.store.exists())

    def test_bad_library_is_not_silently_overwritten(self):
        self.store.write_text("bad-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.add()
        self.assertEqual(self.store.read_text(encoding="utf-8"), "bad-json")

    def test_one_document_does_not_take_every_retrieval_slot(self):
        self.add(content=("quasarhop interface static route gateway\n" * 300))
        results = retrieve("quasarhop interface static route gateway", limit=5)
        self.assertLessEqual(sum("document_id" in d for d in results), 2)
        self.assertGreater(len(results), 2)

    def test_pipeline_records_corpus_snapshot_and_baseline_has_none(self):
        self.add()
        request = {"intent": Intent().data(), "mode": "demo", "max_repairs": 1}
        result = run_pipeline(request)
        self.assertEqual(result["retrieval_snapshot"]["method"], "BM25")
        baseline = run_pipeline({**request, "strategy": "llm_only"})
        self.assertIsNone(baseline["retrieval_snapshot"])
        self.assertEqual(baseline["documents"], [])


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.session = patch.object(settings, "_session", None)
        self.session.start()
        self.addCleanup(self.session.stop)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_success_keeps_secret_out_of_status(self):
        with patch("urllib.request.urlopen", return_value=BytesIO(b'{"id":"test-model"}')) as request:
            result = settings.connect({"api_key": "test-secret-not-a-real-key", "model": "test-model"})
        self.assertTrue(result["configured"])
        self.assertTrue(result["access_verified"])
        self.assertFalse(result["generation_verified"])
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertNotIn("test-secret", repr(settings.credentials()))
        self.assertTrue(live_available())
        self.assertEqual(request.call_args.args[0].full_url, "https://api.openai.com/v1/models/test-model")

    def test_failed_reconnect_preserves_previous_connection(self):
        settings._session = settings.Credentials("previous-test-secret", "previous-model", True)
        error = urllib.error.HTTPError("https://api.openai.com", 401, "unauthorized", {}, BytesIO(b"secret body"))
        with patch("urllib.request.urlopen", side_effect=error), self.assertRaises(ValueError) as result:
            settings.connect({"api_key": "invalid-test-secret", "model": "test-model"})
        self.assertNotIn("secret", str(result.exception))
        self.assertEqual(settings.credentials().model, "previous-model")

    def test_disconnect_does_not_fall_back_to_environment(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "environment-secret", "VERIFYNET_MODEL": "env-model"}):
            self.assertTrue(live_available())
            self.assertFalse(settings.disconnect()["configured"])
            self.assertFalse(live_available())

    def test_model_mismatch_does_not_save_key(self):
        with patch("urllib.request.urlopen", return_value=BytesIO(b'{"id":"different-model"}')), self.assertRaises(ValueError):
            settings.connect({"api_key": "invalid-test-secret", "model": "test-model"})
        self.assertFalse(live_available())

    def test_invalid_fields_never_make_a_request(self):
        for fields in [{"api_key": "short", "model": "test-model"}, {"api_key": "invalid-test-secret", "model": "a/../../b"}]:
            with patch("urllib.request.urlopen") as mocked, self.assertRaises(ValueError):
                settings.connect(fields)
            mocked.assert_not_called()


class LibraryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store_patch = patch.object(documents, "STORE", Path(self.directory.name) / "library.json")
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.session_patch = patch.object(settings, "_session", None)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, **headers):
        request = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                                         headers={"Content-Type": "application/json", "X-VerifyNet": "1", **headers})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_import_search_toggle_and_list_over_http(self):
        added = self.request("/api/documents/import", {"title": "Test reference", "content": REFERENCE})
        self.assertTrue(self.request("/api/retrieve", {"query": "quasarhop"})["documents"])
        self.request("/api/documents/state", {"id": added["id"], "enabled": False})
        self.assertFalse(self.request("/api/retrieve", {"query": "quasarhop"})["documents"])
        self.assertEqual(len(self.request("/api/library")["documents"]), 1)

    def test_import_larger_than_old_request_limit(self):
        data = self.request("/api/documents/import", {"title": "Larger reference", "content": REFERENCE * 150})
        self.assertGreater(data["documents"][0]["characters"], 20000)

    def test_setup_endpoint_never_echoes_key(self):
        with patch("verifynet.settings.urllib.request.urlopen", return_value=BytesIO(b'{"id":"test-model"}')):
            # Use http.client here so mocking the provider transport does not mock the test client.
            import http.client
            conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            conn.request("POST", "/api/connection", json.dumps({"api_key": "test-secret-not-a-real-key", "model": "test-model"}), {"Content-Type": "application/json", "X-VerifyNet": "1"})
            response = conn.getresponse()
            body = response.read().decode()
            conn.close()
        self.assertEqual(response.status, 200)
        self.assertNotIn("test-secret", body)
        self.assertEqual(self.request("/api/status")["connection"]["model"], "test-model")
        self.assertFalse(self.request("/api/disconnect", {})["configured"])

    def test_cross_origin_cannot_set_credentials(self):
        with self.assertRaises(urllib.error.HTTPError) as result:
            self.request("/api/connection", {"api_key": "test-secret-not-a-real-key", "model": "test-model"}, Origin="https://other.example")
        self.assertEqual(result.exception.code, 403)
        result.exception.close()

    def test_second_server_cannot_share_the_same_port(self):
        first = LocalServer(("127.0.0.1", 0), Handler)
        try:
            with self.assertRaises(OSError):
                LocalServer(first.server_address, Handler)
        finally:
            first.server_close()


if __name__ == "__main__":
    unittest.main()
