# Recording the demo

A 60-second take for the README. The point is not to show a pretty orb — it is
to show the agent **refusing to do the wrong thing**, twice, out loud. That is
the part a reviewer has not seen in standard toy voice projects.

## Before you press record

Set the stage first, or you will burn takes on an empty calendar.

1. **Seed the day.** Put two real-looking events on the day you will ask about,
   in your own calendar:
   - `Standup`, 11:00–12:00
   - `Design review`, 15:00–15:45

   Leave 09:00–11:00 and 12:00–15:00 free. The script below depends on 11:00
   being taken and 14:00 being free.

2. **Check the model name.** Preview names rotate and a stale one closes the
   socket instantly.

   ```bash
   curl http://127.0.0.1:5000/api/live_models
   ```

   If `GEMINI_LIVE_MODEL` in `index.html` is not in that list, fix it first.

3. **Run both processes**, then open <http://localhost:8000> in Chrome.

4. **Dry-run the whole script once** without recording. The model is not
   deterministic; you want to know how it phrases things before you commit.

5. **Window setup.** 1920×1080, browser in fullscreen (F11) so no bookmarks bar
   or tab strip is in frame. Dark room helps — the page is near-black.

6. **Capture audio.** Record system audio *and* your microphone, or the agent's
   voice is missing from the take. On Windows, OBS with a Desktop Audio source
   plus a Mic source is the reliable option; `Win+Alt+R` (Game Bar) captures
   only one of the two by default.

## The 60 seconds

Times are targets, not a metronome. Say the lines naturally — a stiff read
sounds like a script and undoes the point.

| Time | You say | What should happen on screen |
|---|---|---|
| 0:00–0:05 | *(nothing — click the core)* | Orb at standby, `link` flips to `live`. Hold a beat so the idle animation registers. |
| 0:05–0:18 | "What does my Thursday look like?" | `check_availability` card appears, **the day dial ignites**: red arcs at 11:00 and 15:00. Agent reads the two meetings back. `reply` shows the latency. |
| 0:18–0:33 | "Book an hour with Priya at eleven." | **The refusal.** The slot is taken, so the agent does not book. It calls `find_free_slots`, the dial fills with amber free windows, and it offers a real one. |
| 0:33–0:45 | "Two o'clock then." | `propose_change` card. The agent reads the booking back and asks you to confirm. It does **not** book yet. |
| 0:45–0:52 | "Yes, go ahead." | `book_meeting` fires. Agent confirms. `actions` counter is now 4. |
| 0:52–1:00 | *(nothing)* | Cut to your Google Calendar with the new 14:00 event visible, guest invited. Hold 3 seconds. End. |

## What to say over it, if you add narration later

Keep it to three sentences, because the footage already carries the story:

> It refuses to double-book even when I ask it to — the tool re-checks the
> calendar, it doesn't trust the model. And it won't write anything until I say
> yes out loud; the confirmation is enforced in the backend, not in the prompt.

## If a take goes wrong

- **Agent books without confirming.** Rare now that the write tools require a
  code, but if it happens the tool returns `Refused:` and the agent recovers.
  That is also a fine thing to show — the guard working is the whole point.
- **Agent speaks an event id.** Prompt rule 9 forbids it. Re-take; if it keeps
  happening, that is a real prompt regression and belongs in `evals/cases.json`.
- **Socket closes immediately (1007/1008).** Stale model name. See step 2.
- **Dial stays dark.** `WORK_HOURS` in `index.html` does not match
  `WORK_START_HOUR` / `WORK_END_HOUR` in `.env`, so your events fall outside the
  drawn range.
- **Long silence before the agent replies.** Normal on the first turn — the
  socket is still warming. Start the clip after the first exchange if it drags.

## Shorter cut, if 60 seconds is tight

Drop the Thursday overview (0:05–0:18) and open on the refusal. It loses the
dial ignition but keeps both refusals, which are the parts worth watching.

## After

Export at 1080p, trim to length, and put it at the top of the README above the
architecture diagram — before the setup instructions, not after. A reviewer who
has to scroll past OAuth steps to find the video will not find it.
