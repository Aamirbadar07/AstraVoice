# NovaVoice 🎙️
**Real-Time Voice AI Booking Assistant – Gemini Live API + Google Calendar**

> Built from the Google Developer Codelab: *Build a Real-Time Voice AI Agent with the Gemini Live API, Antigravity and Google Calendar*

---

## What is NovaVoice?

NovaVoice is a voice assistant you talk to in real-time. It:
- Listens via your microphone using the **Gemini Live API** (bidirectional WebSocket)
- Checks your **Google Calendar** for availability
- **Books meetings by voice** (30-minute events)
- Supports **barge-in**: interrupt the agent mid-sentence, it stops immediately

## Architecture

```
Browser (index.html :8000)
    │  1. POST /api/live_token  ──────────────▶ Python bridge (api_server.py :5000)
    │  2. short-lived token     ◀──────────────┘   (holds GEMINI_API_KEY)
    │
    │  3. WebSocket, audio in/out, authorised by that token
    ▼
Gemini Live API (cloud)
    │  4. toolCall messages
    ▼
Browser routes the call ──▶ Python bridge ──▶ calendar_tool.py ──▶ Google Calendar
```

Neither the Gemini API key nor `token.json` ever reaches the browser. The page
asks the bridge for a single-use Live API token each time a call starts; that
token is valid for one session and expires in minutes.

## Tools the agent can call

| Tool | What it does |
|---|---|
| `check_availability(date)` | Lists that day's events, with ids for the write tools |
| `find_free_slots(date, duration_minutes)` | Real free windows inside working hours |
| `propose_change(action, …)` | Describes an intended change, checks it, returns a single-use `confirmation_code` |
| `book_meeting(confirmation_code)` | Books and emails an invite — **refuses on a clash** |
| `reschedule_meeting(confirmation_code)` | Moves an event, keeping its length — refuses on a clash |
| `cancel_meeting(confirmation_code)` | Deletes an event and notifies guests |

Two things are deliberately not left to the model:

**Clash checks.** Every write re-queries the calendar before it acts. The prompt
asks the model to check availability first, but the tools never depend on it — a
model that skips the check still cannot double-book.

**Confirmation.** Writes are two-phase. `propose_change` validates the change and
issues a single-use code; the write tools accept that code and nothing else, with
the arguments frozen at proposal time. So the model cannot book without having
first described the booking, and cannot describe one change and then execute a
different one. The prompt still asks it to get a spoken yes from the user — but
the guard does not rest on the prompt being obeyed.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Full frontend: HUD, orb and day dial, audio pipeline, WebSocket client, tool router |
| `session_config.json` | The agent's contract: system prompt and tool schemas, read by the page and the evals |
| `api_server.py` | Flask bridge: token minting and one route per tool |
| `calendar_tool.py` | All Google Calendar logic, every time calculation, and the two-phase write guard |
| `auth_server.py` | One-time OAuth flow helper, writes `token.json` |
| `tests/test_calendar_logic.py` | Calendar maths: overlaps, timezones, confirmation codes |
| `evals/run_evals.py` | Agent evals: scores which tool the model picks |
| `DEMO.md` | Shot-by-shot script for the README video |
| `requirements.txt` | Python dependencies |
| `.env` | Your secrets (not committed to Git) |

---

## Setup

### 1. Prerequisites

- Python 3.10+
- Google Chrome (for microphone access)
- A Google account with a Google Calendar
- A Gemini API key (free from [Google AI Studio](https://aistudio.google.com/app/apikey))

### 2. Python Virtual Environment

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows (PowerShell)
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> **macOS tip:** PyAudio requires PortAudio. If pip fails, run `brew install portaudio` first.

### 4. Get a Gemini API Key

1. Open [Google AI Studio → API Keys](https://aistudio.google.com/app/apikey)
2. Click **Create API key** and create / select a Google Cloud project
3. Copy the key into `GEMINI_API_KEY` in your `.env` — **not** into the browser.
   The page never sees it; `api_server.py` exchanges it for short-lived tokens.

### 5. Google Cloud OAuth Setup

#### 5a. Enable the Calendar API
1. Open [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) in the same project
2. Click **Enable**

#### 5b. Configure the OAuth Consent Screen
1. Cloud Console → **APIs & Services → OAuth consent screen**
2. Click **Get started**, set App name to `NovaVoice`, pick your support email
3. Audience: **External** → Next
4. Add your email as Contact Information → Next → Finish → Create

#### 5c. Add Yourself as a Test User
1. Google Auth Platform → **Audience → + Add users**
2. Enter the Gmail address whose calendar NovaVoice should manage

#### 5d. Add the Calendar Scope
1. Google Auth Platform → **Data Access → Add or remove scopes**
2. Manually add: `https://www.googleapis.com/auth/calendar.events`
3. Click **Update** then **Save**

#### 5e. Create an OAuth Client ID
1. Google Auth Platform → **Clients → + Create client**
2. Application type: **Web application**, Name: `Calendar Integration`
3. Authorized JavaScript origins: `http://localhost:8000`
4. Authorized redirect URIs: `http://localhost:8000/auth/callback`
5. Click **Create** and copy the **Client ID** and **Client Secret**

### 6. Create the `.env` File

Create a file named `.env` in the project root:

```env
GOOGLE_CLIENT_ID=your_google_oauth_client_id
GOOGLE_CLIENT_SECRET=your_google_oauth_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
HOST_CALENDAR_ID=your_email@gmail.com
HOST_EMAIL=your_email@gmail.com
FRONTEND_URL=http://localhost:8000
SECRET_KEY=any_random_string_here
HOST_TIMEZONE=Asia/Kolkata
BRIDGE_TOKEN=
```

> `HOST_TIMEZONE` must be an IANA name — all date math and every calendar write
> use it. `BRIDGE_TOKEN` is optional; if you set it, set the matching constant
> in `index.html` too.

### 7. Authorize Google Calendar (one time)

```bash
python3 auth_server.py
```

1. Open `http://localhost:8000` in Chrome
2. Click **Click here to Authorize Google Calendar**
3. Sign in with the test user account
4. Click through the "unverified app" warning (expected for Testing mode)
5. Grant calendar events permission
6. You'll see a success page → `token.json` is saved
7. Press **Ctrl+C** to stop the auth server

---

## Running NovaVoice

You need **two terminals** (both with the virtual environment active):

**Terminal 1 – Calendar API bridge:**
```bash
python3 api_server.py
```

**Terminal 2 – Serve the UI:**
```bash
python3 -m http.server 8000
```

Open **http://localhost:8000** in Chrome and click the 🎙️ button. There is no key
to paste — the page fetches a token from the bridge when the call starts.

Two useful endpoints while debugging:

```bash
curl http://127.0.0.1:5000/api/health        # is the key loaded?
curl http://127.0.0.1:5000/api/live_models   # which Live models can this key use?
```

### Auth modes

`index.html` has `AUTH_MODE`. Leave it on `'ephemeral'`. Setting it to `'key'`
restores the old behaviour, where the browser holds the key and shows the setup
modal — kept only to isolate whether a failure is in token minting or in the
Live session itself.

> Ephemeral tokens are deliberately minted **without** `liveConnectConstraints`.
> A constrained token routes the client to `BidiGenerateContentConstrained`,
> which is [reported to ignore the setup `systemInstruction`](https://discuss.ai.google.dev/t/live-api-with-ephemeral-token-ignores-the-system-instruction/113346) —
> and ours carries the current date and timezone, so losing it breaks every
> relative date like "tomorrow at 3". Locking the config server-side is the
> right end state once that is fixed; the stronger version is proxying the
> WebSocket through the bridge entirely.

### Try it

Say something like:
> "Hi! Can you check if my calendar is free tomorrow afternoon? If it is, please book a NovaVoice demo at 3 PM. My email is demo@example.com."

Watch the transcript, the tool cards, and your Google Calendar!

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No microphone prompt | Open via `http://localhost:8000`, not a file path |
| "Address already in use" on port 8000 | Stop the auth server with Ctrl+C |
| Tool card appears but agent says it can't reach calendar | Ensure `api_server.py` is running and `token.json` exists |
| WebSocket closes right after connecting | Check the API key; open browser DevTools console |
| Agent hears itself | Use headphones |
| Meeting booked at wrong time | Check your computer's timezone is correct |
| Error 403: access_denied | Add your Google account to Test users in the OAuth consent screen |
| Error 400: redirect_uri_mismatch | Make sure `.env` `GOOGLE_REDIRECT_URI` matches exactly what's in your OAuth client |
| "Could not get a session token" | `api_server.py` isn't running, or `GEMINI_API_KEY` is missing from `.env` |
| Socket closes with 1007/1008 right away | Stale `GEMINI_LIVE_MODEL`. Check `/api/live_models` and update the constant |
| Agent says a slot is taken when it looks free | An event marked **Busy** overlaps it. Events marked **Free** and all-day events are ignored |
| Agent reads an event id aloud | Prompt rule 7 covers this; check the system prompt survived (token must be unconstrained) |

---

## Common OAuth Errors

- **Error 400: redirect_uri_mismatch** – URI in `.env` and OAuth client differ (check http vs https, trailing slashes)
- **Error 403: access_denied** – Your account isn't listed under Test users
- **invalid_client** – Client ID or Secret in `.env` is wrong or has stray spaces

---

## Tests and evals

Two different questions, two different harnesses.

```bash
python tests/test_calendar_logic.py    # is the calendar maths right?
python evals/run_evals.py              # does the agent pick the right tool?
```

The first stubs the Google libraries and needs no key, no venv and no network.
It covers the overlap arithmetic, timezone handling, and the two-phase write
guard.

The second replays scripted conversations through Gemini using the *same*
system prompt and tool schemas the browser ships — both read
`session_config.json`, so an eval cannot pass against a stale copy. It scores
the tool the model chooses: that it checks availability before proposing, that a
clash sends it to `find_free_slots` instead of booking anyway, that a confirmed
proposal is written with its own code, and that a changed detail produces a new
proposal rather than reusing the old one. It needs `GEMINI_API_KEY` and makes
one short call per case.

`python evals/run_evals.py --selftest` checks the scoring logic offline, with no
model calls — a harness that scores wrongly is worse than no harness.

## Next Steps

- Deploy the bridge to Cloud Run so the demo has a real HTTPS URL
- Proxy the Live WebSocket through the bridge, so session config is enforced server-side
- Multi-participant scheduling via the Calendar `freeBusy` API
- Answer real phone calls with Twilio Media Streams

## Changes in this version (v2)

| Fix | What it was |
|---|---|
| Transcription enabled in `setup` | The transcript pane could never fill — the API was never asked for transcripts |
| Guests actually invited | `guest_email` became the event *title* and `title` was dropped; no `attendees` was ever sent |
| Timezone-correct day lookups | A bare date was treated as UTC, so "tomorrow" scanned the wrong 24 hours for any non-UTC host |
| Valid IANA `timeZone` on writes | `str(tzinfo)` produced `UTC+05:30`, which is not a zone name |
| Bridge locked to the frontend origin | Open CORS + no auth meant any open tab could book on your calendar |
| OAuth success page renders | Its CSS braces were doubled in a non-f-string, so they printed literally |
| Access token refresh persisted | A refreshed token was never written back to `token.json` |
| Writes re-check the calendar | Nothing stopped a double-booking if the model skipped `check_availability` |
| `cancel_meeting` + `reschedule_meeting` | The agent could only create events, never undo one |
| `find_free_slots` | The prompt promised "the next free slot" with no tool to compute one |
| Gemini key off the client | The key sat in `localStorage` and in the WebSocket URL; now the bridge mints per-session tokens |
| Switched to `v1beta` | `v1alpha` was in use; ephemeral tokens are v1beta-only |
| Tool names allowlisted | The old two-way ternary sent any unrecognised tool to `book_meeting` |

---

## Useful Links

- [Gemini Live API overview](https://ai.google.dev/gemini-api/docs/live)
- [Google AI Studio](https://aistudio.google.com)
- [NovaVoice reference repo](https://github.com/coder-irwin/voice_ai_agents_using-Gemini_live_api)
- [Google Calendar API Python quickstart](https://developers.google.com/calendar/api/quickstart/python)
- [Using OAuth 2.0 to access Google APIs](https://developers.google.com/identity/protocols/oauth2)
