"""Small local run history for research comparison, without storing templates or secrets."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "data" / "run_history.json"
HISTORY_DB = ROOT / "data" / "run_history.sqlite3"
MAX_RUNS = 100
_LOCK = threading.RLock()


def _summary(report, kind="generation"):
    if kind == "router":
        return {"kind": "router", "status": report.get("status"), "passed": bool(report.get("passed")),
                "device_tested": bool(report.get("device_tested")), "verification_level": report.get("verification_level", "not_run"),
                "duration_seconds": report.get("duration_seconds", 0), "checks": sum(1 for check in report.get("checks", []) if check.get("passed")),
                "total_checks": len(report.get("checks", [])), "intent": report.get("intent", {}),
                "source_run_id": report.get("source_run_id"),
                "created_at": report.get("started_at", datetime.now(timezone.utc).isoformat()), "notice": report.get("error") or report.get("scope", "")}
    return {"kind": kind, "mode": report.get("mode", ""), "strategy": report.get("strategy", ""),
            "task_profile": report.get("task_profile", "single_route"),
            "first_pass": bool(report.get("first_pass")), "final_pass": bool(report.get("final_pass")),
            "repairs": int(report.get("repairs", 0)), "attempts": len(report.get("attempts", [])),
            "reference_count": len(report.get("documents", [])), "device_tested": bool(report.get("device_tested")),
            "duration_seconds": report.get("duration_seconds", 0), "intent": report.get("intent", {}),
            "created_at": report.get("created_at", datetime.now(timezone.utc).isoformat()),
            "notice": report.get("notice", ""), "requirement": str(report.get("requirement", ""))[:240]}


def record(report, kind="generation"):
    entry = {"id": "run-" + uuid.uuid4().hex[:16], **_summary(report, kind)}
    with _LOCK:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
        except (OSError, ValueError) as exc:
            raise ValueError("Run history is unreadable; move the local history file aside and try again.") from exc
        if not isinstance(existing, list):
            raise ValueError("Run history must contain a JSON list.")
        temp = HISTORY_PATH.with_name(".run_history.tmp")
        temp.write_text(json.dumps(([entry] + existing)[:MAX_RUNS], indent=2), encoding="utf-8")
        temp.replace(HISTORY_PATH)
        # SQLite is the durable queryable store; JSON remains as a portable compatibility export.
        HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(HISTORY_DB) as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS config_versions (version_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created_at TEXT NOT NULL, task_profile TEXT NOT NULL, template TEXT NOT NULL, config_sha256 TEXT NOT NULL, metadata TEXT NOT NULL)")
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?)", (entry["id"], entry["created_at"], entry["kind"], json.dumps(entry)))
            template = ""
            if kind == "router":
                template = str(report.get("config", ""))
            elif report.get("attempts"):
                template = str(report["attempts"][-1].get("template", ""))
            if template:
                import hashlib
                version_id = "version-" + uuid.uuid4().hex[:16]
                metadata = {"mode": report.get("mode", ""), "strategy": report.get("strategy", ""), "kind": kind}
                db.execute("INSERT INTO config_versions VALUES (?, ?, ?, ?, ?, ?, ?)", (version_id, entry["id"], entry["created_at"], entry.get("task_profile", "single_route"), template, hashlib.sha256(template.encode()).hexdigest(), json.dumps(metadata)))
            db.commit()
    return entry


def list_runs(limit=100):
    if type(limit) is not int or not 1 <= limit <= MAX_RUNS:
        raise ValueError("History limit must be between 1 and 100.")
    with _LOCK:
        if not HISTORY_PATH.exists():
            return []
        try:
            runs = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Run history is unreadable; move the local history file aside and try again.") from exc
        if not isinstance(runs, list):
            raise ValueError("Run history must contain a JSON list.")
        return runs[:limit]


def list_versions(limit=100):
    if type(limit) is not int or not 1 <= limit <= MAX_RUNS:
        raise ValueError("Version limit must be between 1 and 100.")
    with _LOCK:
        if not HISTORY_DB.exists():
            return []
        with sqlite3.connect(HISTORY_DB) as db:
            db.execute("CREATE TABLE IF NOT EXISTS config_versions (version_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created_at TEXT NOT NULL, task_profile TEXT NOT NULL, template TEXT NOT NULL, config_sha256 TEXT NOT NULL, metadata TEXT NOT NULL)")
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT version_id, run_id, created_at, task_profile, template, config_sha256, metadata FROM config_versions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row, metadata=json.loads(row["metadata"])) for row in rows]


def restore_version(version_id):
    if not isinstance(version_id, str) or not version_id.startswith("version-"):
        raise ValueError("Provide a valid configuration version ID.")
    with _LOCK:
        if not HISTORY_DB.exists():
            raise ValueError("No configuration versions are available.")
        with sqlite3.connect(HISTORY_DB) as db:
            db.execute("CREATE TABLE IF NOT EXISTS config_versions (version_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created_at TEXT NOT NULL, task_profile TEXT NOT NULL, template TEXT NOT NULL, config_sha256 TEXT NOT NULL, metadata TEXT NOT NULL)")
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT version_id, run_id, created_at, task_profile, template, config_sha256, metadata FROM config_versions WHERE version_id = ?", (version_id,)).fetchone()
        if row is None:
            raise ValueError("Configuration version was not found.")
        result = dict(row)
        result["metadata"] = json.loads(result["metadata"])
        result["restored_at"] = datetime.now(timezone.utc).isoformat()
        return result
