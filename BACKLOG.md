# CLARA — Work Backlog

The single canonical queue of pending work. Grouped by **autonomy tier** (🟢/🟡/🔴), value-ordered within a
tier. Kept fed + comprehensive by Claude at the end of every session. This is the **operational queue**; the
sequenced plan + dependencies live in `briefs/ROADMAP.md` — the two stay in sync.

---

## How to read this + the decision chain

**`BACKLOG.md` → `briefs/ROADMAP.md` → the brief → decide.** Start here (the queue). For a candidate item,
trace to the ROADMAP for where it fits and **its dependencies** (is it the right time? are its prerequisites
done?); then check for a **brief** (briefed-and-confirmed → implement; briefed-awaiting-confirm → don't;
complex-and-unbriefed → write the brief, don't blind-edit). **Only then** decide whether to start it *or not* —
an item whose deps aren't met is not started; do the prerequisite first or pick another.

Each item carries **Deps:** (what must be done first — "none" if free to start) and **Refs:** (roadmap/brief/code
pointers). **Sizes:** S ~<50k tok · M ~one heavy task (100–250k) · L ~a full window (may span a compaction) ·
XL multi-window/multi-day.

**Sync rule:** whenever a feature/idea is discussed and confirmed, add it to **BOTH** this file **and**
`briefs/ROADMAP.md`. Done items move to `TIMELINE.md` (the durable trace) and are struck here.

---

## Busy-Day Operating Contract

**Trigger:** Alkama says "use busy-mode" / "busy day — work the backlog". An **explicit permission-bypass**,
same live VS Code session (not `claude -p`), grounded by CLAUDE.md + ROADMAP + briefs + TIMELINE + this file.
The full loop + rules are the **`busy-mode` skill** (`.claude/skills/busy-mode/SKILL.md`); the short form:

1. **🟢/🟡 → do it without asking** (typical *and* complex). At a fork, pick the most reversible option, do it,
   log it. **There is no one to answer** during a window — never block on a question.
2. **🔴 (and any architecture-rippling / undecidable thing) → never auto-executed.** Write a **brief** (an async
   question) or queue it; never ping Alkama mid-window.
3. **Over-consume freely; under-consume never.** Run until the usage limit (a pause — resume on "continue");
   true stop only on Alkama's explicit "stop busy mode."
4. **Self-check every action** (compile + self-test + boot-and-test live now that the HF cache is repo-local +
   abort-before-write validation guards).
5. **Log everything as you go** to a per-lifetime report in `busy-mode-reports/` (a 150–200-word "which & why"
   *before* each task), plus TIMELINE + this backlog.

---

## 🟢 GREEN — do unattended, no asking (deterministic, reviewable, no live-system risk)

- **G1 · Daily drill** *(RECURRING)* — cron runs the harness; I analyze + promote + write the report's
  `## Claude's Analysis` + TIMELINE. The GREEN backbone. Size **S–M**. Deps: none. Refs: CLAUDE.md "The Drill",
  `tests/report_analysis_status.py`, `tests/verification.py`.
- **G2 · Hardening / code-review sweep** — review recent diffs for self-introduced bugs, report, fix the clear
  ones, queue judgment calls. Size **M**. Deps: none. Refs: `git diff`, /simplify + /code-review patterns.
- ~~**G3 · `v_datetime` R2 extension**~~ — ✅ DONE 2026-06-23 (busy-mode). Added `date_offset` + `time_delta`
  dynamic checks; self-test 30→36; climbed Q21/Q22 to R2 in both sessions (oracles validated before write).
  See TIMELINE "G3 — v_datetime R2 extension". Unblocked the 4 held temporal anchors.
- **G4 · Layer-1 verifier extensions** — ~~confirm the count-check sub-verifier is wired everywhere~~ ✅
  **AUDITED CLEAN 2026-07-01 (busy-mode)** — `_stated_total_conflict` is wired into `v_search_set`, and every
  search/enumerate question carries an explicit `type:search_set` (Q06/Q11/Q19); the absence questions
  (yaml.load/os.fork) correctly route to `absence_honesty`; `v_count` needs no count-check. No gap. ~~guard the
  key_facts false-PASS on speculated tokens~~ → **BRIEFED as BRIEF_53** (the missing-but-substantive →
  lenient `_llm_judge` path; delicate false-PASS↔false-FAIL tradeoff on a central primitive → see 🔴 R17).
  **Remaining:** verify a claimed line/location for L4 quotes (the `value_or_line` extension). Size **S–M**.
  Deps: none. Refs: `tests/verification.py`.
- **G5 · Dead F4/WS voice-path cleanup** — ✅ WS handlers DONE 2026-06-24 (`voice_start`/`voice_stop` removed
  from `api.py`; frontend sends neither). **Follow-up:** the now-orphaned `voice.py` `start_recording` /
  `stop_recording_async` (removing them needs verifying the persistent-mic/`_in_stream` logic — deferred, low
  priority). Refs: TIMELINE 06-24 [REFACTOR], `core_logic/voice.py`.
- ~~**G6 · Durable self-tests for new tools**~~ — ✅ DONE 2026-06-24. `tests/test_whatsapp_missed.py` (locks
  in the limit-before-filter fix) + `tests/test_episodic_search.py` (system-prefix filter + keyword path +
  semantic/cosine path + guards). Both via the `HF_HOME`→`.hf_cache` redirect pattern. See TIMELINE 06-24.
  Fully closed — the semantic-path follow-up is now covered too.
- **G7 · Watch-items to close** — ~~Tier-2 LLM judge transient (retry/fallback)~~ ✅ DONE 2026-06-27
  (`diagnose_failure` retries the `"(request failed:"` signal 2× + classifies a persistent transient as
  `infra`; `tests/test_diagnose_failure_retry.py`; TIMELINE 06-27). Remaining: any over-strict key_facts class
  flagged in recent drills. Size **S** each. Deps: none. Refs: TIMELINE "WATCH".
- **G8 · Refine the busy-mode skill after the first real run** — read the first `busy-mode-reports/` lifetime
  with Alkama; tighten wherever the "which & why" exposed the skill being under-specified. Size **S–M**.
  Deps: one completed busy-mode lifetime. Refs: `.claude/skills/busy-mode/SKILL.md`, `busy-mode-reports/`.
- **G9 · Docs/TIMELINE/BACKLOG/ROADMAP upkeep** *(RECURRING)* — keep all four in sync; harvest new items here +
  the roadmap. Size **S**. Deps: none.
- **G10 · Pre-checker-era report-analysis triage** — `report_analysis_status.py` flags 21 PENDING reports from
  the pre-checker era (05-22 → 06-11) that will never be retro-analyzed (question states long rotated; ~0
  forward value). They dilute the checker's signal for genuinely-missed *recent* reports. Decide once: stamp
  them with a one-line "pre-checker baseline — not retro-analyzed" partner_a the checker treats as closed, OR
  add a date-floor to the checker so it only reports from ~06-12 onward. **Process-policy call (changes what
  the checker signals) → Alkama's preference before acting.** Size **S**. Deps: Alkama nod. Refs:
  `tests/report_analysis_status.py`, `reports/2026-05-*`/`2026-06-0*`.
- ~~**G11 · Relative-date math → deterministic path**~~ — ✅ **DONE 2026-06-28** (Alkama greenlit Brief 50).
  `get_time_date(offset_days=±N)` returns the computed target date+weekday; FAST `date_time` dispatch +
  registry/interpreter routing + PERSONA nudge. Validated live ("10 days from now" → "Wednesday, 08 July
  2026", computed). See TIMELINE 06-28 [FEATURE] Brief 50. *(Below was the brief; now implemented.)* Sharpened diagnosis from the 06-24/06-25 drill catch-up: the failure is
  specifically **month-boundary crossings** (`+10d` Jun→Jul fails both mornings; `−12d` in-June passes both
  evenings) — off-by-one on the 30-day rollover; *time* deltas are fine. Root cause: relative-date Qs route to
  FAST (0 turns) → mental calendar arithmetic; Rule 7 ("no mental math") isn't applied to date offsets. Brief
  50 lays out 3 options (route to `python_repl` / add `offset_days` to `date_time` (RECOMMENDED) / PERSONA
  nudge) + proposed code. **Blast radius is real** (changes how a whole question-class is routed) → brief, not
  a blind edit. Size **S–M**. Deps: Alkama's pick. Refs: `briefs/BRIEF_50…md`, `reports/2026-06-2{4,5}-*.md`
  Q21, `core_logic/{system_prompt,interpreter,tool_executor}.py`, `get_time_date` in `tools.py`. ~~Sub-item:
  FAST raw-tool-output log~~ ✅ FIXED 2026-06-24.
- **G12 · Drill promotion backlog (5 remaining of the 7 deferred 2026-06-24m)** — ~~Q05~~ ✅ + ~~Q20~~ ✅ done
  06-24 (L4→L5: `_context_warmup` self-repair; MCP command/args resilience). Remaining: **Q04**
  (conversation-hold — careful: the `get_smart_context` 6-vs-10 recent-window overlap) + **Q07/Q08/Q12/Q14**
  (L5-maxed → fresh-L1 on untested modules — the design-heaviest, each needs a new module + validated oracle).
  Do as one focused pass. Size **S–M**. Deps: none. Refs: TIMELINE 06-24, `tests/questions_morning.json`.

- **G13 · Format-correction cascade in `run_task` (diagnose → brief the fix)** — surfaced 06-30e Q9: an
  `os.fork` honest-negative (correct, Rule-19-verified) burned **5 turns / 5 flags** (implicit-final-answer →
  off-format-correction → no-valid-action → malformed-json → hallucination-correction) — one malformed-JSON
  Action snowballed compounding corrections on a 1-turn search. **No answer impact; intermittent** (zero
  format flags on 07-01m). The *diagnosis* (read the session log, characterize the snowball, confirm it isn't
  a Brief-51/52 interaction) is safe 🟢; the *fix* (Clara's proposal: after the first format error, emit one
  clean full Action rather than salvaging the broken turn) is a **ReAct-loop behavior change → brief it, don't
  blind-edit** (blast radius = the loop). Y5-adjacent (dynamic turn budget). Size **S–M**. Deps: none. Refs:
  TIMELINE 06-30e/07-01m WATCH, `core_logic/agent.py` run_task format-correction block, `reports/2026-06-30-evening.md` Q9.

- **G14 · Coherence-drill FILESYSTEM leak (fixture wrote a real file)** — *(found 2026-07-02 during commit
  prep)*. `deadlines.md` appeared at repo root, created 2026-07-01 08:10 MID-CRON, containing "API spec due
  Friday (requested by **Priya**)" — Priya is the FICTIONAL coherence-drill manager. `memory_mode=ephemeral`
  isolates *memory*, but drill tool-calls still EXECUTE — a dialogue turn helpfully wrote a real file. Same
  class as the 06-07 fixture-memory pollution, via the filesystem. Investigate the 07-01 08:00 session log
  (which turn wrote it); fix options: coherence dialogues get `write-safe` phrasing, OR the drill gets a
  tool-sandbox/dry-run mode, OR probe answers that *would* write are asserted-not-executed. File is now
  gitignored (fictional content must not be committed); do NOT delete until investigated. Size **S–M**.
  Deps: none. Refs: `deadlines.md`, `tests/coherence_dialogues.json` manager-her, `logs/session_2026-07-01_08-00-55.log`.

## 🟡 YELLOW — I build on `autonomous` (dormant, uncommitted); Alkama reviews the diff + commits

*No sub-branches (`autonomous` vs `main` is the isolation). Gate = dormant-by-default flag + Alkama reviews the
`git diff` + commits (I draft per-feature commit messages; I never commit/push).*

- **Y1 · A2 — salience-gated proactivity** *(THE big multi-part build)*. Refs: `core_logic/salience.py` (gate
  built), `core_logic/ambient.py` (`compute_baseline` built), `briefs/BRIEF_40`, ROADMAP Phase 40, TIMELINE
  06-20/06-21 A2 notes. **Internal dependency order (revised 2026-06-24):** (Y1a ∥ Y1b) → Y1c → [Y1-decisions]
  → Y1e (surface to the interface feed + calibration) → [R1 arm]. *Y1d (timing) + the interrupt-model rebuild
  are DROPPED — passive interface delivery doesn't interrupt.*
  - ~~**Y1a · Novelty fix (seen-vs-dominant + per-class)**~~ — ✅ DONE 2026-06-24. Per-class novelty
    (recognition `1 − days_seen/days_observed` for apps, timing for odd_hours, trajectory for battery);
    `compute_baseline` extended with `proc_hour_days`/`hour_days`/`days_observed`. See TIMELINE 06-24.
  - ~~**Y1b · Observation classifier**~~ — ✅ DONE 2026-06-24. `classify(record, baseline)` →
    battery_low / odd_hours / new_app_seen | None. (off_rhythm/long_session deferred — need session-duration
    state A0 doesn't expose yet.) See TIMELINE 06-24.
  - **Y1-tuning · salience calibration** *(NEW, surfaced by the Y1a/b empirical preview)* — over the real
    14-day baseline, **0/1202 candidates clear the 0.45 threshold** (new_app_seen capped at act 0.25;
    odd_hours lands ~0.39–0.43; no battery events). A2 is currently near-silent. Decide the chattiness in the
    Y1c **shadow** phase: bump `odd_hours` actionability and/or lower the 0.45 threshold against real data.
    Size **S**. Deps: Y1c shadow. *(Alkama's call — how JARVIS-talkative.)*
  - ~~**Y1c · The loop (DORMANT + SHADOW)**~~ — ✅ DONE + WIRED + boot-validated 2026-06-24
    (`core_logic/ambient_loop.py`): `AmbientLoop` (cursor + baseline-refresh + classify→evaluate→compose,
    `A2_MODE` off/shadow/live, per-class cooldowns); `ambient_shadow_loop()` started from `api.py` lifespan
    (gated on `A2_MODE`, mirrors WhatsApp poller); `A2_MODE=shadow` set in `.env`. Boot-test: live tick wrote
    a real shadow entry, `would_send=false`, zero errors. **Shadow accumulates live now** (backend + A0
    running). See TIMELINE 06-24. Live delivery still needs the interrupt rebuild + a notifier sink + arming.
  - ~~**Y1d · `timing_ctx` population**~~ — ❌ REMOVED 2026-06-24 (re-plan): A2 delivers passively to the
    interface (no sound/poke) → cannot interrupt → no timing gate needed. Dropped deep_work/clock-DND/min_quiet
    + the interrupt-model rebuild (Brief 40 §5). Only a future MANUAL mute remains (a flag, no-op today). See
    TIMELINE 06-24 [REFACTOR].
  - **Y1-decisions (NEW, 2026-06-24 re-plan)** — settle the passive-feed model before Y1e: (a) **budget** —
    purpose shifts interrupt-scarcity → feed-hygiene; keep 4/day, loosen, or drop (keep the dedup cooldown
    regardless)? (b) **calibration channel** — 👍/👎 via an interface tap vs WhatsApp? (c) **soak vs go** —
    passive delivery is low-risk, so surface to the interface feed sooner and calibrate live, rather than a
    long shadow soak? Size **S** (decisions). Deps: Alkama. Refs: Brief 40 (superseded note), TIMELINE 06-24.
  - ~~**Y1e · Surface channel + feedback**~~ — ✅ DONE 2026-06-24 (passive-feed model). `ambient_ledger.json`
    + `_live_sink` (broadcast `ambient_nudge` + record) + `GET /ambient_feed` + `POST /ambient_feedback`;
    frontend "Ambient" panel with 👍/👎. `A2_MODE=live`. Self-tested + live-path integration + npm build +
    boot-test. NOT Telegram/interrupt — passive interface only. See TIMELINE 06-24. **Follow-up:** Beta-counter
    auto-tune of the novelty threshold from the 👍/👎 ledger (currently the ledger just RECORDS; tuning is
    manual/review for now).
- ~~**Y2 · OCR for scanned PDFs**~~ — ✅ DONE 2026-06-27 (busy-mode). Built as a **Gemini-vision fallback**
  (`ocr_pdf` native tool, PyMuPDF rasterize → `analyze_image_grok`), deliberately NOT `markitdown-ocr`
  (avoids the `magika`→CPU-`onnxruntime` shadowing of `onnxruntime-gpu`; CUDA verified intact). Text-PDFs
  short-circuit to direct extraction; scans OCR ≤10 pages. Validated: `tests/test_ocr_pdf.py` (4 cases) +
  live Gemini smoke + backend boot (10 native tools, was 9; no errors). See TIMELINE 06-27. `pymupdf` added
  to `requirements.txt`. **Uncommitted on `autonomous`** — Alkama reviews the diff + commits.
- **Y3 · Stronger semantic retrieval** (Topic 4 Phase 3) — relevance-gated top-k + query-expansion before
  embedding. Size **M–L**. Deps: none. Refs: `core_logic/crud.py` get_smart_context, ROADMAP Topic 4.
- ~~**Y4 · A3 screenshot sensor** (ambient vision)~~ — ✅ **DONE 2026-06-28 (DORMANT)** (Alkama greenlit).
  Built as a separate backend module `core_logic/screen_sensor.py` (NOT in `ambient.py` — that module forbids
  API keys + screenshots), OFF by default behind `A3_SCREEN_SENSOR`; screen → Gemini one-line description,
  description-only storage to `ambient_screen.json` (raw image never persisted), 15-min cadence. Self-test +
  boot-test (dormant) green. See TIMELINE 06-28 [FEATURE] Y4/A3. **Arming = Alkama** (`A3_SCREEN_SENSOR=on`;
  privacy: screen → cloud). **Follow-ups (deferred):** A1-recall integration (read `ambient_screen.json`);
  consider an A2 surface for screen-derived observations.
- **Y5 · Dynamic ReAct turn budget** (Topic 3) — base 8, ceiling ~16, extend on progress, stop on stall, honest
  partial at ceiling. Size **M**. Deps: soft — do when agentic/self-heal work begins. Refs: ROADMAP Topic 3,
  `agent.py` run_task.
- **Y6 · Wave 4 — wake-word app** (designed). Size **XL** (multi-session). Deps: none hard. Refs: BRIEF_46.

## 🔴 RED — queued only; needs-Alkama or arming-risk; NEVER auto-executed (brief, don't build live)

- ~~**R1 · Arm A2 live**~~ — ✅ effectively DONE 2026-06-24: the re-plan made A2 a PASSIVE interface feed (no
  push/sound), so "arming" carries no interrupt-risk — `A2_MODE=live` is set and nudges surface to the feed.
  The old arming-risk (a phone buzz) only returns if a muteable Telegram *push* is ever added (then a manual
  DND + a real arm decision). For now: live + calibrating via 👍/👎.
- **R2 · WhatsApp auto-reply / send** — *(arming-risk: ban exposure on the personal number)*. Deps: none.
- **R3 · Self-heal L4 auto-apply** (Brief 34) — *(arming-risk; far future)*. Deps: L2/L3 self-assessment trust
  earned. Note: when built, the writer must be block-edit + atomic + snapshot (not whole-file write).
- **R4 · F10 hotkey physical test** — mic in/out + distortion + resolve the persistent-mic-vs-on-demand OPEN.
  *(needs Alkama's mic)*. **De-risked 2026-06-23:** the empty-transcript issue was diagnosed to the mic
  delivering silence (ASUS/Intelligo noise-cancel gating the default array, not a bug); `hotkey_listener.py`
  now has a silence-guard + `CLARA_MIC_DEVICE` selection + `--list-devices` (TIMELINE 06-23). For the physical
  test: `python hotkey_listener.py --list-devices`, then `CLARA_MIC_DEVICE=2` (the OnePlus headset) or fix the
  Windows/ASUS input gating.
- **R5 · WhatsApp live validation** — confirm the live feel; set `PERSON_MAP` to Shobha's real sender string.
  *(needs Alkama)*.
- **R19 · Telegram voice-note live validation** — ✅ BUILT + ARMED 2026-07-02 (`_handle_voice`, local Whisper
  STT, transcript echo, same pipeline as text; TIMELINE 07-02). *(needs Alkama's phone)*: send Clara's bot
  (1) a voice note → expect 🎤 transcript echo + a normal answer; (2) a plain text → confirm the refactored
  `_process_text` path unchanged. Check STT quality on Hinglish/accented speech; if weak, consider
  `initial_prompt` tuning or a language hint. Refs: `core_logic/telegram_bot.py` _handle_voice/_process_text.
- **R6 · HF-cache wall** — ✅ RESOLVED 2026-06-23 (HF_HOME → repo-local `.hf_cache`; backend boots from any
  context). *Kept here struck as a record; remove next pass.*
- **R7 · Telegram console-mirror live-validation** — confirm the live source-badged mirror. *(needs Alkama /
  external; Telegram was down ~06-22)*.
- **R8 · Brave Search** (Brief 20) — replace Tavily; blocked on API subscription. *(needs Alkama / money)*.
- **R9 · Commit-message drafts** — I draft; Alkama commits, no co-author trailer, I never push. *(needs Alkama
  / git)*.
- **R12 · WhatsApp read/unread (engage-to-read)** — **CORE DONE 2026-06-27** (Alkama's decisions:
  engage-to-read; no panel now → panel queued as R13). Held archive rows now carry `id` + `status`
  (unread/read), lazy-migrated for legacy rows; `mark_whatsapp_read(ids|sender)` is a non-destructive LABEL
  (never deletes — re-queryable forever). `whatsapp_missed` now branches: **no query = UNREAD digest** (marks
  nothing); **named sender = that sender's messages VERBATIM and flips them read** (`mark_read=False` to peek;
  `status` to override). Tests: `conversations.py` self-test + `tests/test_whatsapp_missed.py` (end-to-end).
  Refs: `core_logic/conversations.py`, `tools.py`, `tool_registry.py`, `interpreter.py`. See TIMELINE 06-27.
  **DEFERRED (lower-value, bigger reach):** the full two-store *unification* (folding Shobha's surfaced
  messages into the same store) — Shobha already lands durably in the chat feed (re-readable via `/history`),
  so the read/unread gap only affected the held archive, which is now fixed. Revisit if a single "all WhatsApp
  in one place" view is wanted. Refs: `briefs/BRIEF_49…md` §2.4.
- **R13 · WhatsApp inbox PANEL (interface)** — *(Alkama: "add the panel for future implementation")*. A
  read-only "WhatsApp" panel in the UI showing unread-first held messages with per-sender drill-down + a
  mark-read tap, over the R12 store (`read_whatsapp_held(status=…)` / `mark_whatsapp_read`). Mirrors the A2
  Ambient panel pattern (`Layout.jsx` + `useClara.js` + a `/whatsapp_feed` endpoint). Size **S–M**. Deps:
  R12 (done). Refs: `briefs/BRIEF_49…md` §3.2, `interface/src/Layout.jsx`.
- **R11 · `tests/` + `briefs/` are gitignored — decide: track or keep-local** — *(policy decision; needs
  Alkama)*. `.gitignore` lines 17-18 ignore both dirs, and `git ls-files` confirms NOTHING in them is tracked.
  Consequence: the entire drill machinery (verifier `tests/verification.py`, the question sets, the self-test)
  and every brief (incl. today's Brief 48) live ONLY in the working tree — they will NOT appear in `git diff`
  and cannot be committed/reviewed the normal way. The drill *reports* + TIMELINE/BACKLOG/CLAUDE.md ARE
  tracked, so the OUTPUT is versioned but the MACHINERY is not. Decide: un-ignore (version-control + review the
  test/brief evolution) vs keep-local (deliberate). If un-ignoring, check the question text/briefs for anything
  meant to stay private first. Size **S**. Deps: Alkama decision. Refs: `.gitignore:17-18`.
- ~~**R10 · Brief 48 — Glint-detector Final-Answer false-positive**~~ — **DONE 2026-06-27** (Alkama
  greenlit on busy-mode stop). Gated the inline-fabrication detector: if `Final Answer:` precedes the first
  glint token, the glint is answer prose → suppress the check, deliver in full. Real bare/inline fabrications
  (no Final Answer before the glint) still caught. Refs: `core_logic/agent.py` glint block. See TIMELINE
  2026-06-27. ⚠️ **UPDATE 06-27 (boot-test):** Brief 48 is **INCOMPLETE** — the model delivers Q13
  off-format (`[DELIBERATE] Final Answer (implicit)`, no literal `Final Answer:` marker), so the gate never
  engages and Q13 **still truncates** at `**Bare Glint:**`. The deterministic test passed only on idealized
  marker-prefixed inputs. Superseding fix briefed → **R14 / BRIEF_51**.
- ~~**R14 · Brief 48 refinement — line-start glint anchor**~~ — ✅ **DONE 2026-06-28** (`_detect_fabricated_glint`
  + `tests/test_glint_detector.py` + live boot-test; **exposed R16 / BRIEF_52**). *(orig brief: `briefs/BRIEF_51…md`,
  core ReAct hallucination guard → brief-don't-build)*. Anchor the glint regex to a LINE START
  (`(?m)^[\s>#*`+"`"+`\-]*Glint…:`) so a fabricated `Glint:` *line* is caught but `Glint:` embedded mid-prose
  (`**Bare Glint:**`) is not — marker-independent, supersedes Brief 48's gate. Includes a both-directions
  `tests/test_glint_detector.py` plan. Residual: a mid-line fabrication would slip (low-risk; needs Alkama's
  safety call). On confirm: apply + unit test + re-boot-test Q13 (must deliver full). Size **S**. Deps: Alkama
  confirm. Refs: `briefs/BRIEF_51…md`, `core_logic/agent.py` glint block, TIMELINE 06-27.
- **R15 · Drill cron terminated mid-run (environmental, NOT a code casualty)** — *(diagnosed 06-27 busy-mode;
  needs Alkama / system-level)*. No 06-26/06-27 drill reports because both scheduled tasks (`CLARA_Test_Morning`
  08:00, `CLARA_Test_Evening` 20:00) are healthy/firing but their last runs exited `0xC000013A`
  (STATUS_CONTROL_C_EXIT — killed mid-run), almost certainly the laptop sleeping/shutting down during the away
  period (06-25 ran clean → nothing in the harness regressed). The 06-27 20:00 run is the live tell. If reliable
  away-period drills matter, keep the laptop awake across the run windows (power plan / wake-on-task).
  System-level → Alkama's call, not auto-actioned. Size **S**. Deps: Alkama. Refs: `setup_schedule.ps1`.
- ~~**R16 · BRIEF_52 — self-referential answer breaks the ReAct loop (`Action:`-in-prose)**~~ — ✅ **DONE
  2026-06-29** (Alkama: "implement brief 52"). `_has_line_start_action` + delivery guard; unit test + live
  boot-test (Q13 delivers both forms in full; normal tool query still works). With Brief 51, the
  self-referential class is closed. See TIMELINE 06-29 [FIX] Brief 52. *(orig brief below.)* Brief 51's
  boot-test revealed Q13's answer also contains `Action:` as PROSE ("model writes `Action: [...]`"); the
  action parser misparses it ("Malformed JSON in Action… Skipped") → the real answer is dropped and a
  `[[TASK]]`-marked "already answered" meta-response is delivered. Fix (mirror Brief 51): line-start-anchor
  the action detector + deliver a substantive no-valid-action turn. Q13 regressed on this one pathological
  self-referential probe (the glint cycle had masked it pre-Brief-51). Size **S–M**. Deps: Alkama confirm.
  Refs: `briefs/BRIEF_52…md`, `core_logic/agent.py` parse_actions/run_task, `tests/test_glint_detector.py`.
- **R17 · BRIEF_53 — key_facts false-PASS guard (decision needed)** — *(briefed 2026-07-01 busy-mode, G4
  axis b)*. The `key_facts` **missing-but-substantive → lenient `_llm_judge`** path silently PASSed a
  truncated answer (Q13 06-25e — a false-PASS, the *dangerous* verifier error that hides a real failure).
  Delicate: it's the false-PASS↔false-FAIL tradeoff on a **central primitive** (~half the questions), and the
  trigger is largely closed by Brief 51/52, so it's **defense-in-depth, low urgency**. Brief lays out 4
  options; **recommends Option 3** (downgrade a missing-branch judge-PASS to UNVERIFIABLE — cannot false-FAIL,
  costs a few manual UNVERIFIABLEs) with Option 4 (document + monitor) as the do-nothing default. On confirm:
  implement + both-direction self-tests + re-run. Size **S–M**. Deps: Alkama's pick. Refs:
  `briefs/BRIEF_53_KeyFacts_FalsePASS_Guard.md`, `tests/verification.py` v_key_facts/_llm_judge.
- **R18 · BRIEF_54 — pre-execution admissibility gate** — ✅ **PHASE 0 DONE 2026-07-02** (Alkama greenlit
  "build the gate + noop ledger + local policy"). `core_logic/admissibility.py` (gate + abstract envelope +
  atomic ring ledger + `noop`/`policy` adapters), hooked at `tool_executor._execute_mcp` (the shared
  FAST+DELIBERATE choke point); self-test 7/7 + live shadow boot-test (write query → 1 ALLOW ledger entry,
  no content leak, shadow never blocks). `.env` armed at phase 0: GATE=on / ADAPTER=noop / MODE=shadow /
  FAIL=open. See TIMELINE 07-02 [FEATURE]. **Remaining phases:** **P1** — `partner_a` adapter (contract
  CONFIRMED by the partner A founder, schema in BRIEF_54 §7) in SHADOW (verdicts logged, real latency measured, nothing
  enforced; needs Alkama to register the agent on partner_asca.com + API details). **P2** — enforce-mode pilot
  demo session with the partner A founder (benign file_write through ALLOW/REVIEW/DENY; also the enforce-branch live-fire).
  **P3 (far)** — enforce-by-default on high-risk tools + Telegram REVIEW approval loop (needs task-parking;
  separate brief). Known v1 hole (documented): `python_repl` exempt. Deps: P1 needs Alkama's partner A
  registration; P2 needs P1 + a scheduled session. Refs: `briefs/BRIEF_54…md` (+§7),
  `core_logic/admissibility.py`, `tool_executor.py` _execute_mcp, `LINKEDIN_CONVOS.md (partner A thread).
