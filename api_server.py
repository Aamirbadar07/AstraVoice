"""
api_server.py - Flask bridge (port 5000).

Two jobs:
  1. Mint short-lived Live API tokens, so the long-lived GEMINI_API_KEY stays
     on this machine and never reaches the browser.
  2. Serve the calendar tools the browser calls on toolCall messages.

Secrets live here and in token.json. The browser gets neither.
"""

import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from calendar_tool import (
    book_meeting,
    cancel_meeting,
    check_availability,
    find_free_slots,
    propose_change,
    reschedule_meeting,
)

load_dotenv()

# Only the page we serve may call this bridge. Without this, any website open
# in the same browser could POST here and write to the host's real calendar.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
ALLOWED_ORIGINS = [FRONTEND_URL, FRONTEND_URL.replace("localhost", "127.0.0.1")]

# Optional second lock: set BRIDGE_TOKEN in .env AND in index.html to require it.
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Ephemeral tokens are a v1beta-only feature.
TOKEN_TTL_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", "30"))
SESSION_START_WINDOW_MINUTES = int(os.getenv("SESSION_START_WINDOW_MINUTES", "2"))

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})


@app.before_request
def require_bridge_token():
    if request.method == "OPTIONS" or not BRIDGE_TOKEN:
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

    Deliberately sent WITHOUT liveConnectConstraints: a constrained token
    routes the client to BidiGenerateContentConstrained, which is reported to
    ignore the setup message's systemInstruction -- and ours carries the
    current date and timezone, so losing it breaks every relative date.
    """
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not set in .env on the server."}), 500

    try:
        resp = requests.post(
            f"{GEMINI_BASE}/auth_tokens",
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "uses": 1,
                "expireTime": _rfc3339(TOKEN_TTL_MINUTES),
                "newSessionExpireTime": _rfc3339(SESSION_START_WINDOW_MINUTES),
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"Could not reach the Gemini API: {exc}"}), 502

    if resp.status_code >= 400:
        print(f"[NovaVoice] Token mint failed {resp.status_code}: {resp.text[:300]}")
        return jsonify({"error": f"Token request failed ({resp.status_code}). See server log."}), 502

    name = (resp.json() or {}).get("name", "")
    if not name:
        return jsonify({"error": "Gemini returned no token name."}), 502

    print(f"[NovaVoice] Minted ephemeral token, valid {TOKEN_TTL_MINUTES} min")
    return jsonify({"token": name, "expires_in_minutes": TOKEN_TTL_MINUTES})


@app.get("/api/live_models")
def api_live_models():
    """List models this key can use with the Live API - preview names rotate."""
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not set in .env."}), 500
    try:
        resp = requests.get(
            f"{GEMINI_BASE}/models",
            headers={"x-goog-api-key": GEMINI_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502

    live = [
        m.get("name")
        for m in resp.json().get("models", [])
        if "bidiGenerateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    return jsonify({"live_models": live})


# ───────────────────── calendar tools ─────────────────────

@app.post("/api/check_availability")
def api_check_availability():
    data = request.get_json(force=True, silent=True) or {}
    date = data.get("date", "")
    if not date:
        return jsonify({"result": "Error: no date was provided to check."})

    print(f"[NovaVoice] check_availability: {date}")
    result = check_availability(date)
    print(f"[NovaVoice]   -> {result[:140]}")
    return jsonify({"result": result})


@app.post("/api/find_free_slots")
def api_find_free_slots():
    data = request.get_json(force=True, silent=True) or {}
    date = data.get("date", "")
    if not date:
        return jsonify({"result": "Error: no date was provided."})

    print(f"[NovaVoice] find_free_slots: {date}")
    result = find_free_slots(date, int(data.get("duration_minutes") or 0))
    print(f"[NovaVoice]   -> {result[:140]}")
    return jsonify({"result": result})


@app.post("/api/propose_change")
def api_propose_change():
    """Phase one of every write: describe the change, get a one-time code."""
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    if not action:
        return jsonify({"result": "Error: no action was provided ('book', 'cancel' or 'reschedule')."})

    print(f"[NovaVoice] propose_change: {action} {dict(data)}")
    result = propose_change(
        action,
        title=data.get("title", ""),
        date_time=data.get("date_time", ""),
        guest_email=data.get("guest_email", ""),
        duration_minutes=int(data.get("duration_minutes") or 0),
        event_id=data.get("event_id", ""),
        new_date_time=data.get("new_date_time", ""),
    )
    print(f"[NovaVoice]   -> {result[:140]}")
    return jsonify({"result": result})


# The three write routes take nothing but a confirmation_code. Their arguments
# were frozen when propose_change issued it, so a model that skips the proposal
# step -- or changes its mind about the details afterwards -- cannot write.

@app.post("/api/book_meeting")
def api_book_meeting():
    data = request.get_json(force=True, silent=True) or {}
    code = data.get("confirmation_code", "")

    print(f"[NovaVoice] book_meeting: code={code}")
    result = book_meeting(code)
    print(f"[NovaVoice]   -> {result}")
    return jsonify({"result": result})


@app.post("/api/cancel_meeting")
def api_cancel_meeting():
    data = request.get_json(force=True, silent=True) or {}
    code = data.get("confirmation_code", "")

    print(f"[NovaVoice] cancel_meeting: code={code}")
    result = cancel_meeting(code)
    print(f"[NovaVoice]   -> {result}")
    return jsonify({"result": result})


@app.post("/api/reschedule_meeting")
def api_reschedule_meeting():
    data = request.get_json(force=True, silent=True) or {}
    code = data.get("confirmation_code", "")

    print(f"[NovaVoice] reschedule_meeting: code={code}")
    result = reschedule_meeting(code)
    print(f"[NovaVoice]   -> {result}")
    return jsonify({"result": result})


@app.get("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "gemini_key_loaded": bool(GEMINI_API_KEY),
        "bridge_token": bool(BRIDGE_TOKEN),
    })


if __name__ == "__main__":
    print("[NovaVoice] API bridge running on http://127.0.0.1:5000")
    print(f"[NovaVoice] Allowed origins : {', '.join(ALLOWED_ORIGINS)}")
    print(f"[NovaVoice] Bridge token    : {'enabled' if BRIDGE_TOKEN else 'disabled'}")
    print(f"[NovaVoice] Gemini API key  : {'loaded' if GEMINI_API_KEY else 'MISSING - add GEMINI_API_KEY to .env'}")
    app.run(host="127.0.0.1", port=5000, debug=False)
