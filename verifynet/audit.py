"""Small privacy-preserving audit trail for protected deployments."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / "data" / "audit.jsonl"
_LOCK = threading.RLock()


def _fingerprint(value):
    return hashlib.sha256((value or "").encode()).hexdigest()[:16]


def event(action, path, session_id=None, outcome="ok", detail=""):
    row = {"created_at": datetime.now(timezone.utc).isoformat(), "action": action,
           "path": path, "session": _fingerprint(session_id), "outcome": outcome,
           "detail": str(detail)[:240]}
    with _LOCK:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def recent(limit=100):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Audit limit must be between 1 and 500.")
    with _LOCK:
        if not AUDIT_PATH.exists():
            return []
        rows = []
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                continue
        return list(reversed(rows))
