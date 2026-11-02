# AstraVoice: Confirmed Bugs, Defects & Resolutions Log

**Project:** AstraVoice  
**Audit Cycle:** Master Engineering Audit & Autonomous Repair  
**Status:** All Confirmed Defects Resolved and Verified  

---

## 1. Summary of Defects

| Defect ID | Category | Severity | File(s) Affected | Status |
|:---:|---|:---:|---|:---:|
| **DEF-001** | Cloud Run / Deployment | **HIGH** | `api_server.py`, `Dockerfile` | **FIXED** |
| **DEF-002** | Input Validation / Crash | **MEDIUM** | `api_server.py` | **FIXED** |
| **DEF-003** | Business Logic / Scheduling | **MEDIUM** | `calendar_tool.py` | **FIXED** |
| **DEF-004** | Arithmetic / Duration | **LOW** | `calendar_tool.py` | **FIXED** |
| **DEF-005** | Enterprise Security / CORS | **MEDIUM** | `api_server.py`, `.env.example` | **FIXED** |
| **DEF-006** | Frontend Config & Model Drift | **MEDIUM** | `index.html` | **FIXED** |
| **DEF-007** | Concurrency / Token Collision | **LOW** | `calendar_tool.py` | **FIXED** |
| **DEF-008** | Documentation / Demo Mismatch | **LOW** | `DEMO.md`, `README.md` | **FIXED** |

---

## 2. Detailed Root Cause Analysis & Resolutions

### DEF-001: Missing Standard `/health` Route Causing Container Deployment Failures
- **Severity:** HIGH
- **Component:** Backend / Cloud Run Health Probes
- **Root Cause:** Standard Cloud Run liveness/startup probes ping `GET /health` or `GET /`. `api_server.py` only registered `GET /api/health`. Requests to `/health` resulted in HTTP 404/503. Additionally, when `BRIDGE_TOKEN` was enabled, the `require_bridge_token` hook blocked health check requests lacking the `X-Bridge-Token` header.
- **Resolution:**
  1. Registered `@app.get("/health")` and `@app.get("/api/health")` in `api_server.py`.
  2. Exempted `/health`, `/api/health`, `/`, and `/session_config.json` from `BRIDGE_TOKEN` requirements.
  3. Added a standard Python-based container `HEALTHCHECK` directive in `Dockerfile`.

### DEF-002: Unhandled `ValueError` on Non-Integer Duration Inputs
- **Severity:** MEDIUM
- **Component:** API Bridge Endpoints (`/api/find_free_slots`, `/api/propose_change`)
- **Root Cause:** Direct cast `int(data.get("duration_minutes") or 0)` threw an unhandled `ValueError` when receiving non-numeric strings (e.g. `"thirty"`, malformed JSON, or non-scalar types), causing an unhandled HTTP 500 error.
- **Resolution:**
  Implemented `_safe_int(val, default=0)` helper with robust exception suppression and default fallback.

### DEF-003: Past Date Scheduling Permitted in Calendar Proposals
- **Severity:** MEDIUM
- **Component:** Calendar Business Logic (`calendar_tool.py`)
- **Root Cause:** `propose_change` and `reschedule_meeting` validated boundary overlaps against existing calendar events, but did not check if the requested datetime was in the past. An agent could propose and commit a meeting in 2020 if no conflicting events existed on that date.
- **Resolution:**
  Added `_is_in_past(dt)` check in `propose_change`, `book_meeting`, and `reschedule_meeting`. When `ENFORCE_FUTURE_DATES=true`, past dates return a clean conversational refusal asking the caller for a future time slot.

### DEF-004: Negative Duration Corruption in Free Slot Finder
- **Severity:** LOW
- **Component:** Calendar Free Slot Math (`find_free_slots`)
- **Root Cause:** If `duration_minutes` was passed as a negative value (e.g. `-15`), `duration = duration_minutes or MEETING_MINUTES` retained `-15`. Consequently, `s - cursor >= timedelta(minutes=-15)` evaluated to `True` for every block boundary.
- **Resolution:**
  Added duration clamp `duration = duration_minutes if duration_minutes > 0 else MEETING_MINUTES`. Added sanity bounds on `WORK_START_HOUR` and `WORK_END_HOUR`.

### DEF-005: Insecure CORS Wildcard Overriding Configured Origins
- **Severity:** MEDIUM
- **Component:** Security / API Bridge (`api_server.py`)
- **Root Cause:** `DEFAULT_ALLOWED_ORIGINS` was computed from `FRONTEND_URL`, but line 60 unconditionally called `CORS(app, resources={r"/api/*": {"origins": "*"}})`, opening API bridge endpoints to all origins.
- **Resolution:**
  Configured Flask-CORS to honor `ALLOWED_ORIGINS` by default, with optional `CORS_ORIGINS` environment variable configuration for production environments.

### DEF-006: Hardcoded Live Model Name & Relative Config Fetching in Frontend
- **Severity:** MEDIUM
- **Component:** Frontend WebSocket Client (`index.html`)
- **Root Cause:** `index.html` fetched `session_config.json` via relative path, failing if accessed from another port (e.g. port 8000). Furthermore, `GEMINI_LIVE_MODEL` was hardcoded; if Google rotated preview model availability on the user's API key, the WebSocket disconnected immediately with code 1007/1008.
- **Resolution:**
  1. Updated config request to `${BRIDGE_URL}/session_config.json`.
  2. Implemented dynamic Live model negotiation during `loadSessionConfig()`, querying `${BRIDGE_URL}/api/live_models` to resolve the best active model supported by the server's key pool with graceful fallback.

### DEF-007: Lack of Confirmation Code Collision Check
- **Severity:** LOW
- **Component:** Two-Phase Commit Manager (`calendar_tool.py`)
- **Root Cause:** `secrets.token_hex(4)` generated 8-character hex strings without verifying uniqueness against existing active proposals in `_PENDING`.
- **Resolution:**
  Added collision avoidance loop `while code in _PENDING: code = secrets.token_hex(4)` inside `_issue`.

### DEF-008: Port Discrepancy in Demo Guide
- **Severity:** LOW
- **Component:** Documentation (`DEMO.md`)
- **Root Cause:** `DEMO.md` instructed users to open `http://localhost:8000` (which is the one-time `auth_server.py` port), whereas the AstraVoice unified interface runs on `http://localhost:5000` (`api_server.py`).
- **Resolution:**
  Updated `DEMO.md` step 3 to reference `http://localhost:5000`.

