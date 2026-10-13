"""
run_evals.py - does the agent pick the right tool?

tests/test_calendar_logic.py proves the calendar maths. Nothing proved the
part that actually decides things: the model. This replays scripted
conversations through the regular generateContent endpoint using the SAME
system prompt and tool schemas the browser ships (session_config.json), and
scores the tool call that comes back.

Text, not Live: the Live API needs a socket and a microphone, but tool choice
is driven by the prompt and the declarations, which are identical in both. So
this catches the regressions that matter - a prompt edit that breaks the
two-phase write, a model version that stops calling check_availability first -
without recording audio.

    python evals/run_evals.py                 # all cases
    python evals/run_evals.py --verbose       # show the model's reasoning text
    EVAL_MODEL=models/gemini-flash-latest python evals/run_evals.py

Needs GEMINI_API_KEY in .env. Exits non-zero if any case fails, so it can gate
a commit.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("GEMINI_API_KEY", "")
BASE = "https://generativelanguage.googleapis.com/v1beta"

# A fixed "today" so relative dates in the cases are deterministic. The real
# page passes the live clock; here we pin it, or "tomorrow" would mean a
# different date every run and every case would rot within a day.
REFERENCE_DATE = "Tue Oct 20 2026 09:00:00 GMT+0530 (India Standard Time)"
REFERENCE_TZ = "Asia/Kolkata"
REFERENCE_OFFSET = "+05:30"


# ───────────────────────── config ─────────────────────────

def load_contract():
    """The exact prompt and schemas index.html ships."""
    config = json.loads((ROOT / "session_config.json").read_text(encoding="utf-8"))
    prompt = (
        config["systemPrompt"]
        .replace("{now}", REFERENCE_DATE)
        .replace("{timezone}", REFERENCE_TZ)
        .replace("{utcOffset}", f"UTC{REFERENCE_OFFSET}")
        .replace("{offsetSuffix}", REFERENCE_OFFSET)
    )
    return prompt, config["functionDeclarations"]


def pick_model():
    """Preview model names rotate, so ask the key what it can use today."""
    override = os.getenv("EVAL_MODEL")
    if override:
        return override

    resp = requests.get(f"{BASE}/models", headers={"x-goog-api-key": API_KEY}, timeout=20)
    resp.raise_for_status()
    usable = [
        m["name"]
        for m in resp.json().get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    # Prefer a cheap flash model; these runs are short and there are a dozen.
    for want in ("flash-latest", "flash"):
        for name in usable:
            if want in name and "live" not in name and "image" not in name:
                return name
    if not usable:
        raise SystemExit("This key cannot use generateContent on any model.")
    return usable[0]


# ───────────────────────── replay ─────────────────────────

def build_contents(turns):
    """Turn a case's script into Gemini `contents`."""
    contents = []
    for turn in turns:
        if "user" in turn:
            contents.append({"role": "user", "parts": [{"text": turn["user"]}]})
        elif "model" in turn:
            contents.append({"role": "model", "parts": [{"text": turn["model"]}]})
        elif "tool" in turn:
            # A call the model already made, and what the bridge replied.
            contents.append({
                "role": "model",
                "parts": [{"functionCall": {"name": turn["tool"], "args": turn.get("args", {})}}],
            })
            contents.append({
                "role": "user",
                "parts": [{"functionResponse": {
                    "name": turn["tool"],
                    "response": {"output": turn["result"]},
                }}],
            })
        else:
            raise ValueError(f"turn has no user/model/tool key: {turn}")
    return contents


def ask(model, prompt, declarations, turns):
    """Returns (function_call_or_None, text)."""
    body = {
        "systemInstruction": {"parts": [{"text": prompt}]},
        "contents": build_contents(turns),
        "tools": [{"functionDeclarations": declarations}],
        # Deterministic enough to compare runs; tool choice should not be a
        # coin flip in the first place.
        "generationConfig": {"temperature": 0},
    }
    resp = requests.post(
        f"{BASE}/{model}:generateContent",
        headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    candidates = resp.json().get("candidates") or []
    parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
    call = next((p["functionCall"] for p in parts if "functionCall" in p), None)
    text = " ".join(p["text"] for p in parts if "text" in p).strip()
    return call, text


# ───────────────────────── scoring ─────────────────────────

def check_args(expected, actual):
    """Returns a list of failure strings. Empty means the arguments are fine."""
    problems = []
    for key, want in (expected or {}).items():
        if key.endswith("_starts_with"):
            field = key[: -len("_starts_with")]
            got = str(actual.get(field, ""))
            if not got.startswith(want):
                problems.append(f"{field}={got!r} does not start with {want!r}")
        elif key.endswith("_absent"):
            field = key[: -len("_absent")]
            if actual.get(field):
                problems.append(f"{field} should be absent, got {actual[field]!r}")
        else:
            got = actual.get(key)
            # The API returns numbers as floats; compare by value.
            if isinstance(want, (int, float)) and isinstance(got, (int, float)):
                if float(got) != float(want):
                    problems.append(f"{key}={got}, expected {want}")
            elif got != want:
                problems.append(f"{key}={got!r}, expected {want!r}")
    return problems


def score(case, call):
    if call is None:
        return [f"no tool was called (expected {case['expect']})"]

    name = call.get("name", "")
    args = call.get("args") or {}

    if name in (case.get("forbid") or []):
        return [f"called {name}, which this case forbids"]
    if name != case["expect"]:
        return [f"called {name}, expected {case['expect']}"]
    return check_args(case.get("args"), args)


def selftest():
    """Check the scoring itself, offline. A harness that scores wrongly is
    worse than no harness: it reports green while the agent misbehaves."""
    prompt, declarations = load_contract()
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    names = {d["name"] for d in declarations}

    checks = [
        ("the prompt has no placeholders left", "{" not in prompt),
        ("every case expects a real tool", all(c["expect"] in names for c in cases)),
        ("every forbidden tool is a real tool",
         all(f in names for c in cases for f in c.get("forbid", []))),
        ("a matching call passes",
         not score({"expect": "book_meeting", "args": {"confirmation_code": "a1"}},
                   {"name": "book_meeting", "args": {"confirmation_code": "a1"}})),
        ("a wrong tool fails",
         bool(score({"expect": "check_availability"}, {"name": "book_meeting", "args": {}}))),
        ("a forbidden tool fails",
         bool(score({"expect": "check_availability", "forbid": ["book_meeting"]},
                    {"name": "book_meeting", "args": {}}))),
        ("no tool call at all fails",
         bool(score({"expect": "check_availability"}, None))),
        ("a wrong argument fails",
         bool(score({"expect": "book_meeting", "args": {"confirmation_code": "a1"}},
                    {"name": "book_meeting", "args": {"confirmation_code": "zz"}}))),
        ("_starts_with compares prefixes",
         not check_args({"date_starts_with": "2026-10-21"}, {"date": "2026-10-21T15:00:00+05:30"})
         and bool(check_args({"date_starts_with": "2026-10-21"}, {"date": "2026-10-22"}))),
        ("_absent catches an invented value",
         not check_args({"guest_email_absent": True}, {})
         and bool(check_args({"guest_email_absent": True}, {"guest_email": "a@b.c"}))),
        ("a float from the API matches an int expectation",
         not check_args({"duration_minutes": 60}, {"duration_minutes": 60.0})),
        ("a tool turn replays as call plus response",
         len(build_contents([{"tool": "check_availability", "args": {}, "result": "free"}])) == 2),
    ]

    failed = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        failed += not ok
    print(f"\n{len(checks) - failed}/{len(checks)} passed (offline self-test, no model calls)")
    return 1 if failed else 0


def main():
    verbose = "--verbose" in sys.argv

    if "--selftest" in sys.argv:
        return selftest()

    if not API_KEY:
        print("GEMINI_API_KEY is not set in .env - add it and run again.")
        return 2

    prompt, declarations = load_contract()
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]

    model = pick_model()
    print(f"model: {model}")
    print(f"today in the prompt: {REFERENCE_DATE}\n")

    failed = 0
    for case in cases:
        try:
            call, text = ask(model, prompt, declarations, case["turns"])
            problems = score(case, call)
        except Exception as exc:
            call, text, problems = None, "", [f"request failed: {exc}"]

        print(f"  {'PASS' if not problems else 'FAIL'}  {case['name']}")
        for problem in problems:
            print(f"          {problem}")
        if verbose:
            if call:
                print(f"          -> {call.get('name')}({json.dumps(call.get('args') or {})})")
            if text:
                print(f"          said: {text[:160]}")
        failed += bool(problems)

    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
