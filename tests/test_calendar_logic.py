"""
Self-contained logic tests for calendar_tool.py. No pytest, no venv, no network:
the Google client libraries are stubbed and the calendar is a fixed list of events.

    python3 tests/test_calendar_logic.py

Covers the overlap maths that keeps the agent from double-booking. If you touch
_conflicts, _parse_iso or find_free_slots, run this first.
"""

import os
import re
import sys
import types

os.environ.setdefault("HOST_TIMEZONE", "Asia/Kolkata")
os.environ.setdefault("MEETING_MINUTES", "30")
os.environ.setdefault("WORK_START_HOUR", "9")
os.environ.setdefault("WORK_END_HOUR", "18")


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module


# Stand in for the Google libs so this runs without the venv.
_stub("dotenv", load_dotenv=lambda *a, **k: None)
_stub("google")
_stub("google.oauth2")
_stub("google.oauth2.credentials", Credentials=object)
_stub("google.auth")
_stub("google.auth.transport")
_stub("google.auth.transport.requests", Request=object)
_stub("googleapiclient")
_stub("googleapiclient.discovery", build=lambda *a, **k: None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calendar_tool as ct  # noqa: E402

# 11:00-12:00 is genuinely busy; 14:00-14:30 is marked Free; Diwali is all-day.
EVENTS = [
    {"id": "busy1", "summary": "Standup",
     "start": {"dateTime": "2026-10-20T11:00:00+05:30"},
     "end":   {"dateTime": "2026-10-20T12:00:00+05:30"}},
    {"id": "free1", "summary": "Gym", "transparency": "transparent",
     "start": {"dateTime": "2026-10-20T14:00:00+05:30"},
     "end":   {"dateTime": "2026-10-20T14:30:00+05:30"}},
    {"id": "allday1", "summary": "Diwali",
     "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}},
]

ct.get_calendar_service = lambda: "svc"
ct._list_events = lambda svc, lo, hi: EVENTS
ct._find_event = lambda svc, eid: next((e for e in EVENTS if e["id"] == eid), None)


def conflicts_at(hhmm, ignore=""):
    start = ct._parse_iso(f"2026-10-20T{hhmm}:00+05:30")
    end = start + ct.timedelta(minutes=30)
    return ct._conflicts("svc", start, end, ignore_event_id=ignore)


def propose_book(hhmm, minutes=0):
    return ct.propose_change(
        action="book",
        title="Test",
        date_time=f"2026-10-20T{hhmm}:00+05:30",
        duration_minutes=minutes,
    )


def code_in(summary):
    """Pull the confirmation code out of a propose_change summary, or ''."""
    match = re.search(r"confirmation_code '([0-9a-f]+)'", summary)
    return match.group(1) if match else ""


def main():
    slots = ct.find_free_slots("2026-10-20")
    parsed = ct._parse_iso("2026-10-20")

    # Duration is honoured: 10:30 is free for 30 minutes but not for 60, because
    # a 60-minute meeting would run into the 11:00 standup.
    short_booking = propose_book("10:30", 30)
    long_booking = propose_book("10:30", 60)

    # Two-phase writes: a code is single-use, action-bound, and required.
    good_code = code_in(propose_book("15:00", 45))
    first_use = ct._consume(good_code, "book")
    second_use = ct._consume(good_code, "book")
    wrong_action_code = code_in(propose_book("16:00"))
    wrong_action = ct._consume(wrong_action_code, "cancel")

    expired_code = code_in(propose_book("17:00"))
    action, args, _ = ct._PENDING[expired_code]
    ct._PENDING[expired_code] = (action, args, ct.time.monotonic() - 1)
    expired = ct._consume(expired_code, "book")

    cases = [
        ("11:30 overlaps the 11-12 meeting",        bool(conflicts_at("11:30"))),
        ("11:45 straddles its end -> conflict",     bool(conflicts_at("11:45"))),
        ("10:45 straddles its start -> conflict",   bool(conflicts_at("10:45"))),
        ("12:00 is back-to-back -> allowed",        not conflicts_at("12:00")),
        ("10:30 ends as it starts -> allowed",      not conflicts_at("10:30")),
        ("an event marked Free does not block",     not conflicts_at("14:00")),
        ("an all-day event does not block 16:00",   not conflicts_at("16:00")),
        ("reschedule ignoring itself is clear",     not conflicts_at("11:30", ignore="busy1")),
        ("a bare date resolves in HOST_TIMEZONE",
         (parsed.hour, parsed.utcoffset().total_seconds()) == (0, 19800)),
        ("free slots skip the busy hour",
         "09:00-11:00" in slots and "12:00-18:00" in slots),

        ("a 30-minute booking at 10:30 is clear",     bool(code_in(short_booking))),
        ("the same slot for 60 minutes is refused",   not code_in(long_booking)),
        ("propose_change issues a confirmation code", bool(good_code)),
        ("the code it issued carries the duration",
         first_use[0] is not None and first_use[0]["duration_minutes"] == 45),
        ("a code works exactly once",                 second_use[0] is None),
        ("a book code cannot cancel",                 wrong_action[0] is None),
        ("an expired code is refused",                expired[0] is None),
        ("a write without a code is refused",
         ct.book_meeting("").startswith("Refused")),
        ("a made-up code is refused",
         ct.cancel_meeting("deadbeef").startswith("Refused")),
    ]

    failed = 0
    for name, ok in cases:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        failed += not ok

    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    print(f"find_free_slots -> {slots}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
