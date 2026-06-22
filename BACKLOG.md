# CLARA — Work Backlog

The single canonical queue of pending work. Grouped by **autonomy tier** (🟢/🟡/🔴), not strict priority —
within a tier, roughly value-ordered. Seeded 2026-06-21; kept fed by Claude at the end of every session.

---

## Busy-Day Operating Contract

**Trigger:** Alkama says some form of *"busy day — work the backlog"* (or just *"go work the backlog"*).
This is an **explicit permission-bypass mode**, not a new/headless session — we stay in this VS Code session,
grounded by CLAUDE.md + TIMELINE + this file.

**The only difference in busy-mode: I interrupt less.** Specifically:
1. **🟢/🟡 work → I do it without asking.** Typical *and* complex. No confirmation prompts. When I hit a fork
   or get stuck, I pick the **most reversible option, do it, and log the decision + the alternatives** in the
   end-of-window report — I don't stop to ask.
2. **🔴 work → never auto-executed, never an interruption.** Arming risky live behavior (A2 live, WhatsApp
   *send*, self-heal auto-apply), irreversible/destructive ops, or anything that physically needs Alkama (his
   mic, QR, money, git push) is **queued here with a note** for him to handle on his terms. Busy-mode either
   *does* the work (G/Y) or *queues* it (R) — it never pings him.
3. **Over-consume freely; under-consume never.** Keep pulling real, value-ranked work until the window is
   spent. If the usage limit ends mid-task, that's fine — resume on "continue". Accept the rare edge case
   (a mid-task cutoff, a process left running) rather than over-engineer to avoid it. (Note: the HF-cache wall
   currently prevents me from booting a backend, so my busy-mode work is inherently backend-free — code,
   drill-analysis, hardening, docs — which removes the orphaned-backend risk almost entirely.)
4. **Self-check every action.** Compile-check, run the relevant self-tests, use the abort-before-write
   validation-guard pattern (as in the question-promotions). Autonomous code introduces bugs — the self-veto
   is non-negotiable.
5. **End of each window: write a session report** (what was done, decisions made, what's queued, what needs
   Alkama) and **update this backlog** (mark done, append new finds).

**Self-veto reminder (overrides busy-mode):** if an action is irreversible *and* I'm genuinely unsure it's
right, the reversible move is to do the safe version + log it — not to ask, and not to blast ahead destructively.

---

## 🟢 GREEN — do unattended, no asking (deterministic, reviewable, no live-system risk)

- **G1 · Daily drill** *(RECURRING, fixed)* — harness runs via cron; I do the analysis + promotion + write the
  report's `## Claude's Analysis` section + TIMELINE. Size **S–M**. Grounding: CLAUDE.md "The Drill",
  `tests/report_analysis_status.py`, `tests/verification.py`. *This is the GREEN backbone — no loops, fully safe.*
- **G2 · Hardening / code-review sweep** — review recent diffs for self-introduced bugs (this week's pattern),
  produce a **report**, fix the clear ones, queue the judgment calls. Size **M**. Grounding: `git diff`, the
  /simplify + /code-review patterns.
- **G3 · `v_datetime` R2 extension** — relative-date / delta arithmetic, so the held datetime anchors (morning
  & evening Q21/Q22) can finally climb. Size **M**. Grounding: `tests/verification.py` v_datetime, the held Qs.
- **G4 · Layer-1 verifier extensions** — the flagged candidates: verify a claimed line/location for L4 quotes;
  guard the key_facts false-PASS on speculated tokens; confirm the count-check sub-verifier is wired everywhere.
  Size **M**. Grounding: TIMELINE "Layer-1 extension candidate" lines, `tests/verification.py`.
- **G5 · Dead F4/WS voice-path cleanup** — retire the dormant `voice_start`/`voice_stop` WS handlers +
  `start_recording` now that the mic is opt-in and F10 is the voice path. Third leftover we've found; do a
  focused tidy. Size **S**. Grounding: `api.py` WS handler, `core_logic/voice.py`.
- **G6 · Durable self-tests for new tools** — `episodic_search` + `whatsapp_missed` are only functionally
  spot-tested; add regression self-tests. Size **S–M**. Grounding: `core_logic/tools.py`, `tests/`.
- **G7 · Watch-items to close** — Tier-2 LLM judge returning None on a transient (add retry/fallback);
  any over-strict key_facts class flagged in recent drills. Size **S–M** each. Grounding: TIMELINE "WATCH".
- **G8 · Docs/TIMELINE upkeep + keep this backlog fed** *(RECURRING)* — harvest new items at end of session.

## 🟡 YELLOW — I build on `autonomous` (dormant, uncommitted); Alkama reviews the diff + commits

*No sub-branches — `autonomous` vs `main` is already the isolation layer. The gate is: **dormant-by-default
flag** (nothing live until Alkama flips it) + **he reviews the `git diff` and commits** (I draft per-feature
commit messages, I never commit/push). For a busy-day batch, each feature is self-contained with its own
drafted commit message + file list so he can commit them as clean logical units on his own time.*

- **Y1 · A2 — salience-gated proactivity** *(THE big one; break into sub-items)*. Grounding: `core_logic/salience.py`
  (gate built), `core_logic/ambient.py` (`compute_baseline` built), `briefs/BRIEF_40`, TIMELINE 06-20 A2 notes +
  the 06-21 novelty discussion.
  - **Y1a · Novelty fix (seen-vs-dominant)** — replace share-of-hour with `1 − days_seen(proc,hour)/days_observed`,
    AND make novelty per-class (timing for `off_rhythm`, recognition for app events) — the off-rhythm insight.
    Size **M**.
  - **Y1b · Observation classifier** — raw A0 obs → class (battery_low / off_rhythm / new_app_seen / default).
    Size **M**.
  - **Y1c · The loop (DORMANT + SHADOW mode)** — cursor/watermark + baseline-refresh + evaluate + compose;
    `A2_MODE` env tri-state off/shadow/live; shadow logs what it *would* surface. Size **L**.
  - **Y1d · `timing_ctx` population** — clara_speaking / task_in_flight / ptt / dnd-hours / min_quiet + the
    deep-work inference (don't interrupt mid-flow). Size **M**.
  - **Y1e · Surface channel + feedback** — a distinct proactive nudge (Telegram/console card) + 👍/👎 feedback
    that tunes thresholds. Size **M**.
- **Y2 · OCR for scanned PDFs** (`markitdown-ocr` → Gemini) — unblocked (Gemini key live). Size **M**.
  Grounding: `core_logic/tools.py` markitdown, BRIEF_36 §F.6.
- **Y3 · Stronger semantic retrieval** (Topic 4 Phase 3) — relevance-gated top-k (not fixed 2) + query-expansion
  before embedding. Size **M–L**. Grounding: `core_logic/crud.py` get_smart_context, ROADMAP Topic 4.
- **Y4 · A3 screenshot sensor** (ambient vision) — unblocked by the Gemini key. Size **M–L**. Grounding:
  BRIEF_36 §F.6/F.7, `ambient_watch.py`.
- **Y5 · Dynamic ReAct turn budget** (Topic 3) — base 8, ceiling ~16, extend on detected progress, terminate on
  stall, force honest partial at the ceiling. Do when agentic/self-heal work begins. Size **M**. Grounding:
  ROADMAP Topic 3, `agent.py` run_task.
- **Y6 · Wave 4 — wake-word app** (designed, not built). Size **XL** (multi-session). Grounding: BRIEF_46.

## 🔴 RED — queued only; needs-Alkama or arming-risk; NEVER auto-executed

- **R1 · Arm A2 live** — only after Y1 ships + a shadow-run + threshold tuning. *(arming-risk)*
- **R2 · WhatsApp auto-reply / send** — sending carries ban exposure on the personal number. *(arming-risk)*
- **R3 · Self-heal L4 auto-apply** (Brief 34) — far future, behind heavy guardrails + human merge. *(arming-risk)*
- **R4 · F10 hotkey physical test** — mic in/out + the distortion check + resolve the persistent-mic-vs-on-demand
  OPEN. *(needs Alkama's mic)*
- **R5 · WhatsApp live validation** — confirm the live feel; set `PERSON_MAP` to Shobha's real sender string once
  seen. *(needs Alkama)*
- **R6 · HF-cache wall — real fix for MY context** — `HF_HOME` redirect to a writable project-local dir, or
  diagnose the sandbox/token denial. *(needs Alkama / env)*
- **R7 · Telegram console-mirror live-validation** — was down ~06-22; confirm the live source-badged mirror.
  *(needs Alkama / external)*
- **R8 · Brave Search** (Brief 20) — replace Tavily; blocked on API subscription. *(needs Alkama / money)*
- **R9 · Commit-message drafts** — I draft at end of day; Alkama commits himself, no co-author trailer, I never
  push. *(needs Alkama / git)*

---

## How this stays fed
- **Continuous harvest** (not daily collection): at the end of each session I append newly-surfaced items here
  while I still have the context. A busy morning then needs only a 2-minute triage, not a from-scratch sweep.
- **Done items** move to TIMELINE (the durable trace) and are removed/struck here.
- Sizes: **S** ~<50k tok · **M** ~one heavy task (100–250k) · **L** ~a full window (may span a compaction) ·
  **XL** multi-window/multi-day.
