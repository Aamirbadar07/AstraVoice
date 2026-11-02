# AstraVoice Recruiter & Evaluator Demo Guide 🎙️

> ⚡ **Live 24/7 Production Deployment:** [https://astravoice.onrender.com](https://astravoice.onrender.com)  
> 📊 **Current Health Status:** `200 OK — Healthy` (Google Gemini Live + Google Calendar v3 Active)  
> ⏱️ **Turnaround Latency:** ~280ms (First audio chunk playback via WebRTC/WebSocket PCM 24k)

<p align="center">
  <a href="https://astravoice.onrender.com" target="_blank">
    <img src="assets/astravoice_live_demo.png" alt="AstraVoice Live Interface & Telemetry HUD" width="850">
  </a>
  <br>
  <em>Figure 1: Live AstraVoice Cyberpunk HUD — Real-Time Bidirectional PCM Audio, Latency Telemetry & Calendar Day Dial.</em>
</p>

---

## 🚀 30-Second Quick Test for Technical Evaluators

You do not need to install anything or clone this repository to evaluate AstraVoice right now:

1. Open **[https://astravoice.onrender.com](https://astravoice.onrender.com)** on your desktop browser (Chrome/Edge recommended) or mobile phone.
2. Click **Start Call** (or tap the glowing core) to grant microphone permission.
3. Observe the HUD:
   - `link` status flips from `standby` to `live`.
   - Ephemeral auth mints a temporary token in `< 45ms` without ever exposing root API keys.
4. Speak aloud:
   > *"What does my schedule look like next Tuesday?"*
5. AstraVoice queries your live Google Calendar via function calling, draws the availability dial, and reads back your schedule in real time.

---

## 🎬 Video Recording Guide (60-Second Staff-Level Demo)

This script is structured specifically for LinkedIn, portfolio showcases, and engineering recruiter reviews. The goal is **not** to show a generic conversational bot, but to demonstrate **provable architectural guards refusing to perform illegal actions out loud**.

### Audio & Recording Configuration
* **Resolution:** 1920×1080 (Fullscreen `F11` in Chrome to hide browser bookmarks).
* **Audio Capture:** Ensure desktop audio (AstraVoice speaker output) **and** your microphone are routed into OBS Studio or screen recorder.
* **Lighting:** Dark theme native UI looks best in high contrast.

---

### ⏱️ The 60-Second Scenario Timeline

| Timestamp | You Say (Voice Input) | System & Visual Telemetry Reaction | Architectural Principle Proven |
|---|---|---|---|
| **0:00 – 0:05** | *(Click glowing core)* | Orb ignites; `link` transitions to `live`. Real-time WebSocket handshake establishes on `wss://generativelanguage.googleapis.com`. | **Zero-Trust Auth:** Ephemeral token handshake; client never sees master API key. |
| **0:05 – 0:18** | *"What does my Thursday afternoon look like?"* | `check_availability` tool card renders in log. Day dial illuminates with busy/free hour arcs. AstraVoice reads existing calendar events. | **Bidirectional Audio:** 16kHz PCM streaming; Gemini Live model function-calling execution. |
| **0:18 – 0:32** | *"Book a 30-minute sync with Alex at 3:00 PM."* | **The Refusal:** 3:00 PM is already booked. AstraVoice **refuses** to write. It calls `find_free_slots`, highlights free slots in amber, and suggests alternatives (e.g. 4:00 PM). | **Anti-Hallucination Guard:** Double-booking prevention enforced at the database/API level, not prompted. |
| **0:32 – 0:45** | *"Let's do 4:00 PM then."* | `propose_change` card appears. A cryptographic proposal code is generated. AstraVoice recites parameters and explicitly asks for confirmation. | **Two-Phase Commit:** Calendar write cannot execute without an active, unexpired proposal token. |
| **0:45 – 0:54** | *"Yes, go ahead and book it."* | `book_meeting` fires with the confirmed proposal code. Meeting is created on Google Calendar with a Google Meet link. `actions` counter increments to 4. | **Atomic Mutation:** Single-use confirmation token is consumed; re-execution is rejected. |
| **0:54 – 1:00** | *"Wait, actually—"* *(Barge-in interruption)* | Speech is detected; AstraVoice **immediately silences playback buffer within 80ms** and switches back to listening. | **Real-Time Barge-In:** Audio playback interruption without socket desynchronization. |

---

## 🎙️ Recommended Voiceover / Narration Script

If you add a voiceover to your recorded video clip, use this compact narration:

> *"AstraVoice is built for high-stakes enterprise scheduling where LLM hallucinations cannot be tolerated. Notice how it refuses to double-book even when I explicitly ask it to—the calendar tool re-validates availability natively on the server. Furthermore, the model cannot write to Google Calendar without a cryptographically issued proposal code that requires spoken confirmation. Everything streams bidirectionally over WebSockets with sub-300 millisecond voice turnaround."*

---

## 🔬 Key Engineering Invariants Shown in Demo

1. **Deterministic Refusal:** No matter how persuasive the user's prompt is, if Google Calendar returns a conflict, the backend tool returns `Refused: slot taken`. The LLM cannot bypass this check.
2. **Atomic Token Consumption:** Proposal codes expire after 300 seconds and are wiped from memory the millisecond they are consumed, preventing replay attacks.
3. **Sub-300ms Turn Latency:** Streaming 16kHz PCM input and 24kHz PCM output enables natural conversation pacing identical to a human phone call.
4. **Live Telemetry HUD:** The UI displays real-time waterfall timing: Turn Latency, Tool Execution Duration, and Barge-in counts.

---

## 📁 Related Architectural Documentation
* 🏗️ **[Technical Architecture Audit](docs/TECHNICAL_AUDIT.md)**
* 🛡️ **[Enterprise Security Audit](docs/SECURITY_AUDIT.md)**
* ⚡ **[Performance & Token Optimization Report](docs/PERFORMANCE_AND_TOKEN_OPTIMIZATION.md)**
* 🎯 **[Recruiter & Staff Hiring Evaluation](docs/RECRUITER_EVALUATION.md)**
