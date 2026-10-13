# NovaVoice — project context for Claude Code

Real-time voice booking agent: Gemini Live API (browser WebSocket) + Google Calendar
(Python bridge). Originally from the Google codelab *Build a Real-Time Voice AI Agent
with the Gemini Live API, Antigravity and Google Calendar*; this folder is a hardened
fork of it. The codelab original is untouched at `../GDG Project` — treat it as a
read-only reference, never edit it.

## Run it

```bash
python -m venv venv && venv\Scripts\activate   # Windows; venv is NOT in this folder yet
pip install -r requirements.txt

python auth_server.py        # once only, writes token.json, then Ctrl+C
python api_server.py         # terminal 1 — bridge on :5000
python -m http.server 8000   # terminal 2 — serves index.html
```

Then open <http://localhost:8000> in Chrome. There is no API key to paste.

```bash
python3 tests/test_calendar_logic.py           # no venv needed, stubs the Google libs
python evals/run_evals.py --selftest           # scores the scorer, no model calls
python evals/run_evals.py                      # does the agent pick the right tool?
curl http://127.0.0.1:5000/api/health          # is GEMINI_API_KEY loaded?
curl http://127.0.0.1:5000/api/live_models     # which Live models this key can use
```

## Architecture

```
index.html (:8000)
  ├─ POST /api/live_token  ──▶ api_server.py (:5000)  holds GEMINI_API_KEY
  │   └─ single-use ephemeral token back
  ├─ wss://…v1beta…BidiGenerateContent?access_token=<token>   audio in/out
  └─ on toolCall: POST /api/<tool_name> ──▶ api_server.py ──▶ calendar_tool.py ──▶ Calendar
```

| File | Role |
|---|---|
| `index.html` | Entire frontend: config constants at the top of `<script>`, canvas orb + day dial, PCM audio pipeline, WS client, tool router |
| `api_server.py` | Flask bridge: token minting + one route per tool. No business logic |
| `calendar_tool.py` | All Calendar v3 logic and every time calculation |
| `auth_server.py` | One-time OAuth flow, writes `token.json`. Not used at runtime |
| `session_config.json` | The agent's contract: system prompt + tool schemas. Read by `index.html` AND the evals |
| `tests/test_calendar_logic.py` | Overlap/timezone tests, runs standalone |
| `evals/run_evals.py` | Scores tool choice against scripted conversations in `evals/cases.json` |
| `DEMO.md` | Shot-by-shot script for the README video |

## Invariants — do not regress these

Each of these was a real bug. The reasons matter more than the code.

1. **Writes re-validate against the live calendar.** `book_meeting` and
   `reschedule_meeting` call `_conflicts()` and refuse on overlap. The prompt asks the
   model to call `check_availability` first, but correctness must never depend on the
   model following instructions. Keep the guard even though it duplicates a check.
2. **`_parse_iso` treats a naive datetime as `HOST_TIMEZONE`, never UTC.** A bare
   `2026-10-20` once became UTC midnight, so "tomorrow" scanned the wrong 24 hours for
   any non-UTC host. All date maths funnels through this one function on purpose.
3. **`timeZone` sent to Google must be an IANA name** (`Asia/Kolkata`), never
   `str(tzinfo)`, which yields the invalid `UTC+05:30`.
4. **`GEMINI_API_KEY` never reaches the browser.** The page requests a per-call
   ephemeral token. `AUTH_MODE = 'key'` in `index.html` restores the old direct-key path
   — debugging only, never the shipped default.
5. **Tokens are minted WITHOUT `liveConnectConstraints`.** A constrained token routes
   to `BidiGenerateContentConstrained`, which is reported to ignore the setup message's
   `systemInstruction` — and ours carries the current date and timezone, so losing it
   breaks every relative date. See
   <https://discuss.ai.google.dev/t/live-api-with-ephemeral-token-ignores-the-system-instruction/113346>
6. **`v1beta`, not `v1alpha`,** on both the WebSocket and `auth_tokens`. Ephemeral
   tokens are a v1beta-only feature.
7. **`inputAudioTranscription` and `outputAudioTranscription` must stay in the setup
   message.** Without them the API sends no transcripts and the transcript pane is dead,
   even though the handler code looks correct.
8. **CORS is pinned to `FRONTEND_URL`.** Open CORS plus an unauthenticated bridge meant
   any tab in the browser could book on the host's real calendar.
9. **Tool names go through the `TOOL_ENDPOINTS` allowlist.** The original two-way
   ternary silently routed any unrecognised tool to `book_meeting`.
10. **Event ids are never spoken.** They are internal handles for the write tools;
    system prompt rule 7 forbids reading them aloud.
11. **Events marked Free (`transparency: transparent`) and all-day events do not block
    a timed slot.** Otherwise Diwali blocks the whole day.
12. **Writes are two-phase, enforced server-side.** `propose_change` issues a single-use
    code; the three write tools accept nothing but that code, with their arguments frozen
    at proposal time. The prompt also asks the model to confirm with the user, but by the
    same reasoning as invariant 1 that cannot be the only guard — and freezing the args
    means the model cannot propose one change and execute another. Codes live in an
    in-process dict and die with the process, which is correct: an unconfirmed proposal
    should not outlive its conversation.
13. **The prompt and tool schemas live in `session_config.json`, not in the page.**
    The browser fetches it and `evals/run_evals.py` loads it, so an eval always scores
    the text that actually ships. A copy in two places would let the eval pass green
    while the agent drifted — worse than having no eval at all.

## Tools exposed to the model

`check_availability(date)` → that day's events **with ids** ·
`find_free_slots(date, duration_minutes)` ·
`propose_change(action, …)` → summary + `confirmation_code` ·
`book_meeting(confirmation_code)` ·
`reschedule_meeting(confirmation_code)` ·
`cancel_meeting(confirmation_code)`

`propose_change` takes `action` (`book` | `cancel` | `reschedule`) plus the fields that
action needs: `title`, `date_time`, `duration_minutes`, `guest_email` for a booking;
`event_id` for a cancellation; `event_id` and `new_date_time` for a reschedule. Only
`action` is required — a solo meeting simply omits `guest_email` rather than inventing one.

Adding a tool means three edits: the function in `calendar_tool.py`, a route in
`api_server.py`, and a `functionDeclarations` entry in `session_config.json` — the
browser's allowlist is derived from that list, so it cannot fall out of step. Add a
prompt rule there too if the tool's use needs sequencing, and a case in
`evals/cases.json` if the sequencing is the point.

## Env vars (`.env`, gitignored; `.env.example` is the template)

`GOOGLE_CLIENT_ID` · `GOOGLE_CLIENT_SECRET` · `GOOGLE_REDIRECT_URI` ·
`HOST_CALENDAR_ID` · `HOST_EMAIL` · `FRONTEND_URL` · `SECRET_KEY` (unused) ·
`GEMINI_API_KEY` · `HOST_TIMEZONE` · `MEETING_MINUTES` · `WORK_START_HOUR` ·
`WORK_END_HOUR` · `BRIDGE_TOKEN` (optional; set it in `index.html` too) ·
`TOKEN_TTL_MINUTES` · `SESSION_START_WINDOW_MINUTES`

## Known gotchas

- `GEMINI_LIVE_MODEL` in `index.html` is a **preview** name and rotates. An instantly
  closing socket (1007/1008) usually means it is stale — check `/api/live_models`.
- `ScriptProcessorNode` is deprecated; `AudioWorklet` is the modern replacement. Working
  but dated.
- The venv is intentionally absent from this folder (the original's was 118 MB).
- Not a git repo yet. `.gitignore` already covers `.env`, `token.json`, `venv/`,
  `__pycache__/` — initialise **before** the first commit so the real credentials never
  enter history. The OAuth client secret has sat in a Downloads folder; rotating it is
  wise regardless.
- Mic access needs `http://localhost`, not a `file://` path, and HTTPS anywhere else.
- `WORK_HOURS` in `index.html` is a second copy of `WORK_START_HOUR` / `WORK_END_HOUR`
  from `.env`. It only drives the orb's day dial, so a mismatch misdraws the dial
  rather than breaking booking — but change both.

## Next, in order

1. Deploy the bridge to Cloud Run for a real HTTPS demo URL.
2. Proxy the Live WebSocket through the bridge, so session config is enforced
   server-side (also the confirmed workaround for invariant 5).
3. Multi-participant scheduling via the Calendar `freeBusy` API.
4. Answer real phone calls with Twilio Media Streams (µ-law 8 kHz ↔ 16 kHz resampling
   is the hard part).
5. Record a 60-second demo video for the README — an unrecorded voice project is
   effectively invisible to anyone reviewing it.

## Working preferences

Portfolio project aimed at Generative-AI / AI-application engineering roles, so
interview-defensibility counts: prefer the correct-and-explainable approach over the
quick one, and keep the reasoning in comments where a choice looks odd. No fabricated
capabilities in the README. Don't add integrations for their own sake — one feature
that the codelab did not have beats four that it did.
