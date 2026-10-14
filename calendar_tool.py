"""
calendar_tool.py - Google Calendar logic used by api_server.py.

Design note: every write tool re-validates the slot against the live calendar
before touching it. The model is *asked* to call check_availability first, but
the tool never relies on that -- an LLM that skips a step must not be able to
double-book.
"""

import os
import json
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

HOST_CALENDAR_ID = os.getenv("HOST_CALENDAR_ID", "primary")
HOST_TIMEZONE = os.getenv("HOST_TIMEZONE", "Asia/Kolkata")
MEETING_MINUTES = int(os.getenv("MEETING_MINUTES", "30"))  # default only; callers may override
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.json")

try:
    LOCAL_TZ = ZoneInfo(HOST_TIMEZONE)
except Exception:
    print(f"[Calendar] Unknown HOST_TIMEZONE '{HOST_TIMEZONE}', falling back to Asia/Kolkata")
    HOST_TIMEZONE = "Asia/Kolkata"
    LOCAL_TZ = ZoneInfo(HOST_TIMEZONE)


# ───────────────────────────── auth ─────────────────────────────

def _save_token(creds) -> None:
    """Persist (possibly refreshed) credentials back to token.json if writable."""
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else [],
    }
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as exc:
        print(f"[Calendar] Note: could not write refreshed token to disk: {exc}")


def get_calendar_service():
    """Load token.json or GOOGLE_TOKEN_JSON env var, refresh if stale, and return a Calendar v3 service."""
    token_env = os.getenv("GOOGLE_TOKEN_JSON")
    if token_env:
        try:
            token_data = json.loads(token_env)
        except Exception as exc:
            raise ValueError(f"Failed to parse GOOGLE_TOKEN_JSON: {exc}")
    elif os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token_data = json.load(f)
    else:
        raise FileNotFoundError(
            f"'{TOKEN_FILE}' not found and GOOGLE_TOKEN_JSON not set. "
            "Run auth_server.py first to complete the OAuth flow."
        )

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )

    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
        print("[Calendar] Access token refreshed and saved.")

    return build("calendar", "v3", credentials=creds)


# ───────────────────────── time helpers ─────────────────────────

def _parse_iso(date_iso: str) -> datetime:
    """
    Parse an ISO 8601 date or datetime into a timezone-aware datetime.
    Tolerates a trailing 'Z' and offsets like +05:30. A value with no timezone
    is read in HOST_TIMEZONE, not UTC -- otherwise a bare date like
    "2026-10-14" would select the wrong 24-hour window for any non-UTC host.
    """
    date_iso = (date_iso or "").strip()
    if not date_iso:
        raise ValueError("empty date string")

    if date_iso.endswith(("Z", "z")):
        date_iso = date_iso[:-1] + "+00:00"

    dt = datetime.fromisoformat(date_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _day_bounds(dt: datetime):
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _event_window(event):
    """Return (start, end) as aware datetimes, or (None, None) for all-day events."""
    start_raw = event.get("start", {}).get("dateTime")
    end_raw = event.get("end", {}).get("dateTime")
    if not start_raw or not end_raw:
        return None, None
    try:
        return _parse_iso(start_raw), _parse_iso(end_raw)
    except Exception:
        return None, None


def _list_events(service, time_min: datetime, time_max: datetime):
    result = (
        service.events()
        .list(
            calendarId=HOST_CALENDAR_ID,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            timeZone=HOST_TIMEZONE,
        )
        .execute()
    )
    return result.get("items", [])


def _conflicts(service, start: datetime, end: datetime, ignore_event_id: str = ""):
    """
    Events that genuinely block [start, end). Ignores all-day entries and
    anything marked 'Free' (transparency=transparent), and can skip one event
    so rescheduling doesn't see the event clashing with itself.
    """
    blocking = []
    # Widen the query by a day either side so long events are not missed.
    for event in _list_events(service, start - timedelta(days=1), end + timedelta(days=1)):
        if event.get("id") == ignore_event_id:
            continue
        if event.get("transparency") == "transparent":
            continue
        if event.get("status") == "cancelled":
            continue
        ev_start, ev_end = _event_window(event)
        if not ev_start:
            continue  # all-day: does not block a timed slot
        if ev_start < end and start < ev_end:
            blocking.append((event, ev_start, ev_end))
    return blocking


def _describe(conflicts) -> str:
    return "; ".join(
        f"'{e.get('summary', '(no title)')}' {s.strftime('%H:%M')}-{t.strftime('%H:%M')}"
        for e, s, t in conflicts
    )


def _find_event(service, event_id: str):
    try:
        event = service.events().get(calendarId=HOST_CALENDAR_ID, eventId=event_id).execute()
        return event if event.get("status") != "cancelled" else None
    except Exception:
        return None


# ──────────────────────────── tools ────────────────────────────

def check_availability(date_iso: str) -> str:
    """List events for the given day. Event ids are included so the agent can
    cancel or reschedule a specific one."""
    try:
        service = get_calendar_service()
        day_start, day_end = _day_bounds(_parse_iso(date_iso))
        date_label = day_start.strftime("%Y-%m-%d")

        events = _list_events(service, day_start, day_end)
        if not events:
            return f"The calendar is completely free on {date_label}."

        lines = [f"Events on {date_label} ({HOST_TIMEZONE}):"]
        for event in events:
            summary = event.get("summary", "(no title)")
            ev_id = event.get("id", "")
            ev_start, ev_end = _event_window(event)
            free = " [marked Free]" if event.get("transparency") == "transparent" else ""
            if ev_start:
                lines.append(
                    f"  - {ev_start.strftime('%H:%M')}-{ev_end.strftime('%H:%M')} "
                    f"{summary}{free} [id: {ev_id}]"
                )
            else:
                lines.append(f"  - All day: {summary} [id: {ev_id}]")

        return "\n".join(lines)

    except Exception as exc:
        return f"Failed to check availability: {exc}"


def find_free_slots(date_iso: str, duration_minutes: int = 0) -> str:
    """Free windows on the given day within working hours, for 'suggest the next free slot'."""
    try:
        duration = duration_minutes or MEETING_MINUTES
        service = get_calendar_service()
        day_start, _ = _day_bounds(_parse_iso(date_iso))

        work_start = day_start.replace(hour=int(os.getenv("WORK_START_HOUR", "9")))
        work_end = day_start.replace(hour=int(os.getenv("WORK_END_HOUR", "18")))

        busy = sorted(
            (s, t) for _, s, t in _conflicts(service, work_start, work_end)
        )

        free, cursor = [], work_start
        for s, t in busy:
            if s - cursor >= timedelta(minutes=duration):
                free.append((cursor, s))
            cursor = max(cursor, t)
        if work_end - cursor >= timedelta(minutes=duration):
            free.append((cursor, work_end))

        label = day_start.strftime("%Y-%m-%d")
        if not free:
            return f"No free {duration}-minute window on {label} between {work_start.strftime('%H:%M')} and {work_end.strftime('%H:%M')}."

        windows = ", ".join(f"{s.strftime('%H:%M')}-{t.strftime('%H:%M')}" for s, t in free)
        return f"Free windows on {label} ({HOST_TIMEZONE}): {windows}."

    except Exception as exc:
        return f"Failed to find free slots: {exc}"


# ──────────────────── two-phase writes ────────────────────
# The system prompt asks the model to confirm before writing, but invariant 1
# applies here too: correctness must never depend on the model following
# instructions. So a write is reachable only through a code issued by
# propose_change, and the arguments are frozen at proposal time -- the model
# cannot propose change A and then execute change B with the same code.
#
# An in-process dict on purpose: a restart drops pending proposals, which is
# correct, since an unconfirmed proposal should not outlive the conversation
# that created it.
PROPOSAL_TTL_SECONDS = 300
_PENDING = {}


def _issue(action: str, args: dict) -> str:
    """Store a proposal and return its one-time code."""
    now = time.monotonic()
    for stale in [k for k, (_, _, exp) in _PENDING.items() if exp < now]:
        _PENDING.pop(stale, None)  # keep the dict from growing without bound
    code = secrets.token_hex(4)
    _PENDING[code] = (action, args, now + PROPOSAL_TTL_SECONDS)
    return code


def _consume(code: str, expect: str):
    """Pop a proposal. Returns (args, None) on success, (None, message) otherwise."""
    entry = _PENDING.pop((code or "").strip(), None)
    if not entry:
        return None, (
            "Refused: no pending proposal with that code. Call propose_change first, "
            "read its summary back to the user, and use the code only once they agree."
        )
    action, args, expires = entry
    if time.monotonic() > expires:
        return None, (
            "Refused: that proposal expired. Propose the change again and re-confirm "
            "with the user."
        )
    if action != expect:
        return None, f"Refused: that code was issued to {action}, not to {expect}."
    return args, None


def propose_change(
    action: str,
    title: str = "",
    date_time: str = "",
    guest_email: str = "",
    duration_minutes: int = 0,
    event_id: str = "",
    new_date_time: str = "",
) -> str:
    """
    Describe an intended write and get a one-time confirmation code for it.

    Validates against the live calendar now, so a clash surfaces before the user
    is asked to agree to something impossible.
    """
    try:
        action = (action or "").strip().lower()
        service = get_calendar_service()

        if action == "book":
            if not date_time:
                return "Cannot propose a booking without a date_time."
            minutes = int(duration_minutes or MEETING_MINUTES)
            if minutes <= 0:
                return "Cannot propose a booking with a non-positive duration."
            start = _parse_iso(date_time)
            end = start + timedelta(minutes=minutes)

            clash = _conflicts(service, start, end)
            if clash:
                return (
                    f"Cannot book {start.strftime('%A %d %B %H:%M')} - already taken by "
                    f"{_describe(clash)}. Offer the user a different time."
                )

            args = {
                "date_time": date_time,
                "title": title or "AstraVoice Demo",
                "guest_email": guest_email,
                "duration_minutes": minutes,
            }
            code = _issue("book", args)
            guest = f" with {guest_email}" if guest_email and "@" in guest_email else ""
            return (
                f"Ready to book '{args['title']}'{guest} on "
                f"{start.strftime('%A %d %B at %H:%M')} for {minutes} minutes. "
                f"Confirm with the user, then call book_meeting with "
                f"confirmation_code '{code}'."
            )

        if action == "cancel":
            event = _find_event(service, event_id)
            if not event:
                return f"No active event found with id '{event_id}'."
            start, _ = _event_window(event)
            when = start.strftime("%A %d %B at %H:%M") if start else "an all-day slot"
            code = _issue("cancel", {"event_id": event_id})
            return (
                f"Ready to cancel '{event.get('summary', '(no title)')}', which is on "
                f"{when}. Guests will be notified. Confirm with the user, then call "
                f"cancel_meeting with confirmation_code '{code}'."
            )

        if action == "reschedule":
            if not new_date_time:
                return "Cannot propose a reschedule without new_date_time."
            event = _find_event(service, event_id)
            if not event:
                return f"No active event found with id '{event_id}'."
            old_start, old_end = _event_window(event)
            if not old_start:
                return "That is an all-day event; rescheduling only supports timed events."

            new_start = _parse_iso(new_date_time)
            clash = _conflicts(
                service, new_start, new_start + (old_end - old_start),
                ignore_event_id=event_id,
            )
            if clash:
                return (
                    f"Cannot move it to {new_start.strftime('%A %d %B %H:%M')} - already "
                    f"taken by {_describe(clash)}. Offer the user a different time."
                )

            code = _issue(
                "reschedule", {"event_id": event_id, "new_date_time": new_date_time}
            )
            return (
                f"Ready to move '{event.get('summary', '(no title)')}' from "
                f"{old_start.strftime('%A %d %B %H:%M')} to "
                f"{new_start.strftime('%A %d %B at %H:%M')}. Guests will be notified. "
                f"Confirm with the user, then call reschedule_meeting with "
                f"confirmation_code '{code}'."
            )

        return f"Unknown action '{action}'. Use 'book', 'cancel' or 'reschedule'."

    except Exception as exc:
        return f"Failed to prepare that change: {exc}"


# ──────────────────────────── writes ────────────────────────────

def book_meeting(confirmation_code: str) -> str:
    """Create the meeting a propose_change code stands for."""
    args, error = _consume(confirmation_code, "book")
    if error:
        return error

    try:
        service = get_calendar_service()
        start_dt = _parse_iso(args["date_time"])
        end_dt = start_dt + timedelta(minutes=args["duration_minutes"])

        # Re-check even though propose_change already did: minutes pass while
        # the user decides, and another client may have taken the slot.
        clash = _conflicts(service, start_dt, end_dt)
        if clash:
            return (
                f"Not booked - {start_dt.strftime('%A %d %B %H:%M')} is already taken by "
                f"{_describe(clash)}. Offer the user a different time."
            )

        event = {
            "summary": args["title"],
            "description": "Automated booking created via the AstraVoice voice agent.",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": HOST_TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": HOST_TIMEZONE},
            "conferenceData": {
                "createRequest": {
                    "requestId": secrets.token_hex(8),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        guest_email = args.get("guest_email") or ""
        send_updates = "none"
        if guest_email and "@" in guest_email:
            event["attendees"] = [{"email": guest_email}]
            send_updates = "all"

        try:
            created = (
                service.events()
                .insert(
                    calendarId=HOST_CALENDAR_ID,
                    body=event,
                    sendUpdates=send_updates,
                    conferenceDataVersion=1,
                )
                .execute()
            )
        except Exception as insert_err:
            print(f"[Calendar] Conference insert failed ({insert_err}), falling back to standard event")
            event.pop("conferenceData", None)
            created = (
                service.events()
                .insert(calendarId=HOST_CALENDAR_ID, body=event, sendUpdates=send_updates)
                .execute()
            )

        when = start_dt.strftime("%A %d %B at %H:%M")
        meet_link = created.get("hangoutLink") or ""
        print(f"[Calendar] Booked: {created.get('htmlLink', '(no link)')} | Meet: {meet_link or 'none'}")

        invited = f" An invite was emailed to {guest_email}." if send_updates == "all" else ""
        meet_msg = f" Google Meet link attached: {meet_link}." if meet_link else ""
        return (
            f"Success! '{event['summary']}' is booked for {when}, "
            f"{args['duration_minutes']} minutes.{invited}{meet_msg} [id: {created.get('id', '')}]"
        )

    except Exception as exc:
        print(f"[Calendar] Failed to book: {exc}")
        return f"Failed to book meeting: {exc}"


def cancel_meeting(confirmation_code: str) -> str:
    """Delete the event a propose_change code stands for."""
    args, error = _consume(confirmation_code, "cancel")
    if error:
        return error

    try:
        service = get_calendar_service()
        event_id = args["event_id"]
        event = _find_event(service, event_id)
        if not event:
            return f"No active event found with id '{event_id}'. It may already be cancelled."

        summary = event.get("summary", "(no title)")
        ev_start, _ = _event_window(event)
        when = ev_start.strftime("%A %d %B at %H:%M") if ev_start else "an all-day slot"

        service.events().delete(
            calendarId=HOST_CALENDAR_ID, eventId=event_id, sendUpdates="all"
        ).execute()

        print(f"[Calendar] Cancelled '{summary}' ({event_id})")
        return f"Cancelled '{summary}', which was on {when}. Any guests were notified."

    except Exception as exc:
        print(f"[Calendar] Failed to cancel: {exc}")
        return f"Failed to cancel meeting: {exc}"


def reschedule_meeting(confirmation_code: str) -> str:
    """Move the event a propose_change code stands for, keeping its duration."""
    args, error = _consume(confirmation_code, "reschedule")
    if error:
        return error

    try:
        service = get_calendar_service()
        event_id = args["event_id"]
        event = _find_event(service, event_id)
        if not event:
            return f"No active event found with id '{event_id}'."

        old_start, old_end = _event_window(event)
        if not old_start:
            return "That is an all-day event; rescheduling only supports timed events."

        duration = old_end - old_start
        new_start = _parse_iso(args["new_date_time"])
        new_end = new_start + duration

        # Re-check, and ignore the event itself or it clashes with its own slot.
        clash = _conflicts(service, new_start, new_end, ignore_event_id=event_id)
        if clash:
            return (
                f"Not moved - {new_start.strftime('%A %d %B %H:%M')} is already taken by "
                f"{_describe(clash)}. Offer the user a different time."
            )

        updated = (
            service.events()
            .patch(
                calendarId=HOST_CALENDAR_ID,
                eventId=event_id,
                body={
                    "start": {"dateTime": new_start.isoformat(), "timeZone": HOST_TIMEZONE},
                    "end": {"dateTime": new_end.isoformat(), "timeZone": HOST_TIMEZONE},
                },
                sendUpdates="all",
            )
            .execute()
        )

        summary = updated.get("summary", "(no title)")
        print(f"[Calendar] Rescheduled '{summary}' to {new_start.isoformat()}")
        return (
            f"Moved '{summary}' from {old_start.strftime('%A %d %B %H:%M')} "
            f"to {new_start.strftime('%A %d %B at %H:%M')}. Any guests were notified."
        )

    except Exception as exc:
        print(f"[Calendar] Failed to reschedule: {exc}")
        return f"Failed to reschedule meeting: {exc}"
