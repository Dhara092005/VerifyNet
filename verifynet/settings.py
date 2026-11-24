"""Optional session credentials; never persist them to disk or return them to the UI."""
from dataclasses import dataclass
import json
import os
import re
import threading
import contextvars
import urllib.error
import urllib.parse
import urllib.request

LOCK = threading.RLock()
_session = None
_sessions = {}
_request_session = contextvars.ContextVar("verifynet_session", default=None)


def set_request_session(session_id):
    """Bind the current request to an isolated in-memory credential session."""
    return _request_session.set(session_id or None)


def reset_request_session(token):
    _request_session.reset(token)


def _current_session():
    session_id = _request_session.get()
    if session_id:
        return _sessions.get(session_id)
    return _session


@dataclass(frozen=True, repr=False)
class Credentials:
    api_key: str
    model: str
    verified: bool = False


def credentials():
    with LOCK:
        current = _current_session()
        if current is not None:
            return current
        return Credentials(os.environ.get("OPENAI_API_KEY", ""), os.environ.get("VERIFYNET_MODEL", ""))


def connection_status():
    current = credentials()
    return {"configured": bool(current.api_key and current.model), "model": current.model,
            "access_verified": current.verified,
            "source": "session" if _session is not None else "environment",
            "generation_verified": False}


def connect(payload):
    global _session
    key, model = payload.get("api_key", ""), payload.get("model", "")
    if not isinstance(key, str) or not re.fullmatch(r"[!-~]{16,512}", key.strip()):
        raise ValueError("Enter a valid API key without spaces or line breaks.")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", model.strip()):
        raise ValueError("Enter the model ID from your API account.")
    key, model = key.strip(), model.strip()
    request = urllib.request.Request("https://api.openai.com/v1/models/" + urllib.parse.quote(model, safe=""),
                                     headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ValueError(f"Could not verify model access (HTTP {code}). Check the key and exact model ID. Your previous connection was kept.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ValueError("Could not verify the AI connection. Check your network and try again. Your previous connection was kept.") from None
    if not isinstance(data, dict) or data.get("id") != model:
        raise ValueError("The provider did not confirm that model. Your previous connection was kept.")
    with LOCK:
        session = Credentials(key, model, verified=True)
        session_id = _request_session.get()
        if session_id:
            _sessions[session_id] = session
        else:
            _session = session
    return connection_status()


def disconnect():
    global _session
    with LOCK:
        session_id = _request_session.get()
        if session_id:
            _sessions.pop(session_id, None)
        else:
            # Explicitly disable environment fallback for this running server as well.
            _session = Credentials("", "")
    return connection_status()
