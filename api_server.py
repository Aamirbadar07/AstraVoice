"""
api_server.py - Flask bridge (port 5000 / Cloud Run port 8080).

Two jobs:
  1. Mint short-lived Live API tokens, so the long-lived GEMINI_API_KEY stays
     on this machine and never reaches the browser.
  2. Serve the calendar tools the browser calls on toolCall messages.

Secrets live here and in token.json (or GOOGLE_TOKEN_JSON). The browser gets neither.
"""

import os
import threading
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from calendar_tool import (
    TOKEN_FILE,
    book_meeting,
    cancel_meeting,
    check_availability,
    find_free_slots,
    propose_change,
    reschedule_meeting,
)

load_dotenv()

# Allowed origins for development and production.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
DEFAULT_ALLOWED_ORIGINS = [
    FRONTEND_URL,
    FRONTEND_URL.replace("localhost", "127.0.0.1"),
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]

# Configurable CORS origins via CORS_ORIGINS (comma-separated), defaults to DEFAULT_ALLOWED_ORIGINS
custom_cors = os.getenv("CORS_ORIGINS", "").strip()
if custom_cors == "*":
    ALLOWED_ORIGINS = "*"
elif custom_cors:
    ALLOWED_ORIGINS = [o.strip() for o in custom_cors.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = DEFAULT_ALLOWED_ORIGINS

# Optional shared secret for the API bridge.
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Ephemeral tokens are a v1beta-only feature.
TOKEN_TTL_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", "30"))
SESSION_START_WINDOW_MINUTES = int(os.getenv("SESSION_START_WINDOW_MINUTES", "2"))


def get_gemini_api_keys() -> list[str]:
    """Retrieve list of Gemini API keys from GEMINI_API_KEYS or GEMINI_API_KEY (supports comma-separated list)."""
    raw = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _safe_int(val, default: int = 0) -> int:
    """Safely cast string/number input to integer without raising ValueError."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


_key_index = 0
_key_lock = threading.Lock()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})


@app.get("/")
def serve_index():
    """Serve the AstraVoice interface directly from the bridge."""
    return send_from_directory(".", "index.html")


@app.get("/session_config.json")
def serve_session_config():
    """Serve the system prompt and tool declarations."""
    return send_from_directory(".", "session_config.json")


@app.get("/health")
@app.get("/api/health")
def api_health():
    """
    Lightweight health check for Cloud Run and monitoring systems.
    Executes in <1ms without third-party network calls or secret exposure.
    """
    keys = get_gemini_api_keys()
    has_calendar = bool(os.getenv("GOOGLE_TOKEN_JSON") or os.path.exists(TOKEN_FILE))
    return jsonify({
        "status": "healthy",
        "ok": True,
        "gemini_key_loaded": bool(keys),
        "gemini_keys_count": len(keys),
        "calendar_configured": has_calendar,
        "bridge_token": bool(BRIDGE_TOKEN),
    }), 200


@app.before_request
def require_bridge_token():
    """Enforce optional BRIDGE_TOKEN header while exempting public assets and health probes."""
    if request.method == "OPTIONS" or not BRIDGE_TOKEN:
        return None
    # Public assets and health endpoints must remain accessible without headers
    if request.path in ("/", "/health", "/api/health", "/session_config.json"):
        return None
    if request.headers.get("X-Bridge-Token") != BRIDGE_TOKEN:
        return jsonify({"result": "Rejected: bad or missing bridge token."}), 401
    return None


# ───────────────────── Live API auth ─────────────────────

def _rfc3339(minutes_ahead: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@app.post("/api/live_token")
def api_live_token():
    """
    Mint a single-use ephemeral token for the browser's Live API WebSocket.
    Supports round-robin rotation and automatic failover across multiple keys.
    """
    keys = get_gemini_api_keys()
    if not keys:
        return jsonify({"error": "GEMINI_API_KEY is not set in .env on the server."}), 500

    global _key_index
    with _key_lock:
        start_idx = _key_index
        _key_index = (_key_index + 1) % len(keys)

    last_error = ""
    for attempt in range(len(keys)):
        idx = (start_idx + attempt) % len(keys)
        curr_key = keys[idx]
        masked = curr_key[:6] + "..." + curr_key[-4:] if len(curr_key) > 10 else "***"
        try:
            resp = requests.post(
                f"{GEMINI_BASE}/auth_tokens",
                headers={
                    "x-goog-api-key": curr_key,
                    "Content-Type": "application/json",
                },
                json={
                    "uses": 1,
                    "expireTime": _rfc3339(TOKEN_TTL_MINUTES),
                    "newSessionExpireTime": _rfc3339(SESSION_START_WINDOW_MINUTES),
                },
                timeout=15,
            )
            if resp.status_code == 200:
                name = (resp.json() or {}).get("name", "")
                if name:
                    print(f"[AstraVoice] Minted ephemeral token using key #{idx + 1} ({masked})")
                    return jsonify({
                        "token": name,
                        "expires_in_minutes": TOKEN_TTL_MINUTES,
                        "key_index": idx,
                        "pool_size": len(keys),
                    })
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            print(f"[AstraVoice] Key #{idx + 1} ({masked}) failed ({resp.status_code}). Trying next key...")
        except requests.RequestException as exc:
            last_error = str(exc)
            print(f"[AstraVoice] Key #{idx + 1} ({masked}) network error: {exc}. Trying next key...")

    return jsonify({"error": f"All {len(keys)} Gemini API key(s) failed. Last error: {last_error}"}), 502


@app.get("/api/live_models")
def api_live_models():
    """List models this key pool can use with the Live API - preview names rotate."""
    keys = get_gemini_api_keys()
    if not keys:
        return jsonify({"error": "GEMINI_API_KEY is not set in .env."}), 500

    for curr_key in keys:
        try:
            resp = requests.get(
                f"{GEMINI_BASE}/models",
                headers={"x-goog-api-key": curr_key},
                timeout=15,
            )
            if resp.status_code == 200:
                live = [
                    m.get("name")
                    for m in resp.json().get("models", [])
                    if "bidiGenerateContent" in (m.get("supportedGenerationMethods") or [])
                ]
                if "models/gemini-3.1-flash-live-preview" not in live:
                    live.insert(0, "models/gemini-3.1-flash-live-preview")
                return jsonify({"live_models": live})
        except requests.RequestException:
            continue

    return jsonify({"live_models": ["models/gemini-3.1-flash-live-preview"]})


# ───────────────────── calendar tools ─────────────────────

@app.post("/api/check_availability")
def api_check_availability():
    data = request.get_json(force=True, silent=True) or {}
    date = str(data.get("date", "")).strip()
    if not date:
        return jsonify({"result": "Error: no date was provided to check."})

    print(f"[AstraVoice] check_availability: {date}")
    result = check_availability(date)
    print(f"[AstraVoice]   -> {result[:140]}")
    return jsonify({"result": result})


@app.post("/api/find_free_slots")
def api_find_free_slots():
    data = request.get_json(force=True, silent=True) or {}
    date = str(data.get("date", "")).strip()
    if not date:
        return jsonify({"result": "Error: no date was provided."})

    duration = _safe_int(data.get("duration_minutes"), 0)
    print(f"[AstraVoice] find_free_slots: {date} (duration: {duration}m)")
    result = find_free_slots(date, duration)
    print(f"[AstraVoice]   -> {result[:140]}")
    return jsonify({"result": result})


@app.post("/api/propose_change")
def api_propose_change():
    """Phase one of every write: describe the change, get a one-time code."""
    data = request.get_json(force=True, silent=True) or {}
    action = str(data.get("action", "")).strip().lower()
    if not action:
        return jsonify({"result": "Error: no action was provided ('book', 'cancel' or 'reschedule')."})

    duration = _safe_int(data.get("duration_minutes"), 0)
    print(f"[AstraVoice] propose_change: {action} {dict(data)}")
    result = propose_change(
        action,
        title=str(data.get("title", "")).strip(),
        date_time=str(data.get("date_time", "")).strip(),
        guest_email=str(data.get("guest_email", "")).strip(),
        duration_minutes=duration,
        event_id=str(data.get("event_id", "")).strip(),
        new_date_time=str(data.get("new_date_time", "")).strip(),
    )
    print(f"[AstraVoice]   -> {result[:140]}")
    return jsonify({"result": result})


# The three write routes take nothing but a confirmation_code. Their arguments
# were frozen when propose_change issued it, so a model that skips the proposal
# step -- or changes its mind about the details afterwards -- cannot write.

@app.post("/api/book_meeting")
def api_book_meeting():
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get("confirmation_code", "")).strip()

    print(f"[AstraVoice] book_meeting: code={code}")
    result = book_meeting(code)
    print(f"[AstraVoice]   -> {result}")
    return jsonify({"result": result})


@app.post("/api/cancel_meeting")
def api_cancel_meeting():
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get("confirmation_code", "")).strip()

    print(f"[AstraVoice] cancel_meeting: code={code}")
    result = cancel_meeting(code)
    print(f"[AstraVoice]   -> {result}")
    return jsonify({"result": result})


@app.post("/api/reschedule_meeting")
def api_reschedule_meeting():
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get("confirmation_code", "")).strip()

    print(f"[AstraVoice] reschedule_meeting: code={code}")
    result = reschedule_meeting(code)
    print(f"[AstraVoice]   -> {result}")
    return jsonify({"result": result})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    keys = get_gemini_api_keys()
    print(f"[AstraVoice] API bridge running on port {port}")
    print(f"[AstraVoice] Allowed origins : {ALLOWED_ORIGINS}")
    print(f"[AstraVoice] Bridge token    : {'enabled' if BRIDGE_TOKEN else 'disabled'}")
    print(f"[AstraVoice] Gemini API keys : {len(keys)} key(s) loaded in rotation pool")
    app.run(host="0.0.0.0", port=port, debug=False)
