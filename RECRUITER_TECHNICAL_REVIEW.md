# AstraVoice: Comprehensive Technical Review & Latency Telemetry Report

**Author:** Aamir Badar  
**Repository:** [Aamirbadar07/AstraVoice](https://github.com/Aamirbadar07/AstraVoice)  
**Target Platform:** Google Cloud Run (Containerized Linux / Python 3.11 / Flask / WebSockets)  
**Model Stack:** Google Gemini 2.0 / 3.1 Live Flash Preview (`models/gemini-3.1-flash-live-preview`)  
**Status:** Production Ready (19/19 Unit Tests Passing, 12/12 Eval Tests Passing)

---

## 1. Executive Summary: Why AstraVoice Stands Out

Most voice AI projects built for portfolios fall into the **"Toy Wrapper"** category:
- They daisy-chain three slow HTTP requests: **Microphone -> Whisper API (STT) -> OpenAI ChatCompletion -> ElevenLabs (TTS) -> Speaker**. This results in a jarring **3,000ms – 5,000ms latency**, zero natural turn-taking, and robotic interactions.
- They have no safety guards on stateful actions: LLMs hallucinate booking dates, double-book slots, or overwrite calendar events without user confirmation.
- They leak production API secrets into the browser frontend.

**AstraVoice** solves each of these real-world distributed systems and real-time voice challenges:

| Architectural Dimension | Typical Junior Project (Wrapper) | AstraVoice (Enterprise Caliber) |
| :--- | :--- | :--- |
| **Streaming Architecture** | Multi-hop serial HTTP (STT -> LLM -> TTS) | Single persistent bi-directional **WebSocket** using Gemini Live API |
| **Audio Pipeline** | WAV file post-processing buffers | Gapless raw **16kHz PCM (mic in)** and **24kHz PCM (audio out)** chunking |
| **Turn-Taking & Interruption** | Blocking audio playback; robot talks over user | **Hardware-level Barge-In**: instant playback interruption & queue flush (<25ms) |
| **State Mutation Safety** | Direct prompt-to-database writes (hallucination prone) | **Two-Phase Commit (2PC)**: temporary in-memory lock + 8-char confirmation token |
| **Credential Security** | `GEMINI_API_KEY` exposed in browser JS or `.env` in Git | **Zero-Leak Bridge**: server mints single-use ephemeral tokens (`auth_tokens/...`) |
| **Fault Tolerance** | Single API key failure halts system | **Multi-Key Pool**: automatic round-robin & sub-5ms failover on HTTP 429 |
| **Observability** | Invisible backend or `console.log` | **Glassbox Telemetry HUD**: live TTFB timer, audio waterfall, & step status |

---

## 2. Empirical Performance & Latency Telemetry

Benchmark tests were run live against Google Cloud APIs and local container infrastructure:

```
===================================================================
       AstraVoice Live Empirical Latency & Performance Audit       
===================================================================
[OK] 1. API Bridge Health Check
    - Roundtrip Latency  : avg=3.18ms (min=2.34ms, max=5.17ms)
    - Key Rotation Pool  : 2 active keys in pool
    - Memory Overhead    : ~62 MB idle / ~95 MB active

[OK] 2. Gemini Live Ephemeral Token Minting (Google GenerativeLanguage API)
    - Roundtrip Latency  : avg=732.77ms (min=470.81ms, max=839.08ms)
    - Security Guarantee : Ephemeral single-session token (30 min TTL)
    - Failover Overhead  : < 5ms in-memory rotation on 429 quota exhaustion

[OK] 3. Calendar Tool Execution: find_free_slots (Real Google Calendar OAuth2 API)
    - Roundtrip Latency  : avg=1,272.47ms (min=885.27ms, max=1,936.03ms)
    - Conflict Scan Area : 09:00 - 18:00 host workday in target timezone

[OK] 4. Two-Phase Locking / Proposal Token Issuance (propose_change)
    - Execution Latency  : 852.58ms (includes calendar pre-flight verification)
    - Atomic Lock Token  : 8-character single-use alphanumeric code
===================================================================
```

### End-to-End Voice Latency Breakdown (The "Waterfall")

```
User Stops Speaking
 │
 ├── [0ms - 20ms]      Browser AudioWorklet detects VAD speech boundary
 ├── [20ms - 40ms]     WebSocket frame dispatched to Gemini Live
 ├── [40ms - 520ms]    Gemini Live native speech inference & streaming generation
 │                      └── TTFB (Time to First Audio Byte): ~480ms - 650ms
 ├── [520ms - 530ms]   Browser Web Audio API schedules 24kHz PCM buffer
 ▼
Speaker Outputs First Syllable (Total perceived turn-around: ~550ms - 700ms)
```

---

## 3. The 4 Golden Demo Scenarios for Recruiters

### Scenario 1: Natural Availability Discovery
* **User says:** *"Hi, what does your schedule look like next Tuesday?"*
* **AstraVoice response:** Searches Google Calendar via `find_free_slots` and speaks only the open windows (e.g., *"On Tuesday, October 20th, I am free between 9:00 AM and 11:00 AM, and again from 12:00 PM to 6:00 PM."*).
* **Under the Hood:** Rule 3 prevents reading busy events aloud; timezone math handles offset normalization.

### Scenario 2: Overlap Rejection & Clash Guard
* **User says:** *"Can we do 11:30 AM on Tuesday?"*
* **AstraVoice response:** Detects overlap with existing 11:00–12:00 meeting and refuses: *"11:30 AM conflicts with an existing meeting. Would 12:00 PM or 10:30 AM work better?"*
* **Under the Hood:** `_conflicts` logic verifies boundary conditions (`lo < busy_hi and hi > busy_lo`).

### Scenario 3: Two-Phase Commit Booking with Google Meet
* **User says:** *"Let's book 4:00 PM for 30 minutes to discuss the Engineering Manager role."*
* **AstraVoice response:** *"I have prepared a booking for 'Engineering Manager Interview' on Tuesday, October 20th at 4:00 PM for 30 minutes. Should I go ahead and confirm this?"*
* **User confirms:** *"Yes, please confirm."*
* **AstraVoice response:** Calls `book_meeting` with confirmation code. Generates calendar event with Google Meet link: *"All set! I've booked that for you and added a Google Meet link."*

### Scenario 4: Mid-Sentence Barge-In (Interruption)
* **Action:** While AstraVoice is speaking, speak naturally: *"Wait, hold on, let's make it Wednesday instead."*
* **Result:** Within 25 milliseconds, the assistant cuts off its audio, clears the buffer, and seamlessly adapts to Wednesday.
