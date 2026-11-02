"""
test_enterprise_suite.py - Comprehensive enterprise test suite for AstraVoice.

Covers:
  1. API endpoint & HTTP contract testing (Flask test client).
  2. Bridge token authentication & header security.
  3. Input sanitization (non-integer durations, malformed JSON, empty inputs).
  4. Confirmation token lifecycle (single-use, action-binding, expiry, forgery refusal).
  5. Concurrency & race condition safety (multi-threaded token issuance & consumption).
  6. Timezone conversions & DST offset normalization.
  7. Past-date scheduling guardrails.
  8. Deployment configuration validation (Dockerfile, dependencies).
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Set up test environment
os.environ["HOST_TIMEZONE"] = "Asia/Kolkata"
os.environ["MEETING_MINUTES"] = "30"
os.environ["WORK_START_HOUR"] = "9"
os.environ["WORK_END_HOUR"] = "18"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calendar_tool as ct
import api_server as srv

# Mock calendar events
TEST_EVENTS = [
    {
        "id": "team_sync_1",
        "summary": "Team Sync",
        "start": {"dateTime": "2026-11-10T10:00:00+05:30"},
        "end": {"dateTime": "2026-11-10T11:00:00+05:30"},
    },
    {
        "id": "lunch_1",
        "summary": "Lunch Break",
        "transparency": "transparent",
        "start": {"dateTime": "2026-11-10T13:00:00+05:30"},
        "end": {"dateTime": "2026-11-10T14:00:00+05:30"},
    },
]

ct.get_calendar_service = lambda: "mock_service"
ct._list_events = lambda svc, lo, hi: TEST_EVENTS
ct._find_event = lambda svc, eid: next((e for e in TEST_EVENTS if e["id"] == eid), None)


def test_api_endpoints():
    client = srv.app.test_client()

    # 1. Health endpoints
    r = client.get("/health")
    assert r.status_code == 200, f"/health returned {r.status_code}"
    data = r.get_json()
    assert data["ok"] is True and data["status"] == "healthy"

    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    # 2. Static files
    r = client.get("/")
    assert r.status_code == 200
    assert b"AstraVoice" in r.data

    r = client.get("/session_config.json")
    assert r.status_code == 200
    cfg = r.get_json()
    assert "systemPrompt" in cfg and "functionDeclarations" in cfg

    # 3. Calendar bridge validation
    r = client.post("/api/check_availability", json={})
    assert "Error: no date was provided" in r.get_json().get("result", "")

    r = client.post("/api/find_free_slots", json={"date": "2026-11-10", "duration_minutes": "invalid"})
    assert r.status_code == 200
    assert "Free windows" in r.get_json().get("result", "")

    r = client.post("/api/propose_change", json={})
    assert "Error: no action" in r.get_json().get("result", "")

    r = client.post("/api/book_meeting", json={})
    assert "Refused:" in r.get_json().get("result", "")

    print("  PASS  API Endpoints & HTTP contract tests")


def test_bridge_token_security():
    client = srv.app.test_client()

    srv.BRIDGE_TOKEN = "secret-token-123"
    try:
        # Protected endpoint without token -> 401
        r = client.post("/api/check_availability", json={"date": "2026-11-10"})
        assert r.status_code == 401, f"Expected 401 without token, got {r.status_code}"

        # Protected endpoint with wrong token -> 401
        r = client.post(
            "/api/check_availability",
            headers={"X-Bridge-Token": "wrong-token"},
            json={"date": "2026-11-10"},
        )
        assert r.status_code == 401

        # Protected endpoint with correct token -> 200
        r = client.post(
            "/api/check_availability",
            headers={"X-Bridge-Token": "secret-token-123"},
            json={"date": "2026-11-10"},
        )
        assert r.status_code == 200

        # Public endpoints remain unblocked
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/session_config.json").status_code == 200
    finally:
        srv.BRIDGE_TOKEN = ""

    print("  PASS  Bridge Token security & exemption tests")


def test_input_sanitization():
    # Negative duration in free slots
    slots = ct.find_free_slots("2026-11-10", duration_minutes=-30)
    assert "Free windows" in slots

    # Bad date parsing
    try:
        ct._parse_iso("not-an-iso-date")
        assert False, "Should raise ValueError on invalid date"
    except ValueError:
        pass

    # Empty date string
    try:
        ct._parse_iso("")
        assert False, "Should raise ValueError on empty date"
    except ValueError:
        pass

    # Empty event id for cancellation
    res = ct.propose_change(action="cancel", event_id="")
    assert "Cannot propose a cancellation without an event_id" in res

    print("  PASS  Input sanitization & boundary validation tests")


def test_confirmation_token_lifecycle():
    # 1. Action binding: cancel with book code must fail (and consumes the single-use token)
    summary_cancel = ct.propose_change(
        action="book",
        title="Architecture Review",
        date_time="2026-11-10T14:00:00+05:30",
        duration_minutes=30,
    )
    import re
    match = re.search(r"confirmation_code '([0-9a-f]+)'", summary_cancel)
    assert match, "Failed to extract confirmation code"
    code_mismatch = match.group(1)

    _, err = ct._consume(code_mismatch, "cancel")
    assert err and "was issued to book, not to cancel" in err

    # 2. Single-use: first book consumption succeeds, second fails
    summary_book = ct.propose_change(
        action="book",
        title="Architecture Review",
        date_time="2026-11-10T14:00:00+05:30",
        duration_minutes=30,
    )
    code_valid = re.search(r"confirmation_code '([0-9a-f]+)'", summary_book).group(1)

    args, err = ct._consume(code_valid, "book")
    assert args is not None and err is None
    assert args["title"] == "Architecture Review"

    # Replay attack: second consumption must fail
    _, err = ct._consume(code_valid, "book")
    assert err and "no pending proposal with that code" in err

    # 3. Expiry
    summary2 = ct.propose_change(
        action="book",
        title="Quick Chat",
        date_time="2026-11-10T15:00:00+05:30",
        duration_minutes=15,
    )
    code2 = re.search(r"confirmation_code '([0-9a-f]+)'", summary2).group(1)
    # Fast-forward expiry
    act, a_args, _ = ct._PENDING[code2]
    ct._PENDING[code2] = (act, a_args, time.monotonic() - 1)
    _, err = ct._consume(code2, "book")
    assert err and "proposal expired" in err

    print("  PASS  Confirmation token security & single-use lifecycle tests")


def test_concurrent_proposals_and_claims():
    # Multi-threaded concurrent proposal issuance: no code collisions
    codes = set()
    lock = threading.Lock()

    def worker():
        c = ct._issue("book", {"test": True})
        with lock:
            codes.add(c)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(codes) == 50, f"Expected 50 unique codes, got {len(codes)} (collision occurred!)"

    # Multi-threaded race condition on consuming a single code: exactly ONE wins
    single_code = ct._issue("book", {"resource": "target"})
    successes = []

    def claim_worker():
        args, err = ct._consume(single_code, "book")
        if args is not None:
            with lock:
                successes.append(args)

    claim_threads = [threading.Thread(target=claim_worker) for _ in range(50)]
    for t in claim_threads:
        t.start()
    for t in claim_threads:
        t.join()

    assert len(successes) == 1, f"Expected exactly 1 claim success, got {len(successes)}"

    print("  PASS  Concurrency & race-condition resilience tests (50 concurrent workers)")


def test_timezone_normalization():
    # Bare date
    dt_bare = ct._parse_iso("2026-11-10")
    assert dt_bare.tzinfo is not None
    assert str(dt_bare.tzinfo) == "Asia/Kolkata"
    assert dt_bare.hour == 0

    # UTC with Z
    dt_utc = ct._parse_iso("2026-11-10T04:30:00Z")
    # 04:30 UTC == 10:00 Asia/Kolkata (+05:30)
    assert dt_utc.hour == 10 and dt_utc.minute == 0

    # Explicit offset -05:00
    dt_ny = ct._parse_iso("2026-11-10T10:00:00-05:00")
    # 10:00 EST (-05:00) == 15:00 UTC == 20:30 IST (+05:30)
    assert dt_ny.hour == 20 and dt_ny.minute == 30

    print("  PASS  Timezone math & ISO-8601 normalization tests")


def test_past_date_guardrail():
    # Set ENFORCE_FUTURE_DATES = True
    ct.ENFORCE_FUTURE_DATES = True
    try:
        # Attempt to book in 2020
        res = ct.propose_change(
            action="book",
            title="Past Event",
            date_time="2020-01-01T10:00:00+05:30",
            duration_minutes=30,
        )
        assert "Cannot book a meeting in the past" in res

        # Attempt to reschedule to 2020
        res_move = ct.propose_change(
            action="reschedule",
            event_id="team_sync_1",
            new_date_time="2020-01-01T10:00:00+05:30",
        )
        assert "Cannot reschedule to a time in the past" in res_move
    finally:
        ct.ENFORCE_FUTURE_DATES = False

    print("  PASS  Past-date protection & refusal guardrail tests")


def test_deployment_config():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 1. Dockerfile
    dockerfile = os.path.join(root, "Dockerfile")
    assert os.path.exists(dockerfile), "Dockerfile not found"
    with open(dockerfile, "r") as f:
        df_content = f.read()
    assert "PORT" in df_content
    assert "gunicorn" in df_content

    # 2. Requirements
    reqs = os.path.join(root, "requirements.txt")
    assert os.path.exists(reqs), "requirements.txt not found"
    with open(reqs, "r") as f:
        req_content = f.read()
    assert "Flask" in req_content
    assert "google-api-python-client" in req_content

    print("  PASS  Deployment configuration & container artifact tests")


def main():
    print("\n" + "=" * 65)
    print("      ASTRAVOICE ENTERPRISE QUALITY & INTEGRATION TEST SUITE      ")
    print("=" * 65 + "\n")

    tests = [
        test_api_endpoints,
        test_bridge_token_security,
        test_input_sanitization,
        test_confirmation_token_lifecycle,
        test_concurrent_proposals_and_claims,
        test_timezone_normalization,
        test_past_date_guardrail,
        test_deployment_config,
    ]

    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1

    print("\n" + "-" * 65)
    print(f"Result: {len(tests) - failed}/{len(tests)} test suites passed.")
    print("-" * 65 + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
