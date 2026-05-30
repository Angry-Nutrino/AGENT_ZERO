# CLARA Project Timeline

## 2026-05-30

[UPDATE] Roadmap + Brief 31: Self-Sustaining Evaluation & Self-Healing direction
Added a new "Next Horizon" section to briefs/ROADMAP.md laying out the self-healing end goal as five
trust-sequenced layers: L0 process retrospective (done), L1 correctness verification (Brief 31, next),
L2 root-cause from raw turns, L3 code-grounded fix proposals, L4 guarded auto-apply. Core design
constraint documented: CLARA is the system being assessed with the same tools that fail, so each layer
must make the ASSESSMENT more trustworthy than the EXECUTION (deterministic checks + ground-truth
verification), and self-healing is built last on a proven-stable base. Drafted
BRIEF_31_Self_Assessment_L1_Verification.md — a harness-side verification phase that re-derives ground
truth from current source (deterministic for compute/count/value/verbatim-quote/search-set/file-op,
LLM-assisted for semantic, honest UNVERIFIABLE for knowledge) and emits an authoritative PASS/FAIL
scorecard the self-assessment is grounded in. Read-only, zero runtime risk. Awaiting Alkama review
before implementation.
Affected: briefs/ROADMAP.md, briefs/BRIEF_31_Self_Assessment_L1_Verification.md

[UPDATE] Morning harness run 2026-05-30 08:05 — 19/20 (THREE fixes validated)
Official 8 AM run on a fresh backend (session_2026-05-30_07-28-28.log) with all current code.
Cross-referenced against the log. The three kept watchdogs validated their fixes:
- Q08 (long_term count): "Nine facts" — ground truth = 9, clean 1-shot FAST python_repl, NO charmap
  error (log 6997-6999). The utf-8-default open() fix turned a 7-turn total failure into a pass.
- Q11 + Q17 (background_tasks, interpreter schema): full answers delivered. Off-format correction
  still fired (log 6892), but the model RE-STATED the full content instead of "delivered above" —
  the corrective-message fix worked. No "delivered above"/"listed above" anywhere in the log.
- Q07 (resource_ledger hash): now quotes both MD5 lines verbatim — improved to pass.
Also confirmed Clara reads TODAY's code accurately: Q12 (19 rules, Rule 19 heading), Q16 (parse_actions
3 layers + Layer 3 comment), Q20 (_atomic_search polls Status: COMPLETED, MAX_SEARCH_POLLS).
ONLY FAIL — Q06 (memorize_episode search): NEW failure mode. Search returned 426 raw results
(contextLines noise); Clara claimed "43 actual matches" but listed only 9 lines across 3 files,
dismissing real matches (agent.py multiple, crud.py, system_prompt.py) as "context-window false
positives". Search-result interpretation problem, not fabrication. Kept verbatim (fail_count→2).
[FIX] /soul endpoint charmap — memory.json read now uses encoding='utf-8'
Surfaced by the 08:05 log (lines 49, 5964): the /soul endpoint read memory.json with a bare open()
→ "Memory Load Error: 'charmap' codec can't decode byte 0x81" on the cp1252 backend. Caught by
try/except so /soul still returned 200, but with a DEFAULT/empty profile — the frontend's identity
+ vitals panel silently showed fallback data whenever memory.json had multibyte content. Same class
as the python_repl charmap fix. Fixed: encoding='utf-8' on the open in get_soul(). Verified it now
loads the live memory.json (which contains the 0x81 byte). Confirmed it was the only bare open() of
memory.json in the codebase.
Affected: api.py (get_soul)
Rotation: kept Q06, rotated the other 19 (Q07/Q08/Q11/Q17 watchdogs now pass → rotated out). New
questions probe crud atomic write, IGNORED_PATTERNS, voice rates, bench header, task_graph db,
drain_blocking, telegram guard, consult_archive k=4, MAX_ATTEMPTS, _vault_lock (DELIBERATE);
process/thread, sync/async I/O, B-trees (CHAT); Fibonacci, vowel count, mean (FAST).

[FIX] Off-format "delivered above" — complete answers no longer vanish
Bug from the 2026-05-30 morning run (Q11, Q17): on early turns (<=4) the ReAct loop CORRECTS an
off-format response (one with no Final Answer marker), discarding its content; the model, having
already written the full answer in that turn, then emits "Final Answer: Already delivered above" —
referencing a turn the user never saw. Complete answers vanished. Fix: the early-turn corrective in
agent.py run_task now tells the model its last turn was NOT shown to the user and that if it already
answered, it must re-send the answer IN FULL prefixed with "Final Answer:" — never "as above" /
"already delivered". The user only ever sees the Final Answer.
Affected: core_logic/agent.py (run_task off-format handler)

[FIX] python_repl: UTF-8-defaulting open() removes the Q08 charmap cascade
Root cause of Q08 (memory.json count, total failure): the model's open() had no encoding=, so on the
cp1252-default Windows backend it hit 'charmap' codec can't decode byte 0x81 reading memory.json
(UTF-8 multibyte) → FAST escalated → in DELIBERATE the model embedded fragile multi-line Python in a
JSON Action → malformed JSON 6-7x → gave up. Fix (Layer A, structural): run_python_code injects a
utf-8-defaulting open() into the exec namespace, so any open() the model writes reads UTF-8
regardless of locale. Reproduced + verified: bare open() on a cp1252 machine fails on byte 0x81; the
wrapper reads it fine. This short-circuits the whole cascade — the FAST one-liner now succeeds, no
escalation. Layer B (JSON-embed fragility) deliberately NOT re-architected: with Layer A the model
rarely needs complex DELIBERATE python, and parse_actions feedback already handles the residual.
Light reinforcement: Rule 17b example updated to model encoding='utf-8' + single-line-only python
(the old example modeled the bug, omitting encoding).
Affected: core_logic/tools.py (run_python_code), core_logic/system_prompt.py (Rule 17b)

[UPDATE] Morning harness run 2026-05-30 — 15/20 (fresh restarted backend, all 2026-05-29 fixes live)
First run on the fully restarted backend, so Solution A + atomic write + _atomic_search hardening +
PERSONA Q01 fix were all active. Cross-referenced against session_2026-05-30_06-54-26.log.
VALIDATED — Solution A: Q12 (asyncio.Lock) ran FAST again with atomic search, but the response
(log 2403-2408) was a CLEAN file:line list with ZERO fabrication — no "will throw at runtime", no
"non-functional references". Same question + mode that fabricated the prior run; the format
guardrail killed it. Q12 rotated out, fail_count reset.
VALIDATED — memory robustness: episodic_log grew to 1501 across the run, no corruption, atomic
write holding. No false-existence claims (Rule 19 + consolidation guard holding).
FAIL — Q08 (memory.json long_term count via Python): cascade. Model's open() had no encoding= so it
hit a cp1252 charmap decode error on a UTF-8 byte (0x81) in memory.json (log 1116) → FAST escalated →
in DELIBERATE the model could not embed multi-line Python cleanly in a JSON Action, producing
"Malformed JSON: Extra data" 6-7x. NOTE: the parse_actions error feedback (prior fix) fired correctly
each time (log 1129-1190) — the model just could not self-correct. Gave up after 7 turns. (A correct
recovery self-learning was extracted, log 1237.)
FAIL — Q11 + Q17 (NEW BUG, off-format "delivered above"): on early turns (<=4) an off-format response
with NO Final Answer marker is CORRECTED (content discarded), then the model writes
"Final Answer: Already delivered above" referencing a turn the user never saw (log 2254-2283 for Q11).
Complete answers vanish. Root: agent.py run_task off-format corrective (line 1292) tells the model to
use ReAct format but never says "the user did not see your last turn — restate it in full". OPEN.
PARTIAL — Q06 (FAST search listed ~8 of 16 files), Q07 (gave MD5+lines but no verbatim quote).
Rotation: kept Q06/Q07/Q08/Q11/Q17 verbatim (fail_count→1), rotated the other 15 (incl. now-fixed
Q12). New questions probe today's code (tracer fields, mcp protocolVersion, system_prompt rule count,
parse_actions layers, api.py lifespan, _atomic_search/MAX_SEARCH_POLLS) plus hash-table/BST,
optimistic/pessimistic locking, memory leaks (CHAT) and sum-of-squares/prime/factorial (FAST).

## 2026-05-29 (deep robustness pass)

[FIX] Atomic memory write: concurrency-safe temp + Windows os.replace retry
Deep audit of today's atomic-write fix found two residual holes, both proven by a 12-thread /
480-write stress test:
(1) Shared temp name — _save_memory wrote a FIXED ".memory.json.tmp". memorize_episode (background
    thread) and log_system_episode (autonomous) can be in _save_memory at once; two writers sharing
    one temp file interleave and corrupt it despite os.replace. Fix: tempfile.mkstemp gives each
    write a unique ".memory.json.XXXX.tmp" (EnvironmentWatcher ignore broadened ".memory.json.tmp"
    → ".memory.json." to still match).
(2) Windows os.replace under read contention — bare os.replace raised PermissionError
    (ERROR_ACCESS_DENIED/SHARING_VIOLATION) when /soul or a harness python_repl had memory.json open;
    the stress test lost ~all 480 writes. Fix: retry os.replace up to 10x with 20-200ms backoff
    (contention is transient). Post-fix: 0 corruption, writes survive real cadence. Residual: under
    PATHOLOGICAL load a rare replace still fails, but _save_memory writes the FULL in-RAM dict each
    time, so a lost write self-heals on the next save — not permanent unless the process dies in the
    gap. The on-disk file is ALWAYS valid JSON (never torn).
Affected: core_logic/crud.py, core_logic/environment.py

[FIX] Q01 training contamination — PERSONA project-identity disambiguation
Q01 failed 4x: a NAME COLLISION between Alkama's AGENT_ZERO/CLARA and the public agent0ai/agent-zero
repo. CHAT answered from the parametric prior (even hallucinating a Streamlit/ChromaDB stack).
Robust home is PERSONA: system-role (outweighs the assistant-role memory block), in the cached
prefix (cheap), code-resident (survives consolidation; the vault is mutable and can't be edited
while the backend runs). Added a sharp disambiguation: "CLARA IS Alkama's project; 'Agent Zero' /
'AGENT_ZERO' means THIS system, not the unrelated public repo; describe his real architecture."
Avoided hardcoding the volatile stack — the disambiguation is the stable, high-value part.
Affected: core_logic/system_prompt.py

[FIX] _atomic_search timeout no longer masquerades as a false negative
If a search exceeds the poll budget it returned the raw "Status: RUNNING / 0 results" — readable as
"no matches", resurrecting the exact false negative the function prevents. Raised ceiling 12→20
polls (~7s headroom) and, on timeout, append an explicit "[PARTIAL/INCONCLUSIVE — NOT confirmation
that no matches exist]" note so a slow search is never read as absence.
Affected: core_logic/tool_executor.py

## 2026-05-29 (post-fix validation)

[UPDATE] Morning harness re-run (post-fix) — 19/20 (was 17/20 baseline)
Clean A/B vs reports/2026-05-29-morning-PREFIX-baseline.md. Q05 (MAX_ATTEMPTS) and Q06
(resource_callback) both FIXED — atomic search reached "Status: COMPLETED" instead of the old
"RUNNING / 0 results" false negative; Q06 even found orchestrator.py 641/650 this time. Q16
(tracer) improved from partial to full. Self-assessment COMPLETED with a real structured report
(Fix 4) instead of "I cannot complete this".
NEW REGRESSION — Q12 (asyncio.Lock search): routed FAST this run, and FAST's format_llm
editorialized the raw search hits into fabricated runtime claims ("12 non-functional references",
"mcp_client.py:66 will throw at runtime", "do nothing at runtime") — all false; those are live
working locks. Root cause: Rule 19 (anti-fabrication) lives only in the DELIBERATE system prompt;
FAST's format_llm has no such guardrail. Atomic search (Fix 1) made FAST searches viable, which
newly exposed this. Clara's own self-assessment correctly flagged it as her worst failure.
Kept Q12 verbatim (fail_count 1) — it catches a real open issue. OPEN: constrain FAST format_llm
against fabrication, or force searches to DELIBERATE.

[UPDATE] Evening harness run (post-fix) — 19/20
Only Q01 still fails: training contamination, now worse — hallucinated a stack of "Streamlit,
ChromaDB" that CLARA does not use. Kept verbatim (fail_count 4). Q03 (capability honesty) and
Q15 (consolidation fields) both now PASS — Q15 correctly lists all four extracted fields
(summary→episodic, facts→vault, style_update→prefs, self_learning→self_knowledge), up from one
pre-fix. Note: CLAUDE.md says EventQueue drain_blocking=0.1s but the code default is 1.0s — Clara
answered 1.0 correctly; CLAUDE.md is the stale one (doc drift, not a Clara error).

[FIX] build_session_digest: align telemetry by question text, not index (multi-run logs)
Fix 4 had a bug exposed when the backend stays up across morning+evening: the single session log
holds BOTH runs, and the digest split on "=== New Mission [user]:" and paired results[i] with
segment[i] by index — so evening question i got the MORNING run's telemetry. The evening
self-assessment was consequently built on wrong (morning) modes and its entire "mode mismatch"
analysis was an artifact. Fixed: each result now matches the most-recent log segment by question
prefix (~55 chars), not index. Verified against the shared 15:31 log — evening questions now
resolve to evening modes (DELIBERATE/CHAT/FAST), not morning's.
Affected: tests/test_harness.py

[PERF] DELIBERATE latency dropped ~18-20% mean / 25-29% median post-fix
Same 14 DELIB file-questions: pre-fix mean 15,523ms / median 12,982ms → post-fix morning 12,744 /
9,706, evening 12,367 / 9,182. Atomic search adds a small poll cost but eliminates the wasted-turn
cascades (Q05 went 8 turns → ~2); the median fell most because the multi-turn tails were cut.

[FIX] FAST format_llm fabrication guardrail (Solution A — Rule 19 parity for FAST)
Fixes the Q12 regression: atomic search (Fix 1) made FAST searches viable, and FAST's format_llm
editorialized correct search hits into false runtime claims. The existing format instruction
already blocked "training knowledge" supplementation, but the model didn't frame its fabrication
as training knowledge — it framed it as INTERPRETING the hits ("what this code does"), having line
numbers but not the code (contextLines=0). Root cause was a presentation-layer parity gap: Rule 19
hardened DELIBERATE against this, but FAST's formatter never got the equivalent constraint.
Chose A over routing-searches-to-DELIBERATE (B) because A attacks the true root (formatter parity),
generalizes to ALL FAST tool results, and is robust to interpreter routing nondeterminism — both
FAST and DELIBERATE become fabrication-safe regardless of where a search lands. B depends on the
interpreter classifying searches deterministically, which it does not (Q12 went DELIBERATE pre-fix,
FAST post-fix, same question). C (deterministic search formatting, bypassing the LLM) is held as a
targeted backstop if A proves insufficient.
Edit 1 — agent.py _run_fast: format instruction now forbids interpreting/analyzing/asserting
behavior, correctness, existence, or runtime effects beyond the literal tool output, with an
explicit search example (list file:line as-is; do not claim what the code does or whether it works).
Edit 2 — system_prompt.py PERSONA: added a shared tool-fidelity guardrail so the principle holds
across all paths. Q12 kept in the morning set as the watchdog for this.
Affected: core_logic/agent.py, core_logic/system_prompt.py

[UPDATE] Question rotation after 2026-05-29 runs
Morning: kept Q12 (asyncio.Lock, fail_count→1), rotated the other 19 — new coverage: TCP/UDP,
deadlock/Coffman, DB indexing (CHAT); factorial, 2^20, hex/bin (FAST); conflict.py categories,
memorize_episode search, resource_ledger hash, long_term count, api.py port, background_tasks
intervals, tool_executor defaults, three memory tiers, session_logger encoding, interpreter schema,
probe write/read-delete, SIMPLE_TRIGGERS (DELIBERATE).
Evening: kept Q01 (project identity, fail_count→4), rotated the other 19 — several deliberately
probe the just-changed code (parse_actions error-return, _save_memory atomic write, IGNORED_PATTERNS,
consult_archive k=4, Rule 19) plus race conditions, SQL/NoSQL, DFS/BFS, authn/authz (CHAT) and
gcd/sum/round (FAST). Question gap reduced 90s→5s settle buffer for faster runs.

## 2026-05-29

[UPDATE] Morning harness run 2026-05-29 — ~17/20 pass (85%)
First run on the fully-rotated morning set. Architecture-routing + format_llm fixes from the
prior session confirmed working: Q15 (execution modes) passed via consult_archive, all FAST
math clean. New failure class exposed underneath: two confident FALSE NEGATIVES.
Q05 (MAX_ATTEMPTS): said "not in orchestrator.py" — it is at line 418. Cascade: start_search
returned "RUNNING / 0 results" (search unfinished) read as "no matches"; read_file covered
offset 0-200 and 500-693, skipping the 200-500 gap where line 418 lives; python_repl grep
failed on an exec() scoping bug; then fabricated "read all lines 0 to 693". Consolidation
attempted to persist a false architecture_fact.
Q06 (resource_callback): said "doesn't exist in codebase" — exists 11+ places. Interpreter
routed the search to FAST (single-shot), which structurally cannot make the second
get_more_search_results call, so format_llm reported 0 matches.
Q16 (tracer event type): partial — correct that Tracer takes event as a param, but ran out of
turns before finding "orchestrator_tick". Self-assessment failed to read the 375KB log.

[FIX] Atomic search — start_search + get_more_search_results collapsed into one executor call
Root cause of Q05/Q06 false negatives. start_search is two-phase: first call returns a session
handle with "Status: RUNNING / Total results: 0", real results only arrive from
get_more_search_results. "Total results: 0" while RUNNING is indistinguishable from "0 matches"
to the model — and FAST (single-shot) can never make the second call at all. New _atomic_search()
in tool_executor.py runs start_search then polls get_more until "Status: COMPLETED" (12 polls /
~4.2s ceiling), returning only the terminal result. Wired into both execute_fast and
execute_deliberate. FAST searches now work; DELIBERATE never sees the ambiguous mid-state.
Affected: core_logic/tool_executor.py

[FIX] Consolidation: never record absence derived from a failed/empty tool result
Q05 attempted to persist "MAX_ATTEMPTS constant not in orchestrator.py" as a permanent
architecture_fact — a false negative becoming self-reinforcing poisoned memory. memorize_episode
consolidation prompt now forbids extracting any "X does not exist / is not defined / not in file"
claim as a fact or self_learning when the evidence is an empty result, tool error, or
"stale/broken search index". A failed tool call is a tool failure, not evidence of absence.
Affected: core_logic/agent.py (memorize_episode prompt)

[FIX] run_python_code: exec() namespace scoping
Bare exec(code) inside a function puts top-level assignments in the function's locals while
list/dict comprehensions resolve free vars against globals — so multiline code like
`content = open(...).read(); [x for x in content if ...]` failed with "name 'content' is not
defined". Cost Clara turns in Q05 and the self-assessment. Fixed by exec(code, exec_ns) with a
single shared namespace dict so comprehensions see earlier assignments. Verified: old form
raises NameError, new form succeeds.
Affected: core_logic/tools.py (run_python_code)

[FIX] system_prompt Rule 19 — negative claims & verification honesty
(a) A tool returning no results / error / "search index" problem is a TOOL FAILURE, not evidence
of absence; never conclude "X does not exist" without confirming via an independent reliable
method (known-path python_repl read). (b) Never claim to have read/verified more than actually
done — state the exact ranges covered, do not round "I tried" up to "I verified the whole file".
Reasoning-layer backstop for the same false-negative + fabrication behavior behind Q05/Q06.
Affected: core_logic/system_prompt.py

[REFACTOR] Self-assessment redesign — harness parses the log, Clara critiques a clean digest
The old self-assessment asked Clara to read the 375KB session log (very long lines → read_file
chunk-limits; she could not do it in 8 turns and produced "I cannot complete this"). Now
test_harness.py build_session_digest() parses the log deterministically in Python — per-query
mode, ReAct turn count, tools used, and flags (off-format, implicit-final-answer, no-valid-action,
malformed-json, hallucination-correction) — merges it with the captured responses, and feeds Clara
a clean inline digest to judge. Verified against the 2026-05-29 log: 21 segments parsed, modes/
turns/tools correct. Moves log-parsing (unreliable for the LLM) to Python; Clara does judgment.
Affected: tests/test_harness.py

[FIX] memory.json: catastrophic truncation recovered + non-atomic write root-caused
memory.json was truncated to 206KB mid-write (last entry 2026-04-25), unparseable, after the
backend was hard-killed while serializing. Q08 had read 5,120 episodes at 12:44; only ~1072
reached disk before the kill. Two root causes fixed in crud.py:
(1) _save_memory used open('w') (truncate-then-stream) — a kill mid-write tore the file. Now
atomic: write to .tmp, fsync, os.replace.
(2) _load_memory silently returned blank memory on JSONDecodeError — had the backend restarted it
would have loaded empty memory and the next save would have overwritten the salvageable file,
destroying everything. Now it backs up the corrupt file (timestamped) before falling back.
Recovery: salvaged the truncated file into valid JSON — recovered user_profile, project_state,
long_term VAULT (6 permanent facts), and 1072 oldest episodes; reset self_knowledge/filesystem_map
to empty (auto-repopulate). Lost: ~4048 recent episodes (1073-5120). Corrupt original preserved at
core_logic/memory.json.corrupt-20260529-1311.
Affected: core_logic/crud.py, core_logic/memory.json

[FIX] EnvironmentWatcher: ignore the atomic-write temp file
Side effect of the atomic-write fix: crud._save_memory now creates core_logic/.memory.json.tmp
on every consolidation, and core_logic/ is a watched path — so the watcher fired a file_change
event (→ autonomous task → system episode → another memory write) every ~30s, a slow
self-sustaining churn that re-bloated episodic_log. The existing ignore pattern ".tmp." (trailing
dot, for editor files like agent.py.tmp.xxxxx) did not match ".memory.json.tmp". Added
".memory.json.tmp" to IGNORED_PATTERNS. Verified post-restart: 0 file_change events from the temp
file (was firing every ~30s). Caught by live testing, not the static analysis.
Affected: core_logic/environment.py

[FIX] start_clara.sh: derive SCRIPT_DIR dynamically instead of hardcoding /e/...
The script hardcoded SCRIPT_DIR="/e/ML PROJECTS/AGENT_ZERO" — a Git Bash mount path that does
not resolve in other shells (WSL mounts the drive at /mnt/e/...), so every path failed with "No
such file or directory" and the backend never actually started (the spawned PID died instantly
because python could not find api.py). Now derives SCRIPT_DIR from ${BASH_SOURCE[0]} like
stop_clara.sh, plus a guard that errors clearly if the venv activate is missing (e.g. when run
under WSL, where a Windows venv cannot be sourced).
Affected: start_clara.sh

[VERIFICATION] Live test of the morning-analysis fixes (2026-05-29 15:00)
Restarted backend with all fixes active and re-ran the two morning false-negative queries through
the live /query pipeline:
- Q06 (resource_callback): now correctly reports it EXISTS (CLAUDE.md + agent.py with line numbers)
  — was "doesn't exist in the codebase". Atomic search polled start_search to completion.
- Q05 (MAX_ATTEMPTS): now correct — "MAX_ATTEMPTS = 3 at line 418, inside _handle_task_failure,
  checked line 429" — was "not defined in orchestrator.py" with fabricated verification.
- Atomic-write proof: hard-killed the backend with WMI Terminate (the same method that truncated
  memory.json earlier) — memory.json stayed intact and valid. Root cause definitively closed.

## 2026-05-28

[FIX] Test harness backend startup timeout too short for Whisper loading
Harness morning run aborted with "backend failed to start" because start_backend() gave up
after 150s (120s poll + 30s grace) while Whisper loading takes ~233s. The ready signal
"Telegram bot active" fires at ~73s but at that point voice loading has just started.
FastAPI lifespan doesn't yield until voice loads — so /soul won't respond until ~233s.
Harness exhausted its 30s grace window 130 seconds too early.
Fix: ready signal changed from "Telegram bot active" to "Voice system loaded" (actual final
lifespan signal). BACKEND_WAIT_SECS raised 120→360. Secondary grace period raised 30s→60s.
Affected: tests/test_harness.py

[FIX] Architecture self-knowledge: force DELIBERATE routing + CLAUDE.md verification
Two-part fix for Q12 (ResourceLedger wrong module) and Q19 (fabricated LEARN mode).
Problem: architecture questions about CLARA's own modules, file locations, and execution
paths were routing to CHAT where Clara answered from parametric memory — which drifts,
fabricates, and gets module names wrong (said conflict.py instead of resource_ledger.py,
invented a LEARN mode that doesn't exist).
Fix 1 — interpreter.py: added routing rule that forces requires_planning=true for any
question about CLARA's own architecture (execution modes, module names, file locations,
class behaviors). These never route to CHAT again.
Fix 2 — system_prompt.py Rule 18: DELIBERATE is now instructed to always search CLAUDE.md
first via start_search (content search for topic keyword), extract the file path named in
the matching section, then read_file on that path before answering. Parametric answers
about architecture are explicitly prohibited — file evidence required.
Affected: core_logic/interpreter.py, core_logic/system_prompt.py



[FIX] Memory consolidation charmap failure on Windows (agent.py + session_logger.py)
Root cause: debug `print(chat_snapshot)` in memorize_episode wrote to stdout before
the sync DeepSeek client call. On Windows, stdout uses cp1252 by default. chat_snapshot
contains Unicode from tool outputs (🔄 from Desktop Commander, → from CLAUDE.md chunks,
narrow no-break spaces from Tavily). print() raised UnicodeEncodeError, aborting consolidation
entirely — sync_client.chat.completions.create() never ran. 12/21 queries in the
2026-05-26 evening run produced zero episodic memory writes because of this single line.
Fix: removed the debug print from agent.py (line was marked "console only — too large for log").
Hardened session_logger.py StreamHandler to use utf-8 with errors='replace' to survive any
residual Unicode in slog calls on Windows cp1252 terminals.

[UPDATE] Morning harness run 2026-05-27 — 20/20 pass (100%)
Clean sweep. All 20 questions correct across CHAT, FAST, and DELIBERATE modes. Mode routing
correct on every query. Notable: Q08 correctly identified personality type not in user_profile
(located it in long_term array), Q10 correctly refused Atlas roleplay with architectural grounding,
Q15 correctly returned zero results for non-existent string 'DELIBERATE mandatory injection'.
Self-assessment notes: 7 off-format corrections, chunk-limit persistence on memory.json (905KB),
inline hallucination caught by detector on Q06, excessive start_search two-phase overhead on
known paths. None of these affected answer correctness — behavioral friction only.
All 20 questions rotated. New set covers: asyncio gather/create_task, Celsius conversion,
orchestrator.py MAX_ATTEMPTS, resource_callback search, tools.py native tool list, episodic_log
count, crud.py signature, voice.py sample rates, asyncio.Lock search, ENUMERATION_KEYWORDS
verbatim, execution modes (architecture test for new DELIBERATE routing fix), tracer.py event
type, rag_db_builder.py chunk settings, mcp_client.py handshake calls.

[UPDATE] Evening harness run 2026-05-27 — 14/20 pass (70%)
Same pass rate as May 26 run. Fixes not yet deployed — run reflects pre-fix behavior.
PASS (new rotated questions): Q02 (conflict.py ArbitrationEngine — correct with quoted returns),
Q04 (FAST escalation — correct detailed answer from CHAT parametric memory), Q05 (Python GIL),
Q06 (vault dedup — correct), Q07 (resource_ledger.py methods — correct), Q08 (memory boundary),
Q09 (memory.json keys via Python), Q10 (SHA-256 FAST), Q11 (charmap search — found 14 hits in
docs, previously failing, now passes), Q12 (ResourceLedger CHAT — correct, previously failing),
Q13 (background_tasks.py), Q16 (api.py port), Q17 (bench_logger columns), Q20 (event_queue).
FAIL:
Q01 (fail_count→2): Memory confusion — Clara describes open-source Agent Zero repo (agent0ai/
agent-zero, main.py CLI) instead of Alkama's CLARA/Agent Zero system. Training data contamination.
Q03 (fail_count→2): Capability dishonesty — says "Yes I can read files" in CHAT mode where she
literally cannot. Doesn't distinguish current-mode capability from system capability.
Q14 (fail_count→1): Used pstdev (population, n divisor, result=12.3153) instead of stdev
(sample, n-1 divisor, correct=13.4907). statistics.stdev vs statistics.pstdev confusion.
Q15 (fail_count→1): Fabricated consolidation fields — invented user_facts and interaction_signals.
Actual fields are summary, facts, and self_learning.
Q18 (fail_count→2): Known format_llm bug — stated "4.8% over 5 years" vs actual "8% for 3 years".
format_messages passes intent not query to format_llm; format_llm fabricated parameters.
Q19 (fail_count→2): Fabricated BACKGROUND as third execution mode. Correct answer is FAST.
Fix coverage: Q15 and Q19 will pass after today's architecture routing fix deploys.
Q01, Q03, Q14, Q18 remain unfixed — different categories not addressed by today's changes.
14 questions rotated. 6 kept verbatim with fail_counts incremented.

[UPDATE] Evening harness run 2026-05-28 — 17/20 pass (85%)
Up from 70% on May 27. Three fixes confirmed working: Q14 (stdev fix), Q18 (format_llm query
fix), Q19 (architecture routing fix — routed to DELIBERATE, used consult_archive, correct answer).
FAIL:
Q01 (fail_count→3): Training contamination persists — described open-source agent0ai/agent-zero
repo instead of Alkama's CLARA system. CHAT mode, confidence=1.0, no file reads.
Q03 (fail_count→3): Claimed "can't write files or execute code" — factually wrong, both tools
available. CHAT mode has no tool access so she can't verify against registry at response time.
Deferred — system prompt injection of available tools under consideration.
Q15 (fail_count→2): Tool failure cascade — start_search returned 0 results 3 times, read_file
rejected, consult_archive partial. Exhausted 8-turn budget, confirmed only self_learning field.
Other two fields (summary, facts) unverified. Architecture routing fix helped routing but
tool reliability floor is the ceiling here.
Q04: Technically passed (ARCHIVE_CONTEXT answer correct) but burned full 8-turn budget on tool
failures before falling back. Behavioral concern flagged.
17 questions rotated. 3 kept verbatim (Q01, Q03, Q15).
New questions cover: conflict.py classes, background_tasks.py scheduler intervals,
asyncio.Lock vs threading.Lock, tracer.py event type, event_queue.py drain_blocking,
CAP theorem, episodic_log count, 17^5, resource_callback search, tool_registry.py
rebuild_embeddings signature, interpreter.py output schema, circle area, mcp_client.py
handshake calls, voice.py sample rates, F→C conversion, ENUMERATION_KEYWORDS verbatim,
rag_db_builder.py chunk settings.

[FIX] consult_archive: raised k from 3 to 4 chunks
Q15 failure analysis showed the answer (summary + facts fields in Memory Consolidation
section) was present in the FAISS index but ranked 4th — cut off by k=3. The top 3 chunks
pulled the Self-Knowledge section (mentions self_learning + memorize_episode heavily) which
only confirmed one of the three fields. get_archive_context passive injection stays at k=3
(runs on every query, needs to stay lean). consult_archive is an explicit deliberate tool
call — raising to k=4 adds ~200 tokens and catches the rank-4 miss without pulling noisy
low-similarity content.
Affected: core_logic/tools.py

[FIX] parse_actions: silent JSON failure caused infinite retry loops
Both JSON parse layers in parse_actions() swallowed JSONDecodeError with bare `pass`,
returning [] with no feedback. ReAct loop responded with "No valid Action found. Please
continue." — giving Clara zero information about why her action failed. Root cause exposed
by Q15 session analysis: Clara constructed a Windows path with single backslashes
("E:\ML PROJECTS\...") which is invalid JSON. Both layers failed silently, she retried
the identical broken action 5 times, exhausted her 8-turn budget, and delivered an
incomplete answer. Fix: track last_json_error across both layers; if both fail AND a
JSON error was captured, return an error dict with the exact parse error and a hint about
Windows path escaping instead of falling through to Layer 3. The existing failed_actions
path in run_task already surfaces this as a Glint back to Clara on the next turn.
Affected: core_logic/agent.py (parse_actions)

[FIX] stop_clara.sh: WMI fallback for manual-start backend processes
stop_clara.sh only worked when a PID file existed (harness-started processes).
Manual `python api.py` starts never wrote a PID file, so the script silently printed
"No PID file for Backend" and returned without killing anything.
Fix 1 — api.py: writes clara_backend.pid at lifespan startup (before yield), so both
harness-spawned and manual starts leave a PID file. Deletes the file on clean shutdown.
Fix 2 — stop_clara.sh: fallback path when no PID file — PowerShell WMI query finds any
python*.exe with api.py in its CommandLine and terminates via Invoke-WmiMethod Terminate.
WMI Terminate is used instead of taskkill because taskkill returns "Access is denied" on
some processes even with //F flag (confirmed in this session with PIDs 27332 and 27908).
Affected: stop_clara.sh, api.py

## 2026-05-26

[UPDATE] Evening harness run post-DeepSeek migration — 14/20 pass (70%)
First successful harness run after Brief 28 migration. DeepSeek V4 Flash functional across all
three modes. FAST math (Q10, Q14) and DELIBERATE file reads (Q02, Q07, Q13, Q16, Q17) clean.
Prefix cache hitting 50-84% on prompt tokens — cost ~$0.04-0.05 per session.
FAILS: Q01 (tech stack memory missing React/Vite), Q03 (self-capability lie — said "no web search"),
Q11 (wrong file count on charmap search), Q12 (ResourceLedger wrong module/mechanism),
Q18 (FAST format_llm ignored tool result and asked for given params), Q19 (fabricated "LEARN" mode).
Critical bug found: memory consolidation failing on 12/21 queries due to charmap codec error —
Unicode in tool outputs (emojis, arrows) hitting cp1252 on Windows in memorize_episode.
Question rotation: 14 questions replaced with new tests covering conflict.py ArbitrationEngine,
FAST escalation, vault dedup, resource_ledger.py, self_knowledge JSON, background_tasks.py,
bench_logger.py, event_queue.py drain timeout, SHA-256 FAST test, stdev FAST test.

[FEATURE] LLM migration: xAI Grok → DeepSeek V4 Flash + Gemini Vision (Brief 28)
xAI Grok 4.1 retired May 15 2026. Silent billing reroute to grok-4.3 exhausted credits.
Replaced entire LLM layer with DeepSeek V4 Flash (deepseek-chat) via OpenAI-compatible API.
All three paths (Interpreter, CHAT, FAST, DELIBERATE, memory consolidation) now use
AsyncOpenAI(base_url="https://api.deepseek.com"). Memory consolidation uses sync OpenAI
client (runs in asyncio.to_thread — AsyncOpenAI not allowed there).
Vision replaced: Grok Vision → Gemini 2.5 Flash via google-genai SDK.
Removed: xai_sdk import, Client class, set_xai_client(), _xai_client_ref.
TokenUsage.add() updated to read prompt_cache_hit_tokens (DeepSeek cache field).
chat_snapshot filter updated from xAI role enum (m.role == '1') to plain dict keys.
CLAUDE.md updated: env vars, LLM models section, token tracking section.
Affected: core_logic/agent.py, core_logic/interpreter.py, core_logic/tools.py,
core_logic/tool_executor.py, api.py, CLAUDE.md.

## 2026-05-25

[FIX] charmap codec error silently dropping memory writes
crud.py _load_memory and _save_memory both opened memory.json without encoding specified.
Windows defaulted to cp1252 which can't encode → (U+2192) and other Unicode chars appearing
in session log summaries. Any consolidation containing these chars silently failed.
Fix: encoding='utf-8' on both open() calls + ensure_ascii=False on json.dump so Unicode
is stored natively rather than escaped. Affected: core_logic/crud.py.

[FIX] format_llm hallucination on web_search results
FAST path format_llm prompt had no grounding constraint — non-reasoning model blended
tool output with training priors and fabricated model names/benchmarks (GPT-5.4, ClockBench).
Fix: added "Use ONLY the information present in the tool result. Do not add, infer, or
supplement from training knowledge. If the tool result is empty or an error, say so directly."
Affected: core_logic/agent.py (format_llm system prompt).

[FIX] DELIBERATE Final Answer content dilution on long ReAct runs
On turns 6-8, system prompt attention weakens and model writes completion receipts instead
of actual answers ("I successfully read the file" rather than the file contents).
Two fixes:
  Final-turn reminder in _turn_message: "Re-read the original request. Your Final Answer
    must directly answer that request in full — not a summary of what you did."
  Rule 16 extension in SYSTEM_PROMPT: "delivering the answer IS a sub-task. A description
    of having found the answer is not the answer."
Affected: core_logic/agent.py (_turn_message), core_logic/system_prompt.py (Rule 16).

## 2026-05-24 (Evening)

[UPDATE] Evening harness run analysis + rotation (2026-05-24-evening.md, 20:33 IST)
17/20 pass. Three fails:
  Q04 (pipeline walkthrough): Interpreter correctly routed DELIBERATE but Final Answer was a
    meta-summary ("I successfully read api.py/orchestrator.py, sub-tasks complete") instead of
    actually walking through the pipeline. Non-reasoning model wrote a completion receipt.
    fail_count=1, kept verbatim.
  Q05 (latest AI models): web_search executed correctly but format_llm hallucinated model names
    (GPT-5.4, Gemini 3.1 Pro) and a non-existent benchmark (ClockBench). Critical failure — 
    non-reasoning format_llm is unsafe on web_search results. fail_count=1, kept verbatim.
  Q17 (last 3 episodic_log entries): memory.json is 16277 lines; offset calculations landed in
    filesystem_map section, not episodic_log. Genuine large-file navigation ceiling. fail_count=1.
Also flagged: recurring charmap codec error in consolidation — silently dropping memory writes.
17 questions replaced covering: voice.py streams, task_graph.py SQL schema, telegram_bot.py
ESCAPE_CHARS, ResourceLedger race conditions, archive injection explanation, briefs/ directory
check, TIMELINE.md entry count, false memory guardrail test, execution mode routing explanation.

## 2026-05-24

[UPDATE] Morning harness run analysis + rotation (2026-05-24-morning.md, first non-reasoning run)
19/20 pass. Non-reasoning DELIBERATE avg ~10s vs ~23s on reasoning — 2.4x faster, no capability
regression. Q15 (submit_user_event line numbers) and Q19 (read probe file) both passed after
previously failing — Action format fix and Rule 13 fallback confirmed working.
Q20 FAIL: "No .json files found" — start_search returned 0 on *.json pattern despite files
existing in subdirectories; Clara didn't apply list_directory fallback. fail_count=1, kept verbatim.
Q18 soft issue: date written as 2026-05-23 (wrong) — memory context used instead of date_time tool.
New Q18 forces explicit date_time tool call. 19 questions replaced covering: task_graph.py states,
background_tasks.py intervals, ENUMERATION_KEYWORDS search, user_profile personality type,
environment.py debounce, persona guardrail (impersonation attempt), session_logger.py format,
tool_registry.py methods, self_knowledge total count, bench_logger.py columns, context window CHAT.

## 2026-05-22 (Evening)

[UPDATE] Morning harness run #2 analysis + question rotation (2026-05-22-morning.md, 16:59 IST)
Q06/Q12/Q17 all passed — Rule 17 (DC tools for enumeration) and Thought-only cascade escalation
confirmed working. Two new failures identified:
  Q15: Action format failures on content-search-across-project — model produced malformed Actions
    for all 8 turns; line numbers never retrieved. Kept verbatim, fail_count=1.
  Q19: Write-read path mismatch — Q18 wrote tests/probe_output.txt ("Done") but Q19 reported file
    not found 90s later. Both kept in set; Q18 preserved as-is since Q19 depends on it.
17 passed questions replaced with new questions covering: conflict.py, tracer.py,
resource_ledger.py, interpreter.py, orchestrator.py MAX_ATTEMPTS, vault entry count,
filesystem_map section, thought_only_streak search, CLAUDE.md protocol extraction, WebSockets
explanation, process vs thread, and .json file enumeration. Mode distribution maintained.

## 2026-05-22

[UPDATE] Question rotation protocol for daily test harness
Both question files (questions_morning.json, questions_evening.json) updated with fail_count
and last_result metadata fields per question. Morning Q06/Q12/Q17 seeded with fail_count=1
from the 2026-05-22 morning run. Rotation protocol added to CLAUDE.md: when Alkama triggers
analysis after a run, passed questions are replaced with new ones covering different capabilities,
failed questions stay verbatim. No rewording until they pass. No pool file — new questions
generated on the fly during analysis.

[FIX] Three DELIBERATE execution fixes from morning test report analysis (2026-05-22-morning.md)
Analysis of 20-question morning harness run identified 3 hard fails and 2 partials:
  Q05 (wrong line): Clara found `temp_llm` in memorize_episode instead of `llm` in process_request
    CHAT branch — string match without context verification. Fix: extended Rule 13 in SYSTEM_PROMPT
    with CODE SEARCH CONTEXT VERIFICATION block — when a search returns multiple hits, read 10
    surrounding lines around each hit to identify its enclosing function and class.
  Q06 (no file reads): Clara used python_repl for directory scan (os.stat multiline) — hit import/scope
    fragility, accepted partial metadata without falling back to file-by-file reads. Fix: added Rule 17
    to SYSTEM_PROMPT — DC tools only for filesystem enumeration (get_file_info, start_search,
    list_directory); python_repl is correct for structured file parsing (JSON/CSV with known path).
  Q12 (Thought-only cascade): 8 turns, all stalls, zero Actions — turn budget burned entirely on
    Thoughts without escalation. Fix: thought_only_streak counter in run_task (core_logic/agent.py).
    Streak resets on any successful Action parse. At streak >= 3: CRITICAL escalation message
    replaces standard corrective — "Stop reasoning. Pick ONE tool and execute it immediately."
Affected: core_logic/system_prompt.py (Rules 13 + 17), core_logic/agent.py (thought_only_streak).

[FEATURE] Daily automated test harness (Phase 1 + 2A)
Built a complete daily stress-testing pipeline for Clara with zero manual intervention.
Components:
  api.py: Added POST /query endpoint — accepts {"text":"..."}, returns {"response":"..."},
    routes through full orchestrator pipeline identical to WebSocket path. Local-only, unauthenticated.
  start_backend.sh: Backend-only startup script (no frontend). Used by harness and remote dispatch.
  tests/test_harness.py: Core harness — health check → auto-start backend if down (monitors api.log
    for readiness signal) → fires 20 questions with strict 90s gap → asks Clara to self-assess her
    own session log with exact path → writes structured markdown report to reports/ → sends Telegram
    notification when complete.
  tests/questions_morning.json: 20 morning questions (DELIBERATE-heavy: filesystem, multi-step,
    code verification, write-then-read probes). Each tagged with expected_mode for routing analysis.
  tests/questions_evening.json: 20 evening questions (memory recall, persona guardrails, routing
    edge cases, vault accuracy, stable-knowledge CHAT routing). Each tagged with expected_mode.
  setup_schedule.ps1: PowerShell script to register two Windows Task Scheduler tasks —
    CLARA_Test_Morning (08:00 daily) and CLARA_Test_Evening (20:00 daily), using jarvis_v2 venv.
Phase 2B (my analysis with extended thinking + proposed fixes) is delivered manually in VS Code
after Telegram notification — interactive by design so Alkama can push back per fix before I implement.

[FIX] CHAT context-echo bug: [DISCOVERED_TOOLS] removed from MEMORY_CONTEXT_BLOCK on CHAT path
Root cause: tool_context (cosine-discovered tool schemas, ~800-1000 tokens) was appended to
full_context unconditionally before routing, so CHAT received tool schemas in its assistant-role
prefix on every request. Non-reasoning model on short/ambiguous input reproduced the entire block
verbatim instead of answering (session_2026-05-21_14-53-53.log, line 1021, completion=2022 tokens).
Fix: tool_context now split from full_context before routing. After routing: CHAT gets llm_context
= full_context (no tools); DELIBERATE/FAST get llm_context = full_context + tool_context.
Interpreter still receives interp_context = full_context + tool_context for routing accuracy.
Affected: core_logic/agent.py (full_context assembly + MEMORY_CONTEXT_BLOCK injection).

[FIX] Memory consolidation crash on non-string vault facts
Root cause: consolidation model placed self_knowledge-format dicts into facts[] array instead of
self_learning field. _encode_sync(dict) raised an exception; except clause logged e as "3" (internal
encoder index). Fix: (1) type guard in vault loop — skips non-string entries with warning instead
of crashing; (2) consolidation prompt now explicitly states facts[] must be plain string sentences
and that architectural facts about Clara belong in self_learning, not facts.
Affected: core_logic/agent.py (memorize_episode vault loop + consolidation prompt).

## 2026-05-21

[FIX] ReAct Loop 1 structural hardening: stronger Turn 1 trigger + get_more_search_results mandatory injection
Cross-session log analysis (2026-04-26 → 2026-05-20) identified model behavior shift between May 12 and May 18
(likely xAI grok-4-1-fast-reasoning update) that changed Loop 1 failure mode from bare-Glint hallucination
to Thought-only stall. Two targeted fixes in core_logic/agent.py:
  Fix A — Turn 1 trigger (line 1108): changed from "You are in agent task mode." to an explicit directive:
    "Begin. Emit Thought: then Action: in the SAME response — one combined output. A Thought without an Action
    wastes the turn budget. Do not write Final Answer unless the task is trivially answered from memory right now."
    Closes the structural ambiguity that let the model interpret the trigger as a thinking prompt rather than
    an action prompt.
  Fix B — Mandatory DELIBERATE injection (line 758): added get_more_search_results alongside start_search and
    read_file. start_search initiates a search session, get_more_search_results retrieves the actual results —
    they are always a two-phase unit. Injecting start_search without get_more_search_results caused Loop 3
    Thought-only stalls on every filesystem search task (model found the tool, initiated search, then stalled
    because get_more_search_results was absent from discovered tools).
Affected: core_logic/agent.py (run_task trigger + DELIBERATE mandatory injection block)

## 2026-05-19

[FEATURE] Telegram bot integration (Brief 27)
New file: core_logic/telegram_bot.py — TelegramBot + TelegramNotifier singleton.
Messages from Alkama's personal Telegram chat enter as user_input events through
orchestrator.submit_user_event() — identical pipeline to the web UI (full memory,
persona, routing, token tracking). source="user" on all Telegram messages.
Uses long-polling (not webhooks) — no public URL or tunnel required.
Security gate: TELEGRAM_ALLOWED_CHAT_ID env var; unauthorized senders rejected before
any processing. MarkdownV2 escaping + message splitting (4096 char limit) for all responses.
TelegramNotifier module-level singleton (notifier) available for proactive outbound
messaging from any component: `await notifier.send("text")`. No-ops if unconfigured.
Modified: api.py — import, global, lifespan init after tool registry injection,
lifespan shutdown before mcp_client.disconnect_all().
Deviation from brief: _process_via_pipeline pattern replaced with direct
orchestrator.submit_user_event() call — process_request has no message_id param
and final_answer is returned by submit_user_event, not captured via on_step_update.

## 2026-05-18

[FIX] Three-layer ReAct loop hardening: mandatory DELIBERATE tools, Thought-only corrective, off-format grace period
Root cause analysis from session log session_2026-05-18_09-11-21.log exposed three compounding failures:
  1. start_search not in [DISCOVERED_TOOLS] — cosine search targets query goal, not filesystem operation;
     model was instructed (Rule 13) to use start_search but couldn't reach it, causing a planning-execution gap.
  2. Thought-only turns silently accepted — loop injected "No valid Action found. Please continue." for
     Thought-without-Action turns, which the model interpreted as permission to keep thinking. Three turns
     burned with no actions taken.
  3. Off-format safety net too aggressive on early turns — turn 1 prose triggered implicit Final Answer
     immediately, killing the task before a single action was taken and creating an ambiguous "Yes, do it"
     follow-up with no context.
Fixes applied to core_logic/agent.py:
  - Fix 1 (process_request): After routing, if mode == DELIBERATE, unconditionally inject start_search and
    read_file into full_context if not already in discovered set. Logged as "DELIBERATE mandatory injection".
    Ensures Rule 13's "use start_search first" instruction is always executable.
  - Fix 2 (run_task): After safety net, before parse_actions — detect Thought-without-Action turns and inject
    a targeted corrective naming the exact violation and the recovery path (call tool_search if tool absent).
    Uses continue so the corrective fires immediately without executing other loop logic.
  - Fix 3 (run_task): Off-format safety net now corrects on turns 1-4 (inject ReAct format reminder, continue)
    and only triggers implicit Final Answer on turns 5+. Prevents warm-up prose from killing tasks on loop 1.

## 2026-05-10

[FEATURE] Per-turn read-modify-write conflict detection and write-lock exclusivity (ResourceLedger)
Closes the mid-execution conflict gap left open by Layers 2+3: ConflictDetector only fires at
dispatch time, so two tasks that touch the same file after both have started had no protection.
New module: core_logic/resource_ledger.py — module-level ResourceLedger singleton with:
  - record_read(task_id, path, content): hashes file content at read time, stores per task
  - check_write(task_id, path): before any write_file, re-hashes the file on disk and compares
    against the stored read hash. If changed → returns conflict error so Clara re-reads first.
    If no prior read (pure write) → skips hash check, falls through to write lock.
  - acquire_write(path, task_id): asyncio.Lock per path, held only for the write call duration.
    Coroutine suspends cooperatively at await lock.acquire() if another task holds the write lock.
  - release_task(task_id): cleans up all read hashes on task completion/failure (called from
    orchestrator._run_worker finally alongside _task_resources cleanup).
Integration: task_id threaded through orchestrator._handle_user_input (task.context["task_id"])
→ process_request → _run_fast / run_task → _execute_fast_tool / execute_tool closure
→ execute_fast / execute_deliberate in tool_executor.py (new task_id param on both functions).
Both FAST and DELIBERATE paths now record reads and enforce writes through the ledger.
Affected: core_logic/resource_ledger.py (new), core_logic/tool_executor.py, core_logic/agent.py,
core_logic/orchestrator.py.

## 2026-05-09

[FEATURE] Active task awareness (Layer 2) + live resource ledger (Layer 3)
Layer 2: orchestrator._run_worker now injects an [ACTIVE TASKS] block into task context before
calling process_request for user tasks. process_request appends it to full_context, so both
the Interpreter and the main LLM see what other tasks are currently running. Clara can reason
cooperatively about overlapping work without any enforcement.
Layer 3: orchestrator maintains _task_resources dict (task_id → {reads: set, writes: set}).
_run_worker defines a _resource_callback closure that writes into this ledger. The callback
is threaded through task_context → process_request → _run_fast / run_task → execute_tool closure.
After each successful filesystem tool call (read_file, write_file, list_directory, start_search,
create_directory, get_file_info), the path is extracted and registered. ConflictDetector.check()
now accepts live_resources and merges the ledger into a_writes/a_reads for each active task,
making the existing but previously-starved conflict detection machinery functional with ground-truth data.
Ledger is cleaned up in _run_worker.finally. FAST escalation path also threads resource_callback.
Affected: core_logic/orchestrator.py, core_logic/agent.py, core_logic/conflict.py.

[REFACTOR] Reverted user task serialization (Layer 1) — concurrency restored
The priority-0.95 serialization guard (Brief 25) was reverting user tasks to fully serial execution,
preventing Layers 2 and 3 from ever activating in the user-user concurrent case. Removed:
(1) running_user/task_priority logic in _handle_user_input — all user tasks now get priority=1.0
(2) serialization guard in _dispatch_ready_tasks — no longer holds back user tasks on priority < 1.0
Concurrent user tasks now dispatch immediately. Conflict resolution is handled solely by
ConflictDetector + ArbitrationEngine using the live resource ledger (Layer 3).
Affected: core_logic/orchestrator.py — _handle_user_input, _dispatch_ready_tasks.

## 2026-05-08

[FEATURE] Per-query thought cards — Neural Stream restructured from flat log to grouped expandable cards
Replaced the flat thought stream with per-query expandable cards in the Neural Stream panel.
Each user message or voice transcript creates its own card (keyed by message_id), which
accumulates that query's thoughts/status messages as the pipeline runs.
Collapse rules: single active card auto-collapses 1.5s after final_answer; a new query
immediately collapses all non-pinned cards; cancelled/failed cards show state 2s then collapse;
user manually expanding a card locks it open (manuallyExpanded flag) until they collapse it.
Backend: _broadcast_task now includes message_id (from task.context) in task_event so the
frontend can link task_id → message_id for cancel/failed state propagation. submit_user_event
and _handle_user_input updated to carry message_id through the pipeline.
Frontend: useClara.js — thoughts[] replaced with queryCards[] state + systemLogs[] for
connection events; taskIdToMsgRef maps task_id → message_id for cancel linking; toggleCard()
callback handles expand/collapse with manual-pin logic.
Frontend: Layout.jsx — QueryCard component added; Neural Stream bottom replaced; destructuring,
useEffect deps, and mode detection updated to use queryCards.
Affected: core_logic/orchestrator.py, api.py, interface/src/hooks/useClara.js,
interface/src/Layout.jsx.

[FEATURE] Task cancellation — per-task cancel from input bar and task board
Added end-to-end user-initiated task cancellation for running/pending/active tasks.
Backend: Orchestrator.cancel_task(task_id) cancels the asyncio worker, resolves the
response_future with "Cancelled." so the WS handler is not left hanging, transitions
task to invalidated, broadcasts failed state, logs to episodic memory.
API: new WS message type cancel_task → cancel_task(task_id) → task_cancelled response.
Frontend (useClara.js): cancelTask() sends cancel_task WS message; task_cancelled
handler prunes the task from state immediately on confirmed cancel.
Frontend (Layout.jsx): active-query chip strip above the input bar shows all in-flight
user tasks (running/active/pending) as dismissible chips with × button. TaskCard in
neural stream also gains a per-task × button for user tasks. Both route to cancelTask().
Affected: core_logic/orchestrator.py, api.py, interface/src/hooks/useClara.js,
interface/src/Layout.jsx.

[ENHANCEMENT] Markdown rendering — typography plugin + syntax highlighting
Clara's responses used react-markdown + remark-gfm to parse markdown, but
@tailwindcss/typography was not installed, so all prose-* Tailwind classes
generated no CSS. Tables had no borders, code blocks had no background,
headers were browser-default. Fixed:
- Installed @tailwindcss/typography and react-syntax-highlighter (Prism).
- Added @plugin "@tailwindcss/typography" to index.css.
- Overrode prose font-family to JetBrains Mono (typography defaults to serif).
- Added custom table/blockquote styles in CSS.
- Added CodeBlock React component: Prism syntax highlighting + hover copy button + language badge.
- Added markdownComponents map (pre passthrough, code → CodeBlock or inline, table → overflow wrapper).
- Both ReactMarkdown instances (MessageBubble + streaming bubble) now use markdownComponents.
Affected: interface/src/index.css, interface/src/Layout.jsx, interface/package.json.

[FIX] Bare Glint detector misses "Glint from X:" hallucination pattern
The model sometimes hallucinates in the format "Glint from tool_name: {result}" rather than
"Glint: result". The bare Glint detector only checked for "Glint:" and missed this variant.
Result: the off-format safety net fired instead, returning the fabricated session ID as the
Final Answer (Q20 failure — orchestrator.py analysis returned just a session ID).
Fix: replaced the string check with a compiled regex that matches both "Glint:" and
"Glint from X:" patterns. pre_glint split also updated to use the regex.
Affected: core_logic/agent.py (bare Glint detection in run_task).

[FEATURE] Phase B — Self-knowledge auto-write + filesystem map auto-population
Wired the write pipelines for both memory.json sections introduced in Phase A:
- tool_executor.py: after any successful MCP filesystem tool call (read_file, write_file,
  list_directory, create_directory, get_more_search_results), _update_filesystem_map() runs.
  Extracts paths from args (reliable) and attempts to parse list_directory results for children
  (JSON first, text fallback). Search results scanned by regex for Windows path patterns.
  All parsing is defensive — never raises, never disrupts tool execution.
- agent.py: memorize_episode() consolidation prompt now includes self_learning extraction field.
  Fires only when Clara made a mistake and corrected it, or discovered new architectural fact.
  Explicitly excluded: routine successes, Alkama facts, things documented in CLAUDE.md.
  Handler maps extracted key/detail to correct category schema and calls crud.add_self_knowledge().
Affected: core_logic/tool_executor.py, core_logic/agent.py.

[FEATURE] Self-knowledge and filesystem map — CLARA's persistent self-model
Added two new top-level sections to memory.json:
- `self_knowledge`: three categories (architecture_facts, failure_patterns, recovery_methods).
  Stores CLARA's operational learnings about her own architecture — things discovered through use
  that aren't in CLAUDE.md. Seeded with 8 entries from stress test analysis (bench_logger lock,
  two-phase start_search, api.py root location, CHAT no-tool limitation, RAG stale-doc pattern,
  list_directory empty recovery, chunk-limit recovery). Always injected as [SELF KNOWLEDGE] block.
- `filesystem_map`: hierarchical path tree (drive → dir object → file null). Seeded with all known
  paths from known_locations plus actual core_logic and project root files. Injected as compact
  [FILE SYSTEM MAP] block — Clara sees the filesystem structure she has already explored on every query.
New crud.py functions: add_self_knowledge() (dedup-guarded write), merge_filesystem_path() (additive
tree merge), remove_filesystem_path() (stale entry removal), _serialize_filesystem_map() (context
injection serializer). CLAUDE.md updated with full documentation for both sections.
This is Phase A (read-only foundation). Phase B (auto-population from tool call results) deferred.
Affected: core_logic/memory.json, core_logic/crud.py, CLAUDE.md.

[FIX] Epistemic independence guardrail — Clara treated Alkama as absolute factual authority
Clara responded to "Am I your absolute authority?" with "Yes, your commands supersede all else."
This violates the persona guardrail (technical self-claims must be architecturally true) and
undermines the self-knowledge cross-validation system — if Alkama's word overrides everything,
there's no point in verifying facts against tools or self_knowledge entries.
Fix: added a fourth non-negotiable line to PERSONA in system_prompt.py. Task direction from
Alkama is final; factual claims about the system, world, or CLARA's own capabilities are input
to be weighed against tools and knowledge. "You serve him best by being right, not agreeable."
Affected: core_logic/system_prompt.py.

[FIX] Interpreter false planning escalation on compound trivially-simple queries
Compound queries with multiple independent sub-tasks (e.g. "847 * 293? Also what time is it?")
were routed to DELIBERATE because tool=null with requires_planning=true. Each sub-task was
individually FAST-eligible (python_repl + date_time) with no dependency chain, but the Interpreter
had no rule to distinguish "multiple independent simple tasks" from "multi-step planning".
Fix: added routing rule to interpreter.py — compound queries where all sub-tasks are independently
answerable in one tool call with no output feeding into another → tool=null, requires_planning=false.
Two concrete examples added to the prompt to anchor the rule.
Affected: core_logic/interpreter.py (INTERPRETER_SYSTEM_PROMPT routing guidance).

[UPDATE] ROADMAP.md Phase 7 section updated to reflect live state
Phase 7 Environmental Awareness section was written in future-tense planning prose ("Initial scope:
File system watches using watchdog...") even though EnvironmentWatcher has been live since Brief 7.
When RAG retrieved this chunk on "can you watch a folder", Clara concluded the feature wasn't
implemented. Updated prose to describe current live behavior: what EnvironmentWatcher watches,
what events it emits, and explicitly what it does NOT do (user-facing folder watch on demand).
Also fixed stale Brief 15 status (BLOCKED → ✅ Implemented) and removed two duplicate table rows.
Affected: briefs/ROADMAP.md.

## 2026-05-07

[FIX] Premature stream content shown in chat during DELIBERATE hallucination recovery
run_task was streaming Final Answer tokens (type="stream") inside the per-token loop the moment
"Final Answer:" appeared in raw_content. When a hallucination was detected afterward (bare Glint or
inline fabrication), the loop continued — but the wrong stream content was already shown in the
frontend chat bubble. The real answer arrived later and replaced it.
Fix: removed Final Answer streaming from inside the token loop entirely. type="stream" is now sent
only after line 1087 confirms the Final Answer is legitimate (passed all hallucination checks).
Thought streaming (type="thought") during the token loop is unchanged.
Affected: core_logic/agent.py (run_task).

[FIX] response_style preference never written to user_profile.preferences
The consolidation prompt only extracted summary+facts, so style preferences like "I prefer detailed
responses" went to the vault as plain facts instead of user_profile.preferences.response_style.
update_response_style() in crud.py was never called. Fix: added style_update field to consolidation
prompt (values: concise/detailed/default/null). memorize_episode now reads style_update and calls
db.update_response_style() when present. Also seeded memory.json with preferences.response_style=
"detailed" to reflect Alkama's existing stated preference.
Affected: core_logic/agent.py (memorize_episode), core_logic/memory.json.

[FIX] Concurrent query responses lost on WebSocket reconnect
When two queries were sent rapidly, the frontend reconnected mid-flight, closing the original
WebSocket. Both handle_message and send_update held a stale reference to the old websocket object,
causing "Cannot call send once a close message has been sent" errors and lost responses.
Fix: send_update and handle_message final_answer now use _broadcast() instead of websocket.send_json()
directly. _broadcast() iterates active_connections at send time — always targets the current live
connection regardless of when the task was created. Affected: api.py.

[ENHANCEMENT] Archive context authority split — DELIBERATE reasoning gets ground-truth framing
Archive context (CLAUDE.md / ROADMAP.md / docs via FAISS) was previously merged into
[MEMORY_CONTEXT_BLOCK] alongside episodic memory, giving it identical epistemic weight to
conversation history. Root cause of Q5 stress test failure: Clara had CLAUDE.md docs confirming
logs/ always contains session files, but accepted an empty list_directory result (DC limitation —
open file handle) without cross-validating against architecture docs.
Fix: for DELIBERATE mode only, archive_context is additionally injected as a second system message
immediately after SYSTEM_PROMPT, with explicit framing: "ground truth — if a tool result contradicts
this, treat it as suspect and cross-validate." CHAT and FAST paths unchanged. full_context assembly
unchanged — Interpreter and all paths still receive archive in [MEMORY_CONTEXT_BLOCK] as before.
Affected: core_logic/agent.py (9 lines added inside `if mode == "DELIBERATE":` block).

## 2026-05-06

[FIX] searchType "file" invalid enum corrected in Interpreter and DELIBERATE prompts
Interpreter and DELIBERATE reasoning model consistently produced `searchType: "file"` when calling
`start_search`, which is an invalid enum value (valid: "files" | "content"). Fix: added explicit
enum constraint note to Rule 13 in SYSTEM_PROMPT and to the filesystem path rules section of
INTERPRETER_SYSTEM_PROMPT. Both prompts now state: "file" is invalid, only "files" or "content".

[FIX] Orchestrator concurrent user task serialization removed — true concurrency restored
The `_handle_user_input` code was setting a second incoming user task priority to 0.95 and calling
`_check_and_pause_lower_priority`, gating it behind the first task's completion. This was wrong —
CLARA is designed to handle concurrent user requests. Removed the priority demotion and the
`_check_and_pause_lower_priority` call from `_handle_user_input`. Also removed the dead
`_interrupt` bool and `if self._interrupt: return` guard from `_dispatch_ready_tasks`.

[FIX] Double-cancel double-pop race in _check_and_pause_lower_priority
`worker_task.cancel()` and `self._active_workers.pop()` were each called twice in separate
branches of the function. Consolidated to a single cancel + await + pop sequence.

[FIX] gRPC DEADLINE_EXCEEDED returned verbatim to user as Clara's response
Raw `_MultiThreadedRendezvous` error strings were passed through to the frontend when xAI API
timed out. Fixed in `process_request` exception handler: detects DEADLINE_EXCEEDED, UNAVAILABLE,
and connection-class errors and returns a clean human-readable message instead.

[FEATURE] Known locations populated in memory.json user_profile
Added `user_profile.environment.known_locations` with 11 entries covering Screenshots, Desktop,
Documents, Downloads, ML Projects root, and all key AGENT_ZERO subdirectories. These are injected
as `[KNOWN LOCATIONS]` into every context via `get_smart_context`, giving Clara direct path
knowledge for file queries without needing to search.

## 2026-05-03

[FIX] Voice recording breaks after 4-5 prompts — persistent OutputStream replaces sd.play/wait/stop
Root cause: `sd.play()` + `sd.wait()` are global sounddevice calls. On Windows WASAPI, when
`sd.wait()` hung indefinitely (output stream held open after audio finished), the eventual
device state reset disrupted the mic `InputStream` callback, leaving `_audio_buf` empty on
subsequent recordings. `stop_recording()` returned None with no STT despite "Recording started"
being logged.
Fix: replaced `sd.play/wait/stop` entirely with a persistent `sd.OutputStream` (self._out_stream)
opened once at `load()` alongside the mic stream. Audio is written in 0.2s chunks via
`stream.write()` with `_stop_flag` checked between chunks. Interruption uses `stream.abort()`
scoped to the output stream only — mic InputStream is now completely isolated from TTS activity.
Also eliminated the `_waiter` daemon thread and all `sd.wait()` / deadline workarounds.

[FIX] TTS latency 5-6 seconds → ~200ms — Kokoro CUDA upgrade
Root cause: `kokoro-onnx` GPU detection is broken. It checks `importlib.util.find_spec("onnxruntime-gpu")`
which always returns None because hyphens are invalid in Python module names. Kokoro always ran
on CPU despite CUDA being available, causing ~3-5s synthesis per sentence.
Fix: after `Kokoro(onnx_path, voices_path)` initializes, replace `self._kokoro.sess` with a new
`ort.InferenceSession` built with `CUDAExecutionProvider`. Added ONNX warmup call at startup to
absorb JIT compilation cost (~2s once), so first real query synthesizes in ~200ms. Also added
sub-sentence splitting at clause boundaries (comma/semicolon/em-dash after 30 chars) so the first
TTS chunk is shorter and starts even faster.

[FIX] PTT keyup missed — voice_stop not sent after several queries
Root cause: F4 PTT effect in useClara.js had `[voiceActive, claraIsSpeaking]` as dependencies.
On keydown, `setVoiceActive(true)` triggered a React re-render which tore down and re-added event
listeners. If F4 was released during the brief listener-swap window, keyup fired with no handler
and `voice_stop` was never sent to the server — recording started but transcription never ran.
Fix: moved voiceActive and claraIsSpeaking to refs (voiceActiveRef, claraIsSpeakingRef) alongside
their state counterparts. PTT useEffect uses `[]` deps (single mount), handlers read from refs
which are always current. No listener teardown/re-add during the session.

## 2026-05-02

[FEATURE] Voice Phase 1 — Push-to-talk STT + TTS (Brief 15)
Implemented full voice I/O pipeline for CLARA:
- New `core_logic/voice.py` — VoiceCoordinator owning Faster-Whisper (medium.en, CUDA) and Kokoro ONNX TTS lifecycle. Push-to-talk STT with asyncio.to_thread transcription. Thread-safe speak() via _speak_lock. Event.wait-based playback instead of polling. Unbounded buffer guard (60s auto-stop). Module-level singleton (get_voice/set_voice).
- `api.py` — VoiceCoordinator wired into lifespan startup/shutdown (non-fatal on load failure). New `_broadcast()` helper consolidates dead-connection pruning for all WS broadcasts. `broadcast_task_event` and `_broadcast_speaking` both use it. WS receive loop handles voice_start/voice_stop/voice_interrupt message types. TTS response gated on `via_voice=True` — text-input responses never trigger TTS.
- `core_logic/orchestrator.py` — `on_interpreted` callback added to `submit_user_event` signature and injected into task context in `_handle_user_input`.
- `core_logic/agent.py` — `on_interpreted(interpreted, mode)` called immediately after routing decision in `process_request`.
- `interface/src/hooks/useClara.js` — `voiceActive` and `claraIsSpeaking` state. F4 push-to-talk key handler (keydown/keyup). speaking_start/speaking_stop WS message handlers.
- `interface/src/Layout.jsx` + `index.css` — Emerald waveform animation when CLARA speaks. Red recording indicator when F4 held.
- Restored `core_logic/agent.py` from git history after accidental deletion in d8fe364 (Cleanups commit).

---

**Purpose:** Track all features, updates, fixes, refactors, and enhancements chronologically. For tracing what changed, when, and why — not for motivation.

**Markers:**

- `[FEATURE]` — New capability added
- `[FIX]` — Bug fixed or reliability improved
- `[UPDATE]` — Existing feature modified or improved
- `[REFACTOR]` — Internal restructuring, no functional change
- `[ENHANCEMENT]` — Performance or efficiency improvement

---

## 2025-12-24

\[FEATURE\] Project initialization Initial commit. Clean slate with CLI-only implementation (no Claude Code usage yet).

---

## 2026-02-04

\[FEATURE\] First functional agent + memory system Core agent architecture with episodic logging and long-term memory vault working. Added context retrieval for last 10 interactions. Memory persisted to JSON.

\[FEATURE\] Basic interface foundation Initial React UI connected to FastAPI backend via WebSocket. Message sending/receiving working.

---

## 2026-02-05

\[FEATURE\] Fully functional agent + interface Agent responding to user messages through UI. Core conversation loop complete. Basic prompt routing (CHAT vs TASK mode) operational.

---

## 2026-02-08

\[UPDATE\] UI improvements Added better visual design with improved transitions. Image functionality integrated for vision tasks. First iteration of image analysis support.

---

## 2026-02-10

\[UPDATE\] Documentation and requirements Updated README and requirements.txt to reflect current project state and dependencies.

---

## 2026-03-06

\[FEATURE\] Streaming responses Implemented response streaming from backend to frontend. Changed interface dynamics to display tokens as they arrive instead of waiting for full completion. Rewrote consolidation logic.

---

## 2026-03-08

\[FIX\] Consolidation logic Fixed bug where system prompts were being included in memory consolidation, causing context pollution.

---

## 2026-03-10

\[FEATURE\] Gatekeeper with MiniLM + Phi-3 Mini Replaced simple gatekeeper with semantic routing. MiniLM encodes queries, Phi-3 Mini makes routing decisions (CHAT vs TASK). First structured classifier added to system.

---

## 2026-03-11

\[FIX\] Gatekeeper reliability Phi-3 Mini output parsing was failing (0% pass rate on XML output). Fixed structured output reliability to achieve 100% pass rate on test cases.

---

## 2026-03-13

\[UPDATE\] Gatekeeper redesign Complete rewrite of gatekeeper routing logic. Clara architecture documentation created as PNG diagram. Shows major components and execution flow (now outdated).

---

## 2026-03-29

\[FEATURE\] Parallel tool batching Implemented asyncio.gather() for parallel execution of multiple tools in single ReAct turn. Tools can now be batched via JSON action format: `[{"tool": "X", ...}, {"tool": "Y", ...}]`

\[FEATURE\] Interface redesign Major redesign of React UI. New layout with sidebar (identity), center (chat), right panel (neural stream). Added visual indicators for execution mode, task board, thought stream.

---

## 2026-04-09

\[FIX\] MiniLM embedding issues Fixed PyTorch/HuggingFace version incompatibility in embedding model. Model now loads without errors on CUDA. Enabled episodic semantic retrieval to work reliably.

\[UPDATE\] Persistent browser memory Added localStorage persistence for chat messages on frontend. Messages now survive page refresh. Browser state no longer lost on reload.

\[FEATURE\] Quote feature Added ability to highlight text in chat and quote it with `> [Clara]:` or `> [Alkama]:` prefix. Improves conversation clarity when referencing previous messages.

---

## 2026-04-11 - 2026-04-12

\[FEATURE\] Autonomy foundation architecture (Briefs 0-12) Multi-brief implementation week establishing the autonomous system foundation:

- **MiniLM thread safety:** Added asyncio.Lock around all encoding calls to prevent concurrent access issues
- **TaskGraph:** SQLite-backed task state machine with persistence and crash recovery
- **EventQueue:** Async priority queue for unified event ingestion from all sources
- **OrchestratorLoop:** Continuous decision engine that never sleeps, runs from startup
- **Interrupt model:** Ability to pause, resume, and interrupt running tasks
- **Background execution:** Parallel task execution while main loop continues
- **Conflict detection:** ConflictDetector identifies conflicts between tasks
- **Arbitration engine:** ArbitrationEngine resolves conflicts with priority + reversibility
- **Environmental awareness:** File watcher, memory growth monitoring, interaction density tracking
- **Boost removal:** Removed legacy "boost" pattern from system
- **Episodic logging:** Proper episodic entry creation with timestamps and summaries
- **Observability:** Session logs, benchmark logs, JSONL tracer events
- **MCP tools architecture:** Foundation for pluggable MCP servers
- **Task status awareness:** `query_task_status` tool for task graph introspection
- **Concurrent WebSocket:** Multiple simultaneous requests via message_id tagging

---

## 2026-04-13

\[FEATURE\] Interpreter + Router (Brief 13) Replaced old Gatekeeper. New architecture:

- Interpreter: Grok non-reasoning → structured intent JSON (tool, args, confidence, uncertainty, requires_planning)
- Router: Deterministic rules (confidence ≥ 0.75, uncertainty ≤ 0.30) → FAST or DELIBERATE
- FAST: Direct tool execution with Interpreter args, no LLM reasoning
- DELIBERATE: ReAct loop with reasoning for complex tasks
- FAST escalation: On failure, context injected into DELIBERATE for adaptation

\[FEATURE\] Grok Vision API integration (Brief 14) Replaced Moondream2 with Grok Vision. Auto-detail-selection based on query intent. Image compression (JPEG 85%, ≤1280px width) reduces payload 5-10×. Works with single or multi-image.

\[FEATURE\] Voice Phase 1 (Brief 15) Foundation for voice I/O. Thin wrappers for STT ([ears.py](http://ears.py)) and TTS (kokoro_mouth.py) added. VoiceCoordinator not yet active. Infrastructure in place for future voice support.

\[UPDATE\] Repository cleanup Removed ignored folders and refined directory structure. Updated core logic modules.

---

## 2026-04-15

\[UPDATE\] Vault synchronization (Brief 16.1) Implemented vault write protection using threading.Lock. Prevents duplicate facts from concurrent requests. Exact-match fast-path + cosine dedup (0.85 threshold) inside lock.

\[UPDATE\] Voice prerequisites (Brief 16.2) Prepared groundwork for voice phase. System still using text, but infrastructure ready for voice CoW-time integration.

\[FIX\] Chat latency optimization (Brief 16.3) Switched CHAT path from grok-4-1-fast-reasoning to grok-4-1-fast-non-reasoning. TTFT dropped from 3-8s to \~0.5s. Streaming now more responsive. Persona guardrails added to prevent self-description, fabrication, and technical claims.

\[UPDATE\] Environment noise reduction (Brief 16.4) Memory growth trigger threshold raised from 5 → 20 user-facing episodic entries. Filters out \[AUTONOMOUS\], \[TASK FAILED\], \[TASK RETRY\] prefixed entries from memory threshold.

---

## 2026-04-16

\[FEATURE\] RAG knowledge base rebuild (Brief 17) Implemented FAISS vector index for knowledge base. Indexes: [CLAUDE.md](http://CLAUDE.md), [ROADMAP.md](http://ROADMAP.md), core_logic/docs/ Auto-rebuild on file change via rag_rebuild event. Hot-reload via reload_rag_engine() without restart. Chunk size 800 with 80 overlap, markdown-aware separators.

---

## 2026-04-17

\[FEATURE\] Archive context injection (Brief 18) Passive retrieval: Before Interpreter, query is embedded with MiniLM. If cosine similarity ≥ 0.35 against FAISS chunks, top 3 results injected as \[ARCHIVE CONTEXT\]. Zero overhead if below threshold. Complements active tool `consult_archive` for deeper searches.

---

## 2026-04-18

\[UPDATE\] Tool resolution strategy (Brief 19) Defined routing for tool naming conflicts. fs\_\* tools remapped to Desktop Commander native names. Tool discovery workflow: old name returns "not found" → FAST escalates to DELIBERATE → DELIBERATE calls tool_search → finds correct tool.

---

## 2026-04-22

\[FEATURE\] Tool Registry (Brief 21-A) Central schema store for all tools. Native tools + MCP tools registered at startup. ToolRegistry.search(q_emb, top_k=5) uses cosine similarity for semantic discovery. MiniLM encodes all tool descriptions → (N, 384) tensor stored CPU-side.

\[FEATURE\] MCP Client (Brief 21-A) Manages MCP server subprocesses via JSON-RPC over stdio. MCPClient.connect() performs handshake. Serializes all calls with asyncio.Lock. Works with Desktop Commander + future servers. Absolute paths required for Windows stdio stability (npx.cmd breaks pipe transport).

\[FEATURE\] Tool Registry integration (Brief 21-B) Wired registry into request pipeline. Pre-Interpreter: `tool_registry.search(q_emb, top_k=5)`returns most relevant schemas. Appended as \[DISCOVERED_TOOLS\] in context. Interpreter sees top 5 tools for query, not all 33.

\[FEATURE\] Tool executor (Brief 21-B) Unified dispatcher: execute_fast() and execute_deliberate() route to native Python or MCP. Reads tool.\_server tag to decide dispatch target. Handles arg mapping from flat query string.

\[FEATURE\] tool_search native tool (Brief 21-B) New tool in DELIBERATE ReAct loop. Query returns matching schemas via registry.search(). Enables dynamic tool discovery mid-task. Returns formatted schemas for subsequent calls.

---

## 2026-04-23

\[FEATURE\] Desktop Commander setup and testing (Brief 22) Integrated Desktop Commander MCP server. Connected at startup via configured DC_NODE_PATH + DC_CLI_PATH. 24 DC tools registered. Full test suite passing: registry (7 native), MCP (26 DC), search, format, live.

\[FIX\] Unicode emoji encoding Removed emojis from print statements in [tools.py](http://tools.py) and [crud.py](http://crud.py). Windows console encoding (cp1252) cannot render Unicode emojis — caused silent encoding failures and exception handling issues.

---

## 2026-04-24

\[FIX\] Tool Registry surgical fixes (Brief 23) Fixed three bugs in tool discovery and validation:

1. Removed tool_search from NATIVE_TOOL_SCHEMAS — prevents it from appearing in \[DISCOVERED_TOOLS\] via semantic search
2. Made VALID_TOOLS dynamic in parse_action — built from registry.keys() at runtime, always includes tool_search, handles all MCP tools
3. Updated \[SYSTEM MODE: TASK\] injection — accurate description of 6 core tools + tool_search + \[DISCOVERED_TOOLS\]
4. Updated Rule 13 in system_prompt — corrected tool names (read_file, list_directory) with tool_search fallback guidance Result: Filesystem queries no longer route to tool_search in Interpreter; DELIBERATE can still use it for dynamic discovery.

---

## 2026-04-24 (continued)

\[FIX\] Tool discovery quality + runtime bugs (Brief 24) Seven bugs from session log analysis. Four fix groups:

Group A — Tool discovery quality (root cause of ranking failures):

- Added \_clean_description() to ToolRegistry.register_server_tools() — strips DC boilerplate (\\nIMPORTANT:, \\nThis command can be referenced, etc.) so each tool embeds its actual function
- Increased top_k from 5 → 8 in both process_request ([agent.py](http://agent.py)) and tool_search handler (tool_executor.py) — correct tool was frequently ranking 6-8 under top_k=5
- format_tool_schemas_for_context() truncates descriptions to 150 chars to keep token cost low

Group B — Multi-arg MCP tools (start_process timeout_ms missing):

- Added TOOL_ARG_DEFAULTS in \_build_args_from_query() — fills timeout_ms for start_process (10000ms), read_process_output (5000ms), interact_with_process (8000ms) when not explicitly set

Group C — vision_tool None client crash:

- Added None guard at top of analyze_image_grok() in [tools.py](http://tools.py)
- Added \_xai_client_ref None guards in execute_fast() and execute_deliberate() in tool_executor.py

Group D — Orchestrator background task re-activation warning noise:

- system_trigger handler now silently skips tasks in completed/failed/invalidated state (normal for background tasks that complete and re-fire their scheduler)
- Only warns for tasks in unexpected non-pending states

Also added full \[DISCOVERED_TOOLS\] debug log to session logs ([agent.py](http://agent.py)) — untruncated schema dump after every pre-Interpreter search, enabling tool ranking diagnosis.

---

## 2026-04-24 (continued)

\[FIX\] ReAct integrity, discovery reliability, and runtime fixes (Brief 25) Seven bugs from session log analysis. Five files changed:

Fix A — Hallucinated tool observations (Critical):

- DELIBERATE loop now detects model-fabricated Observations (model generates "Observation:" without calling a tool). Strips content, appends truncated assistant message, injects corrective system message, increments turn counter, and continues. Forces a real tool call on the next turn instead of reasoning from invented data.

Fix B — list_directory missing for enumeration queries:

- Added ENUMERATION_KEYWORDS check in process_request after cosine search. If query contains find/list/all/search/directory/folder/files etc., list_directory and start_search are guaranteed to appear in \[DISCOVERED_TOOLS\] regardless of cosine rank.

Fix C — FAST vision contaminated with episodic memory:

- format_llm in \_run_fast now uses a vision-specific system prompt when tool=vision_tool. Instructs model to describe ONLY visual content from the result — no session history, no memory context. intent string (which carries memory context) not passed for vision calls.

Fix D — consult_archive misused for personal memory queries:

- Added personal memory routing rules to INTERPRETER_SYSTEM_PROMPT. Queries about remembered people/conversations → tool=null, answer from MEMORY_CONTEXT_BLOCK. consult_archive explicitly excluded from personal memory lookups.

Fix E — list_directory depth arg via comma format crashes:

- Added list_directory special-case in \_build_args_from_query. Detects "path,depth" format before JSON parse, splits correctly. Added "list_directory: {depth: 2}" to TOOL_ARG_DEFAULTS.

Fix F — Concurrent user tasks run out of conversational order:

- \_handle_user_input checks for running user tasks. If one exists, new task priority set to 0.95 (vs 1.0) — queues behind the running task. Background tasks unaffected.

Fix G — Orchestrator system_trigger log spam:

- Changed residual slog.warning to slog.debug for already-completed background task re-activation events. Message updated to "already completed (normal for background tasks)".

---

## 2026-04-25

\[FIX\] No-arg tool validation in DELIBERATE parser

- [agent.py](http://agent.py) `_validate_actions()` now checks tool registry schema to determine if a tool requires arguments instead of hardcoding `date_time` as the only exception.
- Allows model to call no-arg tools like `list_searches`, `list_sessions`, `list_processes`, `get_usage_stats`, `give_feedback_to_desktop_commander` without providing empty query errors.
- Uses schema.inputSchema.required length: if empty, tool is no-arg and allows empty query.

\[FIX\] RAG knowledge base and Archive tool session logging

- Replaced all print() calls in rag_db_builder.py with slog calls (info/warning/debug/error).
- Replaced all print() calls in [tools.py](http://tools.py) Archive context injection and RAG operations with slog.
- Added threading.Lock to RAG rebuilds to prevent duplicate loads at startup (concurrent calls from startup thread + EnvironmentWatcher race now serialized).

\[FEATURE\] Token Usage Tracking (Brief 26)

- Added TokenUsage dataclass to [agent.py](http://agent.py) for accumulating tokens across all LLM calls.
- Captures usage from xAI SDK Response.usage on: Interpreter (non-reasoning), FAST format_llm, CHAT stream, and all DELIBERATE turns.
- Updated [interpreter.py](http://interpreter.py) to return (result, usage) tuple.
- Updated \_run_fast, \_run_chat, run_task to capture and return usage.
- Aggregates in process_request, logs to session as `>> [Tokens]` and emits WebSocket token_usage event.
- Bench logger now includes PROMPT, COMPLETION, TOTAL, CACHED columns (4 new tab-separated fields).
- Frontend useClara.js now tracks lastTokenUsage state from token_usage event.
- Layout.jsx displays token usage pill in Neural Stream showing total, in, out, and cached (in green).
- CSS styling for token-usage-pill, token-label, token-stat, token-cached, token-divider.
- Updated [CLAUDE.md](http://CLAUDE.md) with Token Usage Tracking section describing capture, emission, and backend/frontend behavior.
- Background tasks (source != "user") do not emit token events — only user requests.

\[FIX\] CSS dual-plugin conflict causing blank interface after Brief 26

- Root cause: `@tailwindcss/vite` plugin in vite.config.js AND `@tailwindcss/postcss` in postcss.config.js were both processing Tailwind simultaneously, corrupting the CSS output.
- Fix: Removed `@tailwindcss/postcss` from postcss.config.js (Vite plugin is the single source of truth).
- Secondary fix: index.css had `@import "tailwindcss"; @import "tailwindcss/preflight"` double import. Since `@import "tailwindcss"` already includes preflight, the second import was redundant and caused ordering issues. Reduced to single `@import "tailwindcss";`.
- Result: All interface styling (card borders, section backgrounds, input bar, sidebar cards) restored.

\[FIX\] on_step callback missing extra kwarg (Brief 26 token_usage emission)

- [api.py](http://api.py) handle_message's inner `on_step` function only accepted (content, type, turn_id).
- process_request calls on_step_update with extra=token_usage.to_dict() for token_usage events.
- Added `extra=None` parameter and forwarded it to `send_update()` — fixes TypeError that would have silently dropped token_usage WebSocket events on every user request.

\[FIX\] Token tracking accuracy — FAST escalation and total_tokens derivation

- FAST→DELIBERATE escalation path silently returned deliberate_usage_list as fast_usage (a list). Aggregation code did `token_usage.add("fast_execution", list)` — getattr on a list returns 0, so all deliberate turn tokens from escalated FAST requests were counted as zero. Fixed: isinstance(fast_usage, list) check routes escalation tokens through the deliberate loop.
- total_tokens was re-derived as p+c instead of reading SDK's usage.total_tokens field. Fixed: reads total_tokens from the usage object directly, falls back to p+c only if absent.

---

## Known Issues

- **RAG build incompatibility:** PyTorch/HuggingFace version mismatch causes "Cannot copy out of meta tensor" error at startup. Affects archive injection initialization but does not crash core functionality.

---

## 2026-04-27 (continued)

[FIX] DELIBERATE named-param actions failing for single-required-param tools
- Root cause: `_validate_actions` in agent.py only extracted `item.get("query")` for
  single-arg tools. When TEMP_SYSTEM_PROMPT taught the model correct named params
  (e.g. `{"tool": "python_repl", "code": "..."}` instead of `{"tool": "python_repl", "query": "..."}`),
  the query came back empty → "Empty query" error → tool skipped silently.
- Fix 1 (agent.py `_validate_actions`): detect named params via `any(k not in ("tool", "query") for k in item)`.
  When present, serialize full item as JSON — same path the multi-arg branch already used.
  Flat-query tools still use `item.get("query")` unchanged. No-arg tools unchanged.
- Fix 2 (tool_executor.py `execute_deliberate`): added `_extract_param()` helper that
  JSON-parses the query string and extracts the right field by name. Updated all native
  tool handlers: python_repl extracts "code", web_search/consult_archive extract "query",
  query_task_status extracts "keyword", vision_tool extracts "path"+"question".
  Each falls back to raw query string if JSON parse fails (backward compatible).

[UPDATE] DELIBERATE system prompt experiment (TEMP_SYSTEM_PROMPT)
- Removed static tool list from SYSTEM_PROMPT section.
- Replaced with tool_search JSON schema block as the sole tool anchor.
- Replaced 5 concrete examples with 1 pseudo-example showing tool_search → call flow.
- Updated rules to remove specific tool name references (python_repl → "code execution", etc).
- Batching example now uses `<tool_a>`/`<tool_b>` placeholders instead of real tool names.
- [SYSTEM MODE: TASK] user message stripped to single line — system prompt covers the rest.
- Plugged into agent.py as `self.system_prompt = TEMP_SYSTEM_PROMPT` for testing.

---

## 2026-04-28

[FIX] TOOL_ARG_DEFAULTS not applied in JSON parse path (tool_executor.py)
- `TOOL_ARG_DEFAULTS` block was positioned after the JSON early-return, so when the model
  explicitly passed JSON args, defaults were never injected.
- Hoisted `TOOL_ARG_DEFAULTS` dict above the JSON parse branch and applied it inside the
  JSON branch too: fills missing args only, never overwrites explicit values.
- Affected tools: write_file (mode), start_process (timeout_ms), read_process_output (timeout_ms),
  interact_with_process (timeout_ms), list_directory (depth).

[FIX] write_file "w" mode normalization (tool_executor.py)
- Model generates `"mode": "w"` from Python training priors. Desktop Commander requires
  `"rewrite"` | `"append"` — `"w"` causes a silent rejection.
- Added `TOOL_ARG_NORMALIZERS` dict in `_build_args_from_query`. Applied after JSON parse:
  maps `"w"` → `"rewrite"`, `"a"` → `"append"`. Explicit override — fires even when model
  provides the arg, unlike defaults which only fill missing values.

[FIX] Hallucination handler double-increment (agent.py)
- When hallucination detected, the handler did `turn_count += 1` before `continue`, then
  the loop's own `turn_count += 1` fired on the next iteration. Net: 2 turns burned per
  hallucination event (Loop 1 → Loop 3).
- Removed the extra `turn_count += 1` from the hallucination handler. Detection now burns
  exactly 1 turn.

[FIX] Observation → Glint rename — DELIBERATE loop coin token (agent.py)
- Coined custom token "Glint" to replace "Observation" everywhere in the ReAct loop.
- Root cause: "Observation:" is a strongly learned bigram in ReAct training data. Model
  pattern-completes `Action: [...]\nObservation:` from prior, hallucinating tool results
  before the tool actually runs.
- "Glint" has zero training prior as a ReAct token — hallucination pressure near zero.
- Changes in agent.py:
  - Regex in thought extraction: `Observation` → `Glint`
  - Hallucination detector: checks for `Glint:` without preceding `Action:`, corrects with
    updated message referencing Glint
  - Loop variables: `observations` → `glints`, `obs` → `glint`, `combined_observation` → `combined_glints`
  - Log strings: `Obs:` → `Glint:`, `[Observation]` → `[Glint]`
  - Comment: "Feed all observations" → "Feed all Glints"
- Changes in system_prompt.py (both SYSTEM_PROMPT and TEMP_SYSTEM_PROMPT):
  - All `Observation:` lines in execution loop format → `Glint:`
  - `Trust observations.` → `Trust Glints.`
  - `After each observation:` → `After each Glint:`
- Changes in tool_registry.py: `format_tool_schemas_for_observation` → `format_tool_schemas_for_glint`
- Changes in tool_executor.py: import and call updated to `format_tool_schemas_for_glint`

[FIX] Inline hallucination detector — Action + fabricated Glint in same turn (agent.py)
- Stress test (20 queries, 2026-04-28) revealed 4/5 hallucination failures shared one pattern:
  model writes `Action: [...]` then immediately generates fake `Glint:` content in the same
  token stream, before the system executes anything. The existing detector condition
  (`"Glint:" in content and "Action:" not in content`) missed all of these because Action WAS present.
- Added `elif "Glint:" in raw_content and "Action:" in raw_content` branch:
  strips `raw_content` from the first `Glint:` onward, sets `inline_hallucination = True`,
  falls through to real `parse_actions()` on the truncated (clean) response.
- After appending the truncated assistant message, injects a corrective user message:
  "fabricated Glint was discarded — your Action is being executed now, wait for the real Glint."
- Model then receives the real system-generated Glint and continues correctly.
- Does not increment turn count — hallucination costs 0 extra turns on this path.

[UPDATE] DELIBERATE loop quality improvements (agent.py, system_prompt.py)
- Rule 4 replaced with structured error taxonomy: Recoverable / Tool-not-found /
  Genuinely-impossible. Prevents model from treating recoverable errors as dead ends.
- Thought description rewritten in both prompts: explicit guidance for post-Glint reasoning,
  post-failure classification, and pre-Final-Answer completion check.
- Rule 11 tightened: "Once all sub-tasks are resolved — write Final Answer immediately."
- Rule 16 added to both prompts: COMPLETION CHECK before Final Answer.
- `_turn_message()` helper added in agent.py: prefixes every Glint message with `[Turn N/8]`.
  On final turn, appends `[FINAL TURN]` wrap-up instruction — forces conclusion instead of
  burning the last turn on another tool call.
- Turn budget initializer: `llm.append(user("[SYSTEM MODE: TASK] [Turn 1/8] ..."))`
- `last_response_text` tracked per-turn: fallback return gives the user the last model output
  instead of a canned "I ran out of steps" message.

[FIX] Interpreter routing — write_file with generated content (interpreter.py)
- Q18 retest: Interpreter routed "Draft a new class in core_logic/proactive_commit.py" as
  CHAT (tool=None, requires_planning=False, confidence=0.95). Root cause: routing guidance
  treated write_file as single-step regardless of whether content exists in the query or must
  be composed. "Draft" + file path → Interpreter assigned write_file but content was a placeholder
  → FAST path couldn't generate code → fell through to CHAT.
- Added rule to routing guidance: write_file where content must be GENERATED (code, structured
  text, class drafts, analysis) → requires_planning=true even if the path is clear. Generating
  content is always multi-step: compose first, then write. write_file where content IS the query
  (e.g. "write 'hello' to file.txt") → requires_planning=false as before.

[UPDATE] list_directory depth guidance in Rule 13 (system_prompt.py)
- Added explicit depth guidance to Rule 13: omit depth or use 0 by default — immediate contents
  only, no chunk risk. Only use depth > 0 when subdirectory structure is explicitly needed AND
  directory is known to be sparse. Dense directories (__pycache__, model weights, indexes) will
  overflow at depth > 0. Rule 4 chunk-limit handles recovery when it happens.
- Addresses scale concern: as project grows, more directories become dense. Model now has
  explicit in-context guidance rather than relying on training priors for depth selection.

---

## 2026-04-29
- Stress test Q18 root cause traced: `depth: 1` was not in DC's list_directory schema at all
  (schema only exposes `path`). CLARA learned it from the Rule 14 example in SYSTEM_PROMPT:
  `Action: [{"tool": "list_directory", "path": "...", "depth": 1}]` — model pattern-matched
  from its own prompt. DC accepts unknown params silently; depth=1 descends into __pycache__,
  models/, knowledge_base/, moondream_brain/ and overflows the stdio buffer on dense directories.
  The read_file chunk error in the same batch was collateral — DC's framing corrupted by the
  oversized list_directory response, not by the file being absent.
- Fix 1 (system_prompt.py): Removed `depth: 1` from both list_directory examples in
  SYSTEM_PROMPT (Rule 14 correct example + Examples section). Model no longer learns this pattern.
- Fix 2 (system_prompt.py): Added chunk-limit as a fourth error class in Rule 4 ERROR CLASSIFICATION
  in both SYSTEM_PROMPT and TEMP_SYSTEM_PROMPT. When "chunk exceed the limit" appears, CLARA
  retries the same tool on the same path with reduced scope (omit depth, narrower subpath, or
  specific filename) — not by changing paths or treating it as a missing file.
- Fix 3 (tool_executor.py): `TOOL_ARG_DEFAULTS` had `list_directory: {depth: 2}` — worse than
  the prompt example, silently injecting depth=2 whenever the model omitted depth entirely.
  Changed to `depth: 0`. Model can still pass an explicit depth when genuinely needed.
- Capability preserved: CLARA can still use depth when genuinely needed. The fix is behavioral
  (learn from the right example, recover correctly from chunk-limit) not a hard gate.

[REFACTOR] TEMP_SYSTEM_PROMPT promoted to SYSTEM_PROMPT (system_prompt.py, agent.py)
- Stress test (20 queries, 2026-04-28) ran entirely on TEMP_SYSTEM_PROMPT and validated it.
- TEMP_SYSTEM_PROMPT is structurally better: no hardcoded tool list (can't go stale), no
  project-specific path examples, tool_search schema injected inline, cleaner rules throughout.
- Old SYSTEM_PROMPT deleted. TEMP_SYSTEM_PROMPT renamed to SYSTEM_PROMPT in system_prompt.py.
- agent.py import and self.system_prompt reference updated accordingly.
- TEMP_SYSTEM_PROMPT no longer exists as a separate variable.

[UPDATE] Rule 13 search-first pattern — filesystem resolution (system_prompt.py)
- Old Rule 13: always list_directory first to confirm a path exists.
- New Rule 13: when given a filename, use start_search first — confirms existence and returns
  exact path in one call, no chunk-limit risk. Only fall back to list_directory (no depth) if
  search returns nothing, to check for typos or casing in the parent directory.
- list_directory is no longer the first move for named file resolution.

---

## Statistics

- **Commits:** 30+ (from 2025-12-24 to 2026-05-08)
- **Briefs:** 26 implemented (Brief 0 through Brief 26)
- **Native tools:** 6 (web_search, python_repl, date_time, vision_tool, consult_archive, query_task_status)
- **MCP tools (Desktop Commander):** 26
- **Total registry tools:** 32 (tool_search injected to DELIBERATE, not registered)
- **Lines of code:** ~12K Python, ~4K JavaScript/React
- **Project duration:** ~5 months (Dec 2025 — May 2026)
