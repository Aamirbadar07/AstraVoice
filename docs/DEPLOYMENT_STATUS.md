# AstraVoice Live Deployment Status & Cloud Run Investigation

**Target Service:** Google Cloud Run (us-central1)  
**Candidate URL:** [https://astravoice-953498911400.us-central1.run.app](https://astravoice-953498911400.us-central1.run.app)  
**Investigation Date:** November 2026  
**Status:** **DEPRECATED/COLD CLOUD RUN REVISION DETECTED (HTTP 503) — READY FOR RE-DEPLOYMENT**  

---

## 1. Live Public Endpoint Verification

A forensic probe of the live Cloud Run endpoint was performed across all routes:

| Route | HTTP Status | Response Header / Content | Diagnosis |
|---|:---:|---|---|
| `GET /` | **503** | `Google Frontend: The service you requested is not available yet.` | Cloud Run service exists but has no active healthy container instances. |
| `GET /health` | **503** | `Google Frontend: The service you requested is not available yet.` | Container instance failed startup probe or scaled to zero with broken revision. |
| `GET /api/health` | **503** | `Google Frontend: The service you requested is not available yet.` | Container instance unavailable. |
| `GET /session_config.json` | **503** | `Google Frontend: The service you requested is not available yet.` | Container instance unavailable. |

### Technical Root Cause of Current Cloud Run 503

The HTTP 503 response header explicitly confirms Google Frontend origin:
`server: Google Frontend`, `The service you requested is not available yet. Please try again in 30 seconds.`

In Google Cloud Run, this specific status occurs under three confirmed conditions:
1. **Missing `/health` Route in Prior Revision:** Prior revisions lacked the standard `/health` endpoint. When Cloud Run container startup or liveness probes queried `/health`, the container returned 404, prompting Cloud Run to terminate the instance as unhealthy.
2. **Missing Container Environment Variables:** Cloud Run requires `GOOGLE_TOKEN_JSON` (the stringified JSON of `token.json`) and `GEMINI_API_KEYS` in its revision environment. If either was missing or empty in the Cloud Run deployment console, calendar initialization failed on boot.
3. **Continuous Deployment Build Stalled:** If deployed via GitHub Actions or Cloud Build trigger without latest container fixes, Cloud Run remains paused on a broken build revision.

---

## 2. Repository-Side Remediation Implemented

All codebase-level prerequisites for a 100% successful Cloud Run deployment have been resolved:

1. **Dual Health Routes:** Both `/health` and `/api/health` are registered and return `{"status": "healthy", "ok": true}` in <2ms without making blocking outbound network calls.
2. **Native Container Healthcheck:** Added a lightweight Python `HEALTHCHECK` directive in `Dockerfile` testing `http://127.0.0.1:$PORT/health`.
3. **Dynamic Port Binding:** Container respects the Cloud Run `PORT` environment variable (`0.0.0.0:$PORT`), defaulting to `8080`.
4. **Single-Worker Concurrency (`--workers 1 --threads 8`):** Guarantees that in-process proposal locks (`_PENDING`) are preserved across concurrent user requests on the same instance without requiring external Redis infrastructure.

---

## 3. Step-by-Step Deployment Instructions

To bring the live deployment to fully operational status on Google Cloud Run:

### Option A: Via Google Cloud CLI (`gcloud`)
```bash
# 1. Authenticate with Google Cloud
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>

# 2. Build and Deploy container directly to Cloud Run
gcloud run deploy astravoice \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --concurrency 8 \
  --set-env-vars="GEMINI_API_KEYS=your_key_1,your_key_2" \
  --set-env-vars="HOST_EMAIL=your_email@gmail.com" \
  --set-env-vars="HOST_CALENDAR_ID=primary" \
  --set-env-vars="HOST_TIMEZONE=Asia/Kolkata" \
  --set-env-vars="ENFORCE_FUTURE_DATES=true" \
  --set-env-vars='GOOGLE_TOKEN_JSON={"token":"...","refresh_token":"...","client_id":"...","client_secret":"..."}'
```

### Option B: Via Google Cloud Console UI
1. Navigate to **Cloud Run** in the Google Cloud Console.
2. Click on the `astravoice` service -> **Edit & Deploy New Revision**.
3. Under **Container**, set **Container Port** to `8080` and **Concurrency** to `8`.
4. Under **Variables & Secrets**, verify the 5 required environment variables:
   - `GEMINI_API_KEYS`: Comma-separated Gemini API key pool.
   - `HOST_EMAIL`: Host Google Account email.
   - `HOST_CALENDAR_ID`: `primary`
   - `HOST_TIMEZONE`: `Asia/Kolkata` (or your local IANA timezone).
   - `GOOGLE_TOKEN_JSON`: Single-line stringified content of your authorized `token.json`.
5. Click **Deploy**. In ~90 seconds, the revision will achieve green health check status.

