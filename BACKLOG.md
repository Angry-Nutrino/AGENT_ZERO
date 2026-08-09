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

- **G34 · Self-assessment (free-text) FABRICATES EVIDENCE at exactly the point where the honest answer is
  "I cannot verify this"** — added 2026-08-09, hardened same day. **The most serious open finding.** TWO
  instances in a single self-assessment, both confident, both specific, both checkable, both false:
  1. **Q19** — invented a cause for a FAIL whose real mechanism (a verifier table-parse bug) was invisible
     from inside her trace: *"the answer injected a headline contrast figure of 285 (asyncio.to_thread
     calls)"*, with ownership language (*"My error, specific, naming it"*). No such figure exists; "285"
     occurs once, as a markdown table LINE NUMBER; and there are 33 to_thread occurrences, not 285.
  2. **Q12** — claimed to have READ something that was not on the page: *"On the digest I do see
     PermissionError plainly at the start of part 3"*. She was shown a **900-character** digest of a
     **4,009-character** answer. Part 3 begins at character **2,377**. She never saw part 2 either. And
     `PermissionError` is absent from the full answer, so no truncation could have revealed it.
  **THE PATTERN, and why it is worse than random error.** In case 2 the fabricated detail is
  **LOAD-BEARING**: she asserted the response was *"truncated mid-part-3"* (it was cut inside part **1**),
  which is precisely the premise required for "I can see the start of part 3" to be possible. Two false
  claims that fit together and support each other. That is not noise, it is a coherent invented account.
  The same paragraph also contains the honest hedge *"not something I saw fully in this digest"* — so **she
  knew her evidence was thin, and generated the missing evidence instead of stopping.**
  **Both fabrications sit exactly where the correct output is "I cannot determine this from what I was
  shown."** Fabricated SELF-BLAME is the dangerous direction: it reads as integrity, so nobody interrogates
  it. On Q12 she reached the right verdict by an invented route, which is worse than reaching it honestly —
  the next time that route runs it produces a confident WRONG answer and the output looks identical.
  **ENFORCEMENT (in order of cost, all still to do):**
  (a) **Standing rule, effective now: when Layer 2 and the narrative disagree, Layer 2 wins.** Layer 2 is
      trace-anchored and got Q19 right; the narrative is a story asked to own failures.
  (b) **Remove the root enabler — stop asking her to assess text she cannot see.** `build_session_digest`
      truncates every response to 900 chars (`test_harness.py:~470`). Either raise the cap so the digest
      carries the full answer (23 x ~4k chars is affordable against a prompt that is already ~32k), or state
      per-question exactly how much is hidden and forbid any claim about the hidden region.
  (c) **THE REAL FIX — a deterministic post-check on the self-assessment.** Scan her self-assessment for
      checkable specifics (quoted tokens, "I see X", numeric claims) and verify each against the actual
      answer text, flagging any that do not appear. This is the project's own founding principle —
      *no model grades a model* — applied to the ONE component where it currently is not. Mechanically
      checkable, no LLM needed, and it would have caught both instances instantly.
  (d) Feed Layer 2's classification INTO the narrative prompt so it explains the real mechanism instead of
      inventing one, and make "I cannot verify this from the digest" an explicitly allowed answer.
  Ref: reports/2026-08-08-evening.md analysis. Dep: none. Size: (a) free, (b) S, (c) M, (d) S.

- **G32 · Coherence Drill scores controls whose PRECEDING dialogue died of infra** — added 2026-08-08.
  On 08-08m `appropriately-asked` read **0%**, but one of the two controls (`ambiguous-service`) never ran
  — it died with an `HTTPConnectionPool` read timeout — so the honest denominator was 1, not 2. Worse, the
  surviving control (`ambiguous-offer`) ran *immediately after* that failure and answered "there are no two
  offers in this conversation", which is plausibly **correct** if the failed dialogue disturbed the
  transient window. A failed request is silently laundered into a behavioural score. Fix: skip (or mark
  `unscored`) any probe whose request errored, and any control whose preceding dialogue errored, rather
  than counting it as a behavioural miss. **First step: re-run the two controls in isolation** to settle
  whether 08-08m's 0% is an artifact. Ref: reports/2026-08-08-morning.md analysis. Dep: none.

- ~~**G33 · Harness: the 08:00 morning cron was silently skipping**~~ — ✅ DONE 2026-08-08. **Root cause was
  the Task Scheduler BATTERY GUARD, not the schedule.** `CLARA_Test_Morning` showed `NumberOfMissedRuns: 2`,
  last ran 08-06, skipped 08-07 and 08-08 — matching the missing `reports/2026-08-07-morning.md` exactly.
  Task Enabled, trigger Enabled, and `StartWhenAvailable` already True, so a missed start *should* have been
  retried; `DisallowStartIfOnBatteries=True` blocked it every time the laptop was unplugged, and
  `StopIfGoingOnBatteries=True` would have killed a run mid-flight on unplug. Evening survived only because
  20:00 is desk-and-mains time. Both guards disabled on BOTH tasks (needs an ELEVATED shell —
  `Set-ScheduledTask` returns Access Denied from a normal prompt since the tasks were registered elevated).
  Accepted tradeoff: the drill now runs on battery, ~35 min of GPU. Ref: TIMELINE 2026-08-08 [FIX].

- **G30 · Admissibility: stamp the policy version into every receipt** — added 2026-08-08, surfaced by an
  external reviewer's question. `_ledger_append` records `{receipt_id, verdict, reason, adapter, mode,
  enforced, envelope}` but **no policy version**, and `_load_policy()` re-reads the JSON on every
  evaluation. So two actions either side of a policy edit are indistinguishable in the ledger and an audit
  cannot tell which rules were in force. Add a version/hash of the policy file to the envelope or receipt.
  Dep: none. Small.

- **G31 · Admissibility: bind the verdict to the action (signed, not just structural)** — added 2026-08-08,
  same source. Today the binding is *structural*: `gate(tool_name, args)` gets the same in-memory dict the
  dispatcher gets, same frame, no gap — so the executed action is the evaluated one **by construction**.
  The envelope carries a `nonce` and a `signature`, but `signature` is `""` on the local path. That is
  arguably proportionate for one in-process actuator and clearly **not** enough the moment the actuator is
  a separate process or the verdict comes from a remote engine. Target: a verdict signed over
  (target_path_hash, policy_version, nonce) that the executor verifies before dispatch. Dep: G30 (needs the
  policy version to sign over). 🟡-adjacent — design first, do not wire live without review.

- **G27 · Layer-1: `verbatim_quote` file resolution misses an explicitly-named file** — added 2026-08-07.
  08-07e Q17 graded UNVERIFIABLE with *"no source file resolved from question"* even though the question
  names `core_logic/agent.py` outright, and her quote (`agent.py:2009`) was verbatim-correct. A PASS the
  verifier could not see. Fix the filename extraction in `tests/verification.py`'s quote path, add both
  directions to the self-test. Ref: reports/2026-08-07-evening.md analysis. Dep: none.

- **G28 · Layer-1: `key_facts` judge accepts a paraphrase for an absent must-include token** — added
  2026-08-07. 08-06e Q03 asked to "name the EXACT file"; she described the mechanism and never emitted
  `tool_registry`. The judge accepted the paraphrase and resolved to UNVERIFIABLE. Safe direction (it did
  not silently PASS), but an absent must-include token arguably belongs as a FAIL — the whole premise of
  `key_facts` is that the terminal identifier is *present*, not approximated. **Decide the threshold
  deliberately**: this affects every `key_facts` question in both sets, so it is a designed pass, not a
  drive-by edit. Ref: reports/2026-08-06-evening.md analysis. Dep: none.

- **G29 · Layer-1: code_build acceptance failure grades UNVERIFIABLE, not FAIL** — added 2026-08-07.
  08-05e Q23 failed acceptance (`exit 1: AssertionError: first_exceeding() missing`) — the harness ran her
  code and the method was absent, which is a real miss — but it landed as UNVERIFIABLE, so it never
  registered in the headline. Ref: reports/2026-08-05-evening.md analysis. Dep: none.

- ~~**G26 · search_set partition/caveat false-fail**~~ — ✅ DONE 2026-08-01 (busy-mode). `_stated_total_conflict`
  in `tests/verification.py` false-failed a correct enumeration when the answer PARTITIONED the count
  ("8 executable + 8 comment" of 16) or carried a clarifying CAVEAT ("12 hits for the broader token") — it read
  a sub-header/caveat as the grand total. 3+ instances; on 07-31m it false-failed a *perfect* answer. Fix:
  parse "N total" (number-before-'total') + `_subset_sums_to` partition reconciliation. Self-test 51→54 (3
  fixtures, both directions). Ref: TIMELINE 2026-08-01 [FIX]. **`tests/` gitignored — not in git diff.**

- ~~**G25 · `<tool_call>` blob reached the user (Q22 07-31e)**~~ — ✅ DONE + BOOT-TESTED 2026-08-01
  (busy-mode). F3: `offset_minutes` added to `get_time_date` (deterministic clock-time, midnight-wrap) +
  interpreter schema/routing + FAST-dispatch wiring → time-deltas route FAST ("6h53m from now" → "12:50 PM"
  live). F2b: `_run_chat` replaces a stray native `<tool_call>` block with an honest fallback. Ref: TIMELINE
  2026-08-01 [FIX] G25. **TRACKED (core_logic/) — in git diff.** *(Diagnosis kept below for the record.)*
  NOT a FAST issue and NOT infra. Log (`session_2026-07-31_20-01-03.log:7386-7402`) shows two
  real defects: **(1) Interpreter misclassified** "what time will it be 6h53m from now? Give AM/PM" as
  `tool=null` at **confidence 0.98** (should be `date_time` with `offset_minutes=413`) → routed to CHAT. It
  handles "N days ago" (Q21 routed FAST correctly the same run) but misses relative-TIME ("N hours M minutes
  from now"). **(2) CHAT leaked a native tool-call**: in `_run_chat` (no tool execution) the model emitted
  `<tool_call>{"name":"date_time","arguments":{"offset_minutes":413}}</tool_call>` and CHAT streamed it
  verbatim as the answer. **Refined root cause (2026-08-01):** `get_time_date` supports only `offset_days`, NOT
  `offset_minutes` (tools.py:174), and the design is that the current time is READ from the `[NOW]` line each
  turn (system_prompt.py:75-84) — so tool=null→CHAT is *correct routing* for a time-delta (CHAT computes
  now+delta from [NOW]); the model's `<tool_call offset_minutes=413>` called a parameter that does not exist.
  So the earlier "F1: route to date_time" was wrong. **Two fixes (backend → boot-test):** **F3 (root, the
  right one)** — add `offset_minutes` to `get_time_date` (append a deterministically-computed target-TIME line,
  mirroring the Brief-50 offset_days target-date line), add it to the interpreter date_time schema + a
  relative-time routing rule → time-deltas route FAST to a DETERMINISTIC tool answer (no mental math, no CHAT
  path for this class). **F2b (durable backstop)** — guard `_run_chat`: if the final response is a native
  `<tool_call>` block, do NOT return the blob — strip + honest fallback (or escalate) so a stray CHAT tool-call
  never ships garbage again. Size **S–M**. Deps: none (implement after the 08:00 cron; boot-test the time-delta
  route + the guard). Ref: reports/2026-07-31-evening.md Q22, `core_logic/tools.py` get_time_date,
  `core_logic/interpreter.py`, `core_logic/agent.py` `_run_chat`.

- **G20 · code-build ladder in-loop post-write verification** — 2026-07-20 evening Q23 (Component-2 L2 `peak()`): Clara wrote correct-looking code but the write_file never landed (Action returned as response text, file left as the L1 version) → acceptance failed "peak() missing" AFTER the fact, wasting the rung. 2nd instance of a ladder write not landing. Fix: on a code-build-ladder task, after the write_file, read the file back + run acceptance WITHIN the same task so a non-landed/failed write is caught and retried in-loop, not silently failed post-run. Consider also enforcing that a ladder task must end on a Final Answer, not an unexecuted Action. Size M. Ref: reports/2026-07-20-evening.md Q23 analysis.
  **Flow analysis 2026-08-01 (busy-mode):** `v_code_build` (verification.py:730) runs the acceptance snippet post-run and correctly FAILs a non-landed write ("peak() missing") — but it CANNOT distinguish "write didn't land" (Action-as-prose / parse issue, same class as Brief 51/52) from "wrong implementation"; both fail acceptance. So the fix does NOT belong in the verifier. Two options, both involved: **(a) agent-side** — after any `write_file`, read the file back to confirm the write landed (general robustness, but the agent doesn't know it's a code-build task or the acceptance); **(b) harness-side** — snapshot the target before the task, and if acceptance fails AND the file is byte-identical to the snapshot, classify it "write did not land — rung not attempted" (distinct from a real fail) and optionally re-fire once. (b) is the cleaner, code-build-scoped fix. No clean bounded spot → left queued with this analysis rather than a rushed half-fix; promote to a brief if picked up.

- ~~**G21 · admissibility irreversibility from command semantics, not tool name**~~ ✅ DONE 2026-07-22.
  New `_is_irreversible(tool, operation_class, raw)` folds `_DESTRUCTIVE_HINTS` into a first-class
  `envelope["irreversible"]` in `build_envelope`; the governance vendor adapter reads it. 6/6 unit cases + one live
  probe (destructive delete now DENY, was ESCALATE). Ref: TIMELINE 2026-07-22 [FIX] G21.
  **Follow-up still open:** `gate()` builds `local_ctx = {"path": args.get("path")}` only, dropping the
  command for process actions — the envelope path already carries it via build_envelope, but local_ctx
  (what LOCAL adapters see as the raw path) is still command-less for processes. Thread it through if/when
  the policy adapter needs to match on process commands. Size S.

- **G23 · repair-event classifier (state-repair vs expression-repair)** — idea from the Michael Magee
  thread 07-23: the human's clarification turn IS the label. Mine session logs for human turns that are
  clarification requests, classify object/state repairs ("which file do you mean") vs expression repairs
  ("what do you actually mean" — Magee's 6th category, semantic compression). Ratio over time = which
  layer is failing. The coherence drill currently measures STATE only and would pass a phantom-contrast
  response; this is the missing axis. Cheap: a classifier pass over logs, no backend change. Size S-M.
  Ref: LINKEDIN_CONVOS.md Magee r5 07-23.

- ~~**G24 · centralize the DeepSeek model name**~~ — ✅ DONE 2026-08-01 (busy-mode). New
  `core_logic/llm_config.py` `DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")`; imported
  into agent.py/interpreter.py/ambient_loop.py, all 7 literals → the constant. 4/4 ast.parse, env override
  verified, behavior-preserving default. **TRACKED (core_logic/) — in git diff.** Boot-test deferred past the
  08:00 cron. Ref: TIMELINE 2026-08-01 [REFACTOR] G24.

- **G22 · classifier: package/npm install risk tier** — same run: `_classify_process_target` rates
  `pip/npm install` as `dev_tool` → low risk → OPERATIONAL, so the engine allows them. Supply-chain risk
  argues these should be `medium`+ (→ REVIEW). Design call for Alkama; likely raise. Size S.

- ~~**G19 · self_knowledge-block self-test guard**~~ — ✅ DONE 2026-08-01 (busy-mode).
  `tests/test_self_knowledge_block.py` — defensiveness regression (malformed entry doesn't raise, fallback
  chain surfaces content) + live memory.json validation (builds; every active entry resolves non-empty). All
  pass. Ref: TIMELINE 2026-08-01 [UPDATE] G19. **`tests/` gitignored.**

- ~~**G18 · v_datetime long-form date extraction**~~ — ✅ DONE 2026-08-01 (busy-mode). Extracted a shared
  `_day_present(day,text)` helper (`\b0?{day}(?:st|nd|rd|th)?\b`) tolerating leading-zero + ordinal forms,
  word-boundaried; routed both date branches through it; self-test 54→59 (deterministic fixture). Ref:
  TIMELINE 2026-08-01 [FIX] G18. **`tests/` gitignored.**

- **G1 · Daily drill** *(RECURRING)* — cron runs the harness; I analyze + promote + write the report's
  `## Claude's Analysis` + TIMELINE. The GREEN backbone. Size **S–M**. Deps: none. Refs: CLAUDE.md "The Drill",
  `tests/report_analysis_status.py`, `tests/verification.py`.
  **NEW sub-duty (BRIEF_56, 2026-07-07): eQ23 code-build rubric review** — every evening analysis grades
  the build answer on the 5-axis rubric (brief §2), promotes the level on pass (write the next level's
  question + validated acceptance; level-N oracle must FAIL level-N−1's component), diagnoses on fail.
  Phase-1.7 streak flags are IGNORED for Q23. Refs: `briefs/BRIEF_56_CodeBuild_Ladder.md`.
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
  ~~**Remaining:** verify a claimed line/location for L4 quotes (the `value_or_line` extension)~~ —
  ✅ DONE 2026-07-06 (busy-mode): claimed-line check in `v_verbatim_quote` (±3 drift tolerance;
  real-quote-wrong-line → UNVERIFIABLE location-mismatch, never FAIL) + the '"..."'-span extractor gap
  fixed (missed-PASS class); self-test 41→46, 46/46. See TIMELINE 07-06. **G4 fully closed.**
  Refs: `tests/verification.py`.
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
  `infra`; `tests/test_diagnose_failure_retry.py`; TIMELINE 06-27). ~~Remaining: any over-strict key_facts class
  flagged in recent drills~~ — ✅ CLOSED 2026-07-06 (busy-mode): never recurred in a graded run, but the
  audit found the class LATENT (2-fact oracles FAIL on one miss + 5 questions carried question-supplied
  must_include terms) → all 5 oracles broadened with substance synonyms, validated both directions.
  **G7 fully closed.** See TIMELINE 07-06.
- **G8 · Refine the busy-mode skill after the first real run** — read the first `busy-mode-reports/` lifetime
  with Alkama; tighten wherever the "which & why" exposed the skill being under-specified. Size **S–M**.
  Deps: one completed busy-mode lifetime. Refs: `.claude/skills/busy-mode/SKILL.md`, `busy-mode-reports/`.
- **G9 · Docs/TIMELINE/BACKLOG/ROADMAP upkeep** *(RECURRING)* — keep all four in sync; harvest new items here +
  the roadmap. Size **S**. Deps: none.
- **G10 · Pre-checker-era report-analysis triage** — `report_analysis_status.py` flags 21 PENDING reports from
  the pre-checker era (05-22 → 06-11) that will never be retro-analyzed (question states long rotated; ~0
  forward value). They dilute the checker's signal for genuinely-missed *recent* reports. Decide once: stamp
  them with a one-line "pre-checker baseline — not retro-analyzed" partner the checker treats as closed, OR
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

- ~~**G15 · Extend the FAST fidelity guard to date_time completeness**~~ — ✅ DONE 2026-07-06 (busy-mode; `_date_completeness_ok` + 8/8 regression test; see TIMELINE). Original: — *(found 2026-07-05e drill, the
  rotation era's first FAIL)*. `date_time(offset_days=-25)` returned the complete correct block; format_llm
  condensed it to just "Wednesday." — dropping the demanded date (real FAIL, weekday coincidentally right).
  Same class as the numeric guard's origin (65536→65636) but COMPLETENESS on date_time, which the guard
  doesn't cover (python_repl-scoped). Fix shape: if the raw date_time output contains the computed target
  block, the formatted response must preserve the target date (else return raw) — mirrors `_run_fast`'s
  numeric guard. Contained, self-testable. Size **S**. Deps: none. Refs: `core_logic/agent.py` _run_fast
  guard, `reports/2026-07-05-evening.md` Q21 analysis, logs/session_2026-07-05_20-01-02.log.
- ~~**G16 · Harness API-validity pre-flight**~~ — ✅ DONE 2026-07-06 (busy-mode, same-day as the 402
  casualty it answers): `api_is_usable()` gates the run after reachability; 402/401 → clean skip + Telegram,
  no fail_count pollution. Live-validated against the real outage. See TIMELINE 07-06.
- ~~**G14 · Coherence-drill FILESYSTEM leak (fixture wrote a real file)**~~ — ✅ INVESTIGATED + MITIGATED
  2026-07-06 (busy-mode): mechanism nailed (manager-her T2 read as a real ask → DELIBERATE write_file);
  offending turn rephrased write-safe (probe intact, scorer 24/24); deadlines.md deleted (content preserved
  in log/brief). **Durable class-fix briefed → BRIEF_55** (test-mode write-DENY via the admissibility gate —
  see 🔴 below). Original: *(found 2026-07-02 during commit
  prep)*. `deadlines.md` appeared at repo root, created 2026-07-01 08:10 MID-CRON, containing "API spec due
  Friday (requested by **Priya**)" — Priya is the FICTIONAL coherence-drill manager. `memory_mode=ephemeral`
  isolates *memory*, but drill tool-calls still EXECUTE — a dialogue turn helpfully wrote a real file. Same
  class as the 06-07 fixture-memory pollution, via the filesystem. Investigate the 07-01 08:00 session log
  (which turn wrote it); fix options: coherence dialogues get `write-safe` phrasing, OR the drill gets a
  tool-sandbox/dry-run mode, OR probe answers that *would* write are asserted-not-executed. File is now
  gitignored (fictional content must not be committed); do NOT delete until investigated. Size **S–M**.
  Deps: none. Refs: `deadlines.md`, `tests/coherence_dialogues.json` manager-her, `logs/session_2026-07-01_08-00-55.log`.

- **G17 · Per-turn timeout on the ReAct `stream()` call** *(found 07-08e; reconfirmed 07-31 Q09/Q23)* —
  **BRIEFED 2026-08-01 → `briefs/BRIEF_59_PerTurn_ReAct_Stream_Timeout.md`** (delicate core-loop change →
  brief, not blind-build: the timeout branch can't be self-checked without a synthetic hang). Q11 hung
  ~22 min on a frozen DeepSeek stream; 07-31 Q09/Q23 hit the harness 180s read-timeout. Brief proposes an
  inner-coroutine `asyncio.wait_for` (default 120s, env-overridable) so a hung turn fails fast to the
  empty-turn path; includes proposed code + a synthetic-hang test plan + open questions (discard-vs-keep
  partial, timeout value, turn-count semantics, stream cancellation). **Awaiting Alkama's confirm.** Size
  **S–M**. Refs: `core_logic/agent.py` run_task ~1701-1745, `reports/2026-07-08-evening.md` Q11,
  `reports/2026-07-31-*.md` Q09/Q23. **`briefs/` gitignored — not in git diff.**

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
    battery_low / odd_hours / new_app_seen | None. **long_session ✅ DONE 2026-07-06** (busy-mode;
    `detect_long_session` window-walk in salience.py + tick() wiring, 11/11 test, boot-validated — see
    TIMELINE 07-06). **off_rhythm ✅ DONE 2026-07-06**
    (busy-mode, final task of lifetime 5; `detect_off_rhythm` 3-gate design — dominance/hour-deviance/
    still-drifting — 15/15 tests; see TIMELINE 07-06). **Y1b signal set now: battery_low / odd_hours /
    new_app_seen / long_session / off_rhythm.** Next A2 work = the screenshot enrichment pipeline
    (designs locked; PARKED on the vision-backend decision — Alkama's call) + Y1-tuning from shadow data.
    See TIMELINE 06-24.
  - ~~**Y1-remark-character**~~ — ✅ DONE 2026-07-06 (busy-mode). Per-class register in `_llm_remark`
    (odd_hours = playful night-owl tease per Alkama's 07-04 target, one question allowed; long_session =
    warm no-nag; battery = dry+urgent) + **`_remark_fidelity_ok` deterministic backstop** — live sampling
    caught temp-1.1 fabrication ("you checked the battery at 1:15 PM"); every template number must survive
    verbatim and no new clock-times, else the template ships. See TIMELINE 07-06.
  - **Y1-tuning · salience calibration** — LIVE-DATA PHASE (2026-07-08): 5 classes live, feed
    trustworthy (21h bug fixed, TTL 12h), 👍/👎 votes accumulate on the ledger. Chattiness verdict pending
    Alkama; current posture = live, ~2-4 nudges/day expected (long_session dominant). Tune from a week of
    votes, not predictions. **Screenshots: DEFERRED entirely (Alkama 07-08)** — reopens only on
    demonstrated text-only blindness. Size **S**. Deps: a week of vote data + Alkama.
    *(Original 06-24 note: 0/1202 cleared 0.45 pre-retune; odd_hours actionability was raised 0.5→0.6.)*
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
- **Y3 · Stronger semantic retrieval** (Topic 4 Phase 3) — **relevance-gate HALF DONE 2026-08-01 (busy-mode,
  DORMANT)**: cosine floor on the top-k semantic hits behind `SEMANTIC_RETRIEVAL_V2` (default OFF = unchanged;
  ON drops hits below `SEMANTIC_RETRIEVAL_FLOOR`=0.30). Boot-tested both states. TRACKED, uncommitted, ships
  OFF until Alkama flips it. **Still open:** query-expansion before embedding (the other half). Size **M**
  (was M–L). Deps: none. Refs: `core_logic/crud.py:182` get_smart_context, ROADMAP Topic 4, TIMELINE
  2026-08-01 [FEATURE] Y3.
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

- **R20 · the governance partner Phase 1 — wire the partner adapter LIVE in SHADOW (audit real decisions)** — the
  pilot (2026-07-10) proved the adapter + handshake; the agreed next step (both sides) is to flip the
  LIVE gate `ADMISSIBILITY_ADAPTER=noop→partner` while staying `MODE=shadow`, so CLARA calls the governance partner on
  every mutating action and RECORDS the verdict to the local ledger WITHOUT blocking. Alkama reviews the
  pattern; Phase 2 (enforce) comes later, deliberately. 🔴 = arming a live external dependency on the
  tool-execution hot path → build carefully. **Deps/considerations (BRIEF_54 §7.3):** hot-path latency (a
  network call per mutating action — make the gate call non-blocking/budgeted; timeout+fail-open exist);
  the governance partner free-tier 1000-req/mo quota (scope to write/process classes or sample); sort the
  write_file:sandbox-test capability grant (enforced /analyze currently DENYs it). Size **M**. Refs:
  `briefs/BRIEF_54 §7.3`, `core_logic/admissibility.py` `_partner_evaluate`, `tool_executor.py` gate hook.
  **⏩ PROGRESS 2026-07-14 (BRIEF_57):** the hot-path-latency dep is SOLVED in code — shadow now runs the
  remote adapter **fire-and-forget** (daemon thread computes + ledgers under the same receipt; caller gets
  an immediate non-enforced ALLOW), sync retained for enforce; `_ledger_lock` added for concurrent async
  writes; self-test case (8) green. **⏩ 2026-07-14 GO-LIVE:** adapter FLIPPED `noop→partner` +
  `PARTNER_ENDPOINT=analyze` (core_logic/.env; shadow, fail-open) — live on next backend restart. And the
  **governance-audit sweep is BUILT** (`tests/governance_audit.py`, 25-action battery across all classes,
  validated dry+policy with no network, report→`governance_audit_reports/` gitignored, `--live` for real
  the governance partner calls). **Remaining:** (a) restart backend to activate; (b) **partner-side capability grant** so
  verdicts aren't all-DENY (ask drafted); (c) key rotation; (d) run the battery `--live` post-grant.
  **Deferred to enforce:** the synchronous-remote latency on the user-facing path (see BRIEF_57
  `TODO(enforce)` — risk-tiered fast-path / verdict cache / tighter timeout).

- ~~**R18 · BRIEF_55 — test-mode tool sandbox**~~ — ✅ RESOLVED 2026-07-07: Alkama REDIRECTED (writes
  allowed + contained, not denied). Built as BRIEF_56 §1: drill_workspace/ + harness Phase 0.5/3.5 sweep
  (strays deleted+flagged; tracked-mods loudly flagged). Gate stays shadow. See TIMELINE 07-07.

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
- ~~**R19 · Telegram voice phone test**~~ — ✅ PASSED 2026-07-08 (Alkama live-tested from his phone: voice note → Whisper → pipeline → reply, "working just fine").
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
- ~~**R17 · BRIEF_53 — key_facts false-PASS guard**~~ — ✅ DECIDED + BUILT 2026-07-07 (Alkama:
  Option 3 + prompt line). Missing-route judge-PASS → UNVERIFIABLE; 48/48 self-test. See
  TIMELINE 07-07; brief updated. WATCH: small expected rise in key_facts UNVERIFIABLEs.
- **R18 · BRIEF_54 — pre-execution admissibility gate** — ✅ **PHASE 0 DONE 2026-07-02** (Alkama greenlit
  "build the gate + noop ledger + local policy"). `core_logic/admissibility.py` (gate + abstract envelope +
  atomic ring ledger + `noop`/`policy` adapters), hooked at `tool_executor._execute_mcp` (the shared
  FAST+DELIBERATE choke point); self-test 7/7 + live shadow boot-test (write query → 1 ALLOW ledger entry,
  no content leak, shadow never blocks). `.env` armed at phase 0: GATE=on / ADAPTER=noop / MODE=shadow /
  FAIL=open. See TIMELINE 07-02 [FEATURE]. **Remaining phases:** **P1** — `partner` adapter (contract
  CONFIRMED by the the governance partner founder, schema in BRIEF_54 §7) in SHADOW (verdicts logged, real latency measured, nothing
  enforced; needs Alkama to register the agent with the partner + API details). **P2** — enforce-mode pilot
  demo session with the the governance partner founder (benign file_write through ALLOW/REVIEW/DENY; also the enforce-branch live-fire).
  **P3 (far)** — enforce-by-default on high-risk tools + Telegram REVIEW approval loop (needs task-parking;
  separate brief). Known v1 hole (documented): `python_repl` exempt. Deps: P1 needs Alkama's the governance partner
  registration; P2 needs P1 + a scheduled session. Refs: `briefs/BRIEF_54…md` (+§7),
  `core_logic/admissibility.py`, `tool_executor.py` _execute_mcp, `LINKEDIN_CONVOS.md (the governance partner thread).
