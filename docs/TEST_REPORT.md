# AstraVoice Test Execution & Quality Assurance Report

**Execution Date:** November 2026  
**Auditor:** QA & Automation Engineer  
**Overall Status:** **100% PASSING (39/39 Tests Verified)**  

---

## 1. Test Suite Summary

AstraVoice features a multi-tiered test architecture covering deterministic unit arithmetic, HTTP contracts, security controls, multi-turn conversational tool evaluations, and concurrency stress testing.

| Test Suite File | Type | Total Tests | Passed | Failed | Skipped |
|---|---|:---:|:---:|:---:|:---:|
| `tests/test_calendar_logic.py` | Unit / Overlap Arithmetic & Guards | 19 | 19 | 0 | 0 |
| `tests/test_enterprise_suite.py` | Integration / HTTP, Concurrency, Security | 8 | 8 | 0 | 0 |
| `evals/run_evals.py --selftest` | Eval Harness Contract & Scoring | 12 | 12 | 0 | 0 |
| **TOTAL** | — | **39** | **39** | **0** | **0** |

---

## 2. Detailed Test Suite Results

### Suite 1: Calendar Arithmetic & Overlap Protection (`tests/test_calendar_logic.py`)
- **19/19 Passing** — Executed offline without network dependencies using mocked Google Calendar service.
  1. `[PASS]` 11:30 overlaps the 11-12 meeting
  2. `[PASS]` 11:45 straddles its end -> conflict
  3. `[PASS]` 10:45 straddles its start -> conflict
  4. `[PASS]` 12:00 is back-to-back -> allowed
  5. `[PASS]` 10:30 ends as it starts -> allowed
  6. `[PASS]` an event marked Free does not block
  7. `[PASS]` an all-day event does not block 16:00
  8. `[PASS]` reschedule ignoring itself is clear
  9. `[PASS]` a bare date resolves in HOST_TIMEZONE
  10. `[PASS]` free slots skip the busy hour
  11. `[PASS]` a 30-minute booking at 10:30 is clear
  12. `[PASS]` the same slot for 60 minutes is refused
  13. `[PASS]` propose_change issues a confirmation code
  14. `[PASS]` the code it issued carries the duration
  15. `[PASS]` a code works exactly once
  16. `[PASS]` a book code cannot cancel
  17. `[PASS]` an expired code is refused
  18. `[PASS]` a write without a code is refused
  19. `[PASS]` a made-up code is refused

### Suite 2: Enterprise Integration & Security Suite (`tests/test_enterprise_suite.py`)
- **8/8 Passing** — End-to-end API, Concurrency, and Security Validation.
  1. `[PASS]` **API Endpoints & HTTP Contract Tests:** Validates `/health`, `/api/health`, `/`, `/session_config.json`, and all 6 calendar bridge routes.
  2. `[PASS]` **Bridge Token Security Tests:** Validates header verification (`X-Bridge-Token`) with 401 rejection on unauthorized requests and proper exemption for public endpoints.
  3. `[PASS]` **Input Sanitization Tests:** Validates non-integer durations, bad dates, and empty strings.
  4. `[PASS]` **Confirmation Token Lifecycle Tests:** Validates proposal generation, action-binding, replay prevention, and expiration.
  5. `[PASS]` **Concurrency & Race-Condition Tests (50 Workers):** Dispatches 50 concurrent threads simultaneously requesting proposals (verifying 50 unique collision-free codes) and 50 concurrent threads attempting to claim a single proposal code (verifying exactly 1 succeeds and 49 fail).
  6. `[PASS]` **Timezone Math & ISO-8601 Normalization Tests:** Validates bare dates, UTC `Z` strings, and `-05:00` American offset conversions to `Asia/Kolkata`.
  7. `[PASS]` **Past-Date Protection & Refusal Tests:** Validates that meetings in the past are rejected with clean conversational error messages.
  8. `[PASS]` **Deployment Configuration Tests:** Verifies Dockerfile directives, port bindings, and requirements integrity.

### Suite 3: Agent Tool Selection Evaluation (`evals/run_evals.py --selftest`)
- **12/12 Passing** — Offline verification of the prompt-tool contract.
  1. `[PASS]` the prompt has no placeholders left
  2. `[PASS]` every case expects a real tool
  3. `[PASS]` every forbidden tool is a real tool
  4. `[PASS]` a matching call passes
  5. `[PASS]` a wrong tool fails
  6. `[PASS]` a forbidden tool fails
  7. `[PASS]` no tool call at all fails
  8. `[PASS]` a wrong argument fails
  9. `[PASS]` `_starts_with` compares prefixes
  10. `[PASS]` `_absent` catches an invented value
  11. `[PASS]` a float from the API matches an int expectation
  12. `[PASS]` a tool turn replays as call plus response

---

## 3. Live External Evaluator Run Conditions

- Offline evaluation self-test: 12/12 PASSING.
- Live LLM eval replay (`python evals/run_evals.py`): Requires `GEMINI_API_KEY` in `.env`. When executed with valid key credentials, it replays all 12 scripted multi-turn conversations against Google Generative Language API, verifying tool selection accuracy.

