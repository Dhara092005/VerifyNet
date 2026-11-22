"""Local reference library with bounded imports, provenance, and reversible exclusion."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

STORE = Path(__file__).resolve().parents[1] / "data" / "imported_documents.json"
LOCK = threading.RLock()
MAX_TEXT = 150_000


def _read():
    if not STORE.exists():
        return []
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError()
        return data
    except (ValueError, OSError):
        raise ValueError("The local reference library could not be read. Keep the existing file and restore it from a backup.") from None


def _save(documents):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=STORE.parent, prefix=".documents-", suffix=".tmp", delete=False) as file:
            temporary = file.name
            json.dump(documents, file, ensure_ascii=False, indent=2)
        os.replace(temporary, STORE)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def chunk_document(document, size=1600, overlap=200):
    content = document["content"]
    start, index, result = 0, 1, []
    while start < len(content):
        end = min(len(content), start + size)
        if end < len(content):
            boundary = content.rfind("\n", start + size // 2, end)
            if boundary != -1:
                end = boundary + 1
        excerpt = content[start:end]
        if excerpt.strip():
            result.append({"id": f"{document['id']}:chunk-{index}", "document_id": document["id"],
                           "title": document["title"], "url": document["url"], "text": excerpt,
                           "kind": "Imported reference (not independently verified)", "reviewed": "Not reviewed",
                           "imported_at": document["imported_at"], "sha256": document["sha256"],
                           "start_char": start, "end_char": end,
                           "start_line": content.count("\n", 0, start) + 1,
                           "end_line": content.count("\n", 0, max(start, end - 1)) + 1})
            index += 1
        if end == len(content):
            break
        start = max(start + 1, end - overlap)
    return result


def library():
    with LOCK:
        docs = _read()
        return [{k: v for k, v in doc.items() if k != "content"} | {"characters": len(doc["content"]), "chunks": len(chunk_document(doc))} for doc in docs]


def active_chunks():
    with LOCK:
        return [chunk for doc in _read() if doc["enabled"] for chunk in chunk_document(doc)]


def import_document(payload):
    title, content, url = (payload.get(k, "") for k in ("title", "content", "url"))
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120 or any(ord(c) < 32 for c in title):
        raise ValueError("Give the reference a title of 1–120 characters on one line.")
    if not isinstance(content, str) or not 40 <= len(content.strip()) <= MAX_TEXT:
        raise ValueError("Import between 40 and 150,000 characters of text or Markdown.")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in content):
        raise ValueError("This file contains binary or unsupported control characters. Use UTF-8 text or Markdown.")
    if not isinstance(url, str) or len(url) > 2000:
        raise ValueError("Use a short HTTPS source link, or leave it empty.")
    url = url.strip()
    parsed = urlsplit(url)
    if url and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in url)):
        raise ValueError("Source links must be HTTPS URLs without embedded credentials. The app does not fetch this URL.")
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    digest = hashlib.sha256(content.encode()).hexdigest()
    with LOCK:
        docs = _read()
        existing = next((d for d in docs if d["sha256"] == digest), None)
        if existing:
            return {"duplicate": True, "id": existing["id"], "documents": library()}
        if len(docs) >= 30 or sum(len(d["content"]) for d in docs) + len(content) > 2_000_000:
            raise ValueError("The prototype library limit is 30 documents or 2 million characters.")
        doc = {"id": "import-" + digest[:20], "title": title.strip(), "url": url or None,
               "content": content, "sha256": digest, "enabled": True,
               "imported_at": datetime.now(timezone.utc).isoformat()}
        docs.append(doc)
        _save(docs)
        return {"duplicate": False, "id": doc["id"], "documents": library()}


def set_enabled(payload):
    if not isinstance(payload.get("id"), str) or type(payload.get("enabled")) is not bool:
        raise ValueError("Select a reference and specify whether it is enabled.")
    with LOCK:
        docs = _read()
        doc = next((d for d in docs if d["id"] == payload["id"]), None)
        if doc is None:
            raise ValueError("That reference was not found.")
        doc["enabled"] = payload["enabled"]
        _save(docs)
        return {"documents": library()}
