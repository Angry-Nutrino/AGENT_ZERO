# Busy-Mode Reports

One report per **busy-mode lifetime** — from the moment Alkama says "use busy-mode" until he explicitly
says "stop busy mode" (which may span many usage windows, with pauses and resumes in between).

## Purpose
This is the **decision / process / lifecycle log** of a busy-mode run, and its main job is **evaluation
of the busy-mode skill itself**. Because Claude (not CLARA) runs the loop and follows the rules, faults
usually live in the *skill* being under-specified about some case — not in the execution. The "which &
why" written before each task is what surfaces those gaps: read it back and you can see exactly where the
skill left Claude unsure or pointed it at the wrong thing. After a lifetime **Ends**, evaluate that report
and refine the skill from what it reveals.

## How this differs from the other logs (it is IN ADDITION, not a replacement)
- **`TIMELINE.md`** — *what changed in the code* (file, location, why). Project tracking. These reports
  **reference** TIMELINE entries; they do not duplicate implementation detail.
- **`BACKLOG.md`** — the queue of pending work.
- **busy-mode-reports/** — *the decisions, the reasoning, the timing, the lifecycle.* For evaluating and
  improving the skill.

## One file per lifetime
- File name: `YYYY-MM-DD_HHMM_busy-mode.md` (the start timestamp — sortable, and unique per lifetime).
- **At most one report is `Ongoing` at a time.** On entering busy-mode, if an `Ongoing` report exists,
  **append to it** (you're resuming the same lifetime); otherwise create a new one.
- Status is only ever **`Ongoing`** or **`Ended`**. It flips to `Ended` the moment Alkama says stop.

## Format (the template each report follows)

```markdown
# Busy-Mode Session — Mon 23 Jun 2026, 09:14 IST
**Status:** Ongoing
**Started:** Mon 23 Jun 2026, 09:14 IST

---

## Task 1 — <short title>  ·  🟢/🟡/🔴-briefed  ·  Mon 23 Jun 2026, 09:14 IST

**Which & why (150–200 words, written BEFORE working):**
I picked <task> over <the other candidates> because <value / urgency / unblocks-others>. It is 🟢/🟡
because <tier reasoning>. My approach: <how I'll do it>. Edge cases I'm anticipating: <…>. Why not
<alternative>: <…>.

**Outcome:** Done. <1–2 lines.> See TIMELINE entry "<…>"; files touched: <…>. (Or: Briefed →
`briefs/<…>.md` awaiting confirmation. / Stopped because <…>.)

---

## Task 2 — …  ·  …  ·  Mon 23 Jun 2026, 10:41 IST
…

---
_[paused — usage limit reached, Mon 23 Jun 2026, 11:40 IST]_
_[resumed — Tue 24 Jun 2026, 08:05 IST]_

## Window consolidation (at each pause / end)
- Open briefs awaiting Alkama: `briefs/<…>.md` — <one line each>
- Commit drafts (he commits): <feature> → files [...] — "<message>"

---

## Session ended — Tue 24 Jun 2026, 18:30 IST
**Status:** Ended
**Summary:** <N tasks done, M briefed>. Reverted to normal mode on Alkama's "stop busy mode."
```

Timestamps are **human-readable** (weekday, date, time, zone) so review is easy. Keep entries scannable.
