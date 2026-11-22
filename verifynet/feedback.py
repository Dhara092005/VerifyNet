"""Local human-review labels for generated configuration evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid

ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_PATH = ROOT / "data" / "human_feedback.json"
MAX_FEEDBACK = 100
ALLOWED = {"correct", "partially_correct", "incorrect", "unsafe"}
_LOCK = threading.RLock()


def add_feedback(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a feedback object.")
    run_id = payload.get("run_id")
    verdict = payload.get("verdict")
    note = payload.get("note", "")
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 80 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in run_id):
        raise ValueError("Provide a valid run identifier.")
    if verdict not in ALLOWED:
        raise ValueError("Choose correct, partially correct, incorrect, or unsafe.")
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError("Review notes must be at most 1,000 characters.")
    entry = {"id": "feedback-" + uuid.uuid4().hex[:16], "run_id": run_id, "verdict": verdict,
             "note": note.strip(), "created_at": datetime.now(timezone.utc).isoformat()}
    with _LOCK:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8")) if FEEDBACK_PATH.exists() else []
        except (OSError, ValueError) as exc:
            raise ValueError("Human-feedback storage is unreadable.") from exc
        if not isinstance(existing, list):
            raise ValueError("Human-feedback storage must contain a JSON list.")
        temp = FEEDBACK_PATH.with_name(".human_feedback.tmp")
        temp.write_text(json.dumps(([entry] + existing)[:MAX_FEEDBACK], indent=2), encoding="utf-8")
        temp.replace(FEEDBACK_PATH)
    return entry


def feedback_summary():
    with _LOCK:
        if not FEEDBACK_PATH.exists():
            return {verdict: 0 for verdict in sorted(ALLOWED)}
        try:
            rows = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Human-feedback storage is unreadable.") from exc
        if not isinstance(rows, list):
            raise ValueError("Human-feedback storage must contain a JSON list.")
        return {verdict: sum(row.get("verdict") == verdict for row in rows) for verdict in sorted(ALLOWED)}
