# C.L.A.R.A.

**Contextual Locally Aware Robust Agent** — an autonomous AI system that runs end to end on consumer hardware, checks every action before it takes it, and grades itself twice a day against its own source code.

> Built and operated daily on an RTX 3050 laptop (4GB VRAM). The constraint is the interesting part.

---

## What this actually is

Most agent projects are a loop around an LLM with some tools bolted on. CLARA is built around two questions that only matter once an agent runs unsupervised:

1. **How do you stop it doing something it shouldn't?** → a governance gate that adjudicates every action *before* it executes, and writes a receipt to a tamper-evident ledger.
2. **How do you know it still works?** → a deterministic evaluation harness that grades her against the live source tree twice a day, with no model in the grading path.

Everything else — the orchestrator, the router, the memory, the tooling — exists to make those two things possible on hardware that cannot hold a large model in VRAM.

---

## The execution pipeline

Every input takes the same path. There are no bypasses — a user message, a background trigger and an environment event are all the same kind of thing.

```
INPUT (user / system / background / environment)
        ↓
   EventQueue  (async priority queue)
        ↓
  OrchestratorLoop
        ↓
   Interpreter  →  structured intent JSON
        ↓
     Router  →  FAST | CHAT | DELIBERATE
        ↓
  Governance gate  →  ALLOW / REVIEW / DENY   (receipt written before the action fires)
        ↓
    Execution  →  response
        ↓
  memorize_episode  (background)
```

**Three execution modes**, so compute is spent in proportion to how hard the task is:

| Mode | When | Latency |
|---|---|---|
| `FAST` | tool is known, high confidence, no planning needed | ~2-4s |
| `CHAT` | no tool needed, conversational | ~1.5-2.5s |
| `DELIBERATE` | planning required, low confidence, or FAST failed | ~5-30s (ReAct, 8 turns) |

FAST escalates to DELIBERATE on failure, injecting what was tried and why it failed, so the retry adapts instead of repeating.

---

## The two things worth looking at

### 1. Pre-execution governance

Before any mutating action runs, it is abstracted into a **privacy-preserving envelope**: an operation class, a coarse target class, a hash of the target rather than the target itself, and coarse risk and reversibility labels. Raw content never leaves the machine.

That envelope is adjudicated by a pluggable policy adapter — a local policy, or an external governance engine — which returns `ALLOW`, `REVIEW`, or `DENY`. The verdict and a receipt are written to a tamper-evident ledger **before** the action is allowed to proceed.

The design principle: *a record written after the fact, by the process that acted, is not evidence.* Authorization and its evidence have to be causally upstream of execution.

Runs in shadow mode by default (verdicts recorded, nothing blocked) with an enforce mode and an explicit fail-open/closed posture.

### 2. Self-verification (the Drill)

Twice a day, a harness fires 23 questions per run (46 a day) at the live system and grades the answers **deterministically against the current source tree** — never by asking another model.

- Each question class carries its own machine-checkable oracle: exact counts, set coverage, verbatim quotes, executable acceptance tests, and **absence-honesty probes** where the correct answer is "this does not exist" and any fabricated file:line citation auto-fails.
- A **six-level difficulty ladder** promotes a question one rung after a sustained pass streak, so the benchmark gets harder as the system improves rather than saturating.
- **The grader is itself under test.** A 62-case fixture suite regression-tests the scoring engine on every run and stamps the report if the engine fails its own fixtures. This exists because a scoring bug once quietly failed a set of answers that were correct — and a broken evaluation looks exactly like a broken model until something checks.

```bash
python tests/test_harness.py --session morning   # or: evening
```

---

## Architecture map

| Module | Path | Role |
|---|---|---|
| API server | `api.py` | FastAPI + concurrent WebSocket |
| Agent | `core_logic/agent.py` | routing, FAST / CHAT / DELIBERATE execution |
| Interpreter | `core_logic/interpreter.py` | intent + routing decision |
| Orchestrator | `core_logic/orchestrator.py` | the persistent loop, dispatch, retry |
| TaskGraph | `core_logic/task_graph.py` | SQLite task state machine + crash recovery |
| EventQueue | `core_logic/event_queue.py` | async priority queue |
| Governance | `core_logic/admissibility.py` | envelopes, risk classification, verdicts |
| Memory | `core_logic/crud.py` | episodic log, fact vault, semantic retrieval |
| Tool registry | `core_logic/tool_registry.py` | native + MCP tool schemas, semantic search |
| Tool executor | `core_logic/tool_executor.py` | unified dispatch |
| Voice | `core_logic/voice.py` | Whisper STT + Kokoro TTS on CUDA |

**Memory** is a three-tier store: an episodic log with vector retrieval (recency + cosine similarity), a deduplicated long-term fact vault, and a verbatim recent-conversation window. Persistence is crash-safe (temp file → fsync → atomic replace), because a hard kill mid-write once truncated the store.

**Tooling** is 30+ tools across native Python functions and MCP servers, retrieved semantically per query rather than dumped into the prompt.

---

## Running it

**Prerequisites:** Python 3.11, Node.js, NVIDIA CUDA 12.x, [eSpeak NG](https://github.com/espeak-ng/espeak-ng/releases) on PATH, and FFmpeg.

```bash
git clone https://github.com/Angry-Nutrino/AGENT_ZERO.git
cd AGENT_ZERO

python -m venv jarvis_v2
jarvis_v2\Scripts\activate                 # Windows

pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt

cd interface && npm install && cd ..
```

**Configuration** — create `core_logic/.env`:

```env
DEEPSEEK_API_KEY=...      # cloud reasoning, via an OpenAI-compatible API
GEMINI_API_KEY=...        # vision
tavily_api=...            # web search
DC_NODE_PATH=...          # optional: Desktop Commander MCP
DC_CLI_PATH=...
```

**Start** (two terminals):

```bash
python api.py             # backend on :8001
cd interface && npm run dev   # dashboard on :5173
```

Or start the whole stack with `bash start_clara.sh` (and `bash stop_clara.sh` to stop it).

---

## Status and honesty

This is a personal system in daily use, not a product. Some things worth stating plainly:

- The governance gate ships in **shadow mode** by default. Enforce mode exists and works, but the policy is still maturing.
- Layer 4 of the self-assessment ladder — the agent applying its own fixes — is **deliberately not built**. She writes fix proposals for persistent failures; every one is a review-only artifact and nothing is auto-applied.
- Some modules are legacy and no longer imported (`sight.py`, `ears.py`, `kokoro_mouth.py`). They are kept for history, not use.
- It runs on 4GB of VRAM. That shapes almost every architectural decision here.

---

## License

No license granted. All rights reserved. Read it, learn from it, but please do not redistribute.
