import re
import json
import asyncio
import base64
import threading
import torch
from dataclasses import dataclass, field
from sentence_transformers import SentenceTransformer
from .tools import (
    run_python_code, web_search, get_time_date, consult_archive,
    query_task_status, get_archive_context,
)
from .system_prompt import SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT, PERSONA
from .bench_logger import Timer, log_request
from .interpreter import interpret, TOOL_ARG_SCHEMAS
from .memory_manager import free_gpu_memory
# from .ears import listen_local
# from .kokoro_mouth import speak
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

_DS_CLIENT: AsyncOpenAI | None = None
_DS_SYNC_CLIENT = None  # sync OpenAI client for memorize_episode (thread-safe, reused)


def _ds_client() -> AsyncOpenAI:
    """Shared DeepSeek async client (lazy singleton). A fresh client per call threw
    away the httpx keep-alive pool, paying TCP+TLS setup on EVERY LLM call —
    interpreter, CHAT stream, FAST formatter, and each DELIBERATE turn (Brief 36 C-1).
    Request isolation lives in the per-request `llm` message list, not the transport.
    """
    global _DS_CLIENT
    if _DS_CLIENT is None:
        _DS_CLIENT = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )
    return _DS_CLIENT


def _ds_sync_client():
    """Shared sync DeepSeek client for the consolidation thread (Brief 36 B-13)."""
    global _DS_SYNC_CLIENT
    if _DS_SYNC_CLIENT is None:
        from openai import OpenAI as _SyncOpenAI
        _DS_SYNC_CLIENT = _SyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )
    return _DS_SYNC_CLIENT

# DeepSeek thinking mode, DELIBERATE path ONLY (2026-06-07). The ReAct loop reasons
# before each turn to cut the from-memory-fabrication pattern; interpreter/CHAT/FAST stay
# non-reasoning (latency-sensitive, low accuracy upside). Smoke-tested: deepseek-chat accepts
# reasoning_effort + extra_body thinking, returns the CoT in a SEPARATE reasoning_content field
# (the ReAct stream reads delta.content only, so the parser is untouched). Effort is one knob:
# dial "max"->"high" if the evening bench shows the per-turn cost is too steep (DELIBERATE makes
# one LLM call PER ReAct turn, so the cost multiplies across turns).
# A/B FLIP 2026-06-11 (Alkama's call, closing the 06-08 trial): thinking OFF for the
# 06-11 evening + 06-12 morning runs. The trial never got a clean A/B (the question
# suite hardened simultaneously), so this is it — the suite is now stable and
# streak-tracked, so any previously-passing anchor failing is unambiguous signal.
# REVERT TRIGGER: one new FAIL on a previously-passing anchor -> set True immediately.
# Decision review with Alkama after the 06-12 MORNING drill.
DELIBERATE_THINKING = False
# Dialed "max"->"high" 2026-06-07 after the evening bench: thinking=max cost DELIBERATE
# +5.4s/+39% per answer (scaling with ReAct turn count) for an accuracy benefit confounded
# with question-hardening. "high" roughly halves the per-turn tax; the interpreter router rule
# is the real fabrication guard. (Effort value is inert while DELIBERATE_THINKING=False.)
DELIBERATE_REASONING_EFFORT = "high"

def user(content: str) -> dict:
    return {"role": "user", "content": content}

def system(content: str) -> dict:
    return {"role": "system", "content": content}

def assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}

def _capture_react_trace(llm: list, per_msg_cap: int = 3000) -> list:
    """Brief 32 (Self-Assessment Layer 2): extract the post-routing ReAct turns from the
    conversation so the harness can feed a FAILED query's actual loop to Clara for root-cause
    diagnosis. process_request owns the `llm` list that run_task mutates in place, so by the time
    execution returns the full trace is already here — no hot-path instrumentation of the loop.

    Keeps the request + every Thought/Action/Glint/Final Answer; SKIPS the system prompt and the
    [MEMORY_CONTEXT_BLOCK] (huge, not reasoning). Large tool observations are bounded with an
    EXPLICIT [truncated] marker so the diagnosis knows an obs was clipped, not absent (Rule-19
    honesty applied to the diagnosis INPUT). Gated on return_trace — production requests never pay it."""
    turns, started = [], False
    for m in llm:
        content = m.get("content", "") or ""
        if not started:
            if m.get("role") == "user" and content.startswith("Now, execute this request:"):
                started = True
            else:
                continue
        if "[MEMORY_CONTEXT_BLOCK]" in content:
            continue
        if len(content) > per_msg_cap:
            content = content[:per_msg_cap] + f"\n…[truncated {len(content) - per_msg_cap} chars]"
        turns.append({"role": m.get("role"), "content": content})
    return turns

def _repair_json_for_parse(s: str) -> str:
    """Best-effort repair of the #1 Action parse failure: unescaped backslashes in Windows paths
    the model writes naturally inside JSON ('Invalid \\escape', ~4-9x/run — measured 2026-06-09).
    Applied ONLY after a clean json.loads has already failed, so valid JSON is never touched.
    (a) Drive-letter paths (X:\\...) → forward slashes — every tool accepts them on Windows, and
    this leaves legitimate \\n/\\t escapes in python_repl code strings alone (they aren't drive-
    path-shaped). (b) Any remaining lone backslash that is NOT a valid JSON escape → doubled
    (handles backslashed relative paths)."""
    s = re.sub(r'[A-Za-z]:\\[^"]*', lambda m: m.group(0).replace("\\", "/"), s)
    s = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)
    return s

from .crud import crud
from .session_logger import slog
from .tool_executor import execute_deliberate, execute_fast
from .tool_registry import format_tool_schemas_for_context
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))


# Filesystem tools whose paths feed the live resource ledger in the orchestrator.
_FS_WRITE_TOOLS = frozenset({"write_file", "create_directory"})
_FS_READ_TOOLS  = frozenset({"read_file", "list_directory", "start_search", "get_file_info"})


def _extract_resource_path(tool_input: str) -> str:
    """
    Pull the 'path' value out of a DELIBERATE tool_input string.
    tool_input is either a JSON-serialized action item or a flat string.
    Returns empty string if no path can be extracted — caller skips silently.
    """
    import json as _json
    stripped = tool_input.strip()
    if stripped.startswith("{"):
        try:
            return _json.loads(stripped).get("path", "")
        except Exception:
            return ""
    # Flat string — treat as path only when the tool expects one as primary arg.
    return stripped


_TASK_MARKER_RE = re.compile(r"\[\[\s*TASK\s*:\s*(COMPLETE|INCOMPLETE)\b[^\]]*\]\]", re.IGNORECASE)


def _parse_completion(text: str):
    """Brief 35 — extract + STRIP the [[TASK: COMPLETE|INCOMPLETE — reason]] marker from a
    DELIBERATE final answer. Returns (clean_text, status, reason).

    Marker is authoritative. If absent → default COMPLETE, with a conservative phrase-backstop
    that flips to INCOMPLETE ONLY on process-failure language and NEVER when a confident negative
    is present ("does not exist" / "no matches" are COMPLETE — flipping them would wrongly trigger
    a retry and pressure fabrication, the rule-19 dual / Brief 35 trap 1).
    """
    if not text:
        return text, "COMPLETE", ""
    m = _TASK_MARKER_RE.search(text)
    if m:
        status = m.group(1).upper()
        reason = ""
        if status == "INCOMPLETE":
            rm = re.search(r"INCOMPLETE\b[\s\-—:]*([^\]]+?)\s*\]\]", m.group(0), re.IGNORECASE)
            reason = rm.group(1).strip() if rm else ""
        clean = _TASK_MARKER_RE.sub("", text).strip()
        return clean, status, reason
    low = text.lower()
    PROCESS_FAIL = (
        "i was unable to", "i could not complete", "could not complete the", "i couldn't complete",
        "no filesystem tools", "no tools were available", "the tool failed", "i failed to",
        "unable to access", "couldn't access", "ran out of turns", "turn budget",
    )
    NEGATIVE_OK = (
        "does not exist", "doesn't exist", "not found", "no matches", "no occurrence",
        "there are no", "zero matches", "is absent", "does not appear", "doesn't appear",
    )
    if any(p in low for p in PROCESS_FAIL) and not any(n in low for n in NEGATIVE_OK):
        return text, "INCOMPLETE", "inferred from failure language (no marker emitted)"
    return text, "COMPLETE", ""


def _turn_message(current_turn: int, max_turns: int, body: str) -> str:
    """
    Prepend [Turn N/M] to every Glint message so the model knows its budget.
    On the final turn, append a forced wrap-up instruction so the model writes
    Final Answer instead of attempting another Action that will never execute.
    """
    next_turn = current_turn + 1
    prefix = f"[Turn {next_turn}/{max_turns}] "
    if next_turn == max_turns:
        suffix = (
            "\n\n[FINAL TURN — no further Actions will execute after this response. "
            "Write your Final Answer now. Re-read the original request at the top of this "
            "conversation before writing. Your Final Answer must directly answer that request "
            "in full — not a summary of what you did, not a confirmation that you found the "
            "answer, but the actual answer itself. "
            "State what succeeded, what failed, what you attempted for each failure, "
            "and what remains incomplete if anything.]"
        )
    else:
        suffix = ""
    return f"{prefix}{body}{suffix}"


@dataclass
class TokenUsage:
    """Accumulated token usage for a single request across all LLM calls."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    call_breakdown: dict = field(default_factory=dict)

    def add(self, label: str, usage_obj) -> None:
        if usage_obj is None:
            return
        p = getattr(usage_obj, 'prompt_tokens', 0) or 0
        c = getattr(usage_obj, 'completion_tokens', 0) or 0
        t = getattr(usage_obj, 'total_tokens', 0) or (p + c)
        # DeepSeek cache field — fall back to xAI field name for compatibility
        cached = getattr(usage_obj, 'prompt_cache_hit_tokens', 0) or 0
        if cached == 0:
            cached = getattr(usage_obj, 'cached_prompt_text_tokens', 0) or 0
        self.prompt_tokens += p
        self.completion_tokens += c
        self.total_tokens += t
        self.cached_tokens += cached
        self.call_breakdown[label] = {"prompt": p, "completion": c}

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "breakdown": self.call_breakdown,
        }


def route(interpreted: dict) -> str:
    """
    Decide execution mode from Interpreter output.
    Returns "FAST", "CHAT", or "DELIBERATE".

    FAST:       high confidence, low uncertainty, no planning needed,
                tool is specified with complete args
    CHAT:       high confidence, low uncertainty, no planning needed,
                no tool needed — direct conversational response
    DELIBERATE: anything else
    """
    if (
        interpreted.get("requires_planning") is False
        and interpreted.get("confidence", 0) >= 0.75
        and interpreted.get("uncertainty", 1) <= 0.30
    ):
        if (
            interpreted.get("tool") is not None
            and interpreted.get("args") is not None
        ):
            return "FAST"
        if interpreted.get("tool") is None:
            return "CHAT"
    return "DELIBERATE"


class Clara_Agent:
    def __init__(self, model_name="phi3:mini"):
        self.system_prompt = SYSTEM_PROMPT or """

### Role ###
You are CLARA — Alkama's autonomous agent.

### Objective ###
Execute multi-step tasks, retrieve information, and solve problems for Alkama without question or hesitation.

### Context ###
You work for Alkama and must obey his commands without question. You have access to powerful tools and must use them effectively to complete any task.

### Tools ###
You have access to the following tools:

1. Python Repl: Execute Python code for calculations, data analysis, and logic.
   Action: [{"tool": "python_repl", "code": "print(2 + 2)"}]

2. Web Search: Search the internet for real-time information.
   Action: [{"tool": "web_search", "query": "current Bitcoin price"}]

3. Date/Time: Get current date and time.
   Action: [{"tool": "date_time"}]

4. Vision Tool: Analyze images from local disk.
   Action: [{"tool": "vision_tool", "path": "/absolute/path/image.png", "question": "What is in this image?"}]

5. Consult Archive: Look up information from local documents.
   Action: [{"tool": "consult_archive", "query": "technical skills resume"}]

6. Read File: Read file contents from disk.
   Action: [{"tool": "read_file", "path": "E:\\path\\to\\file.txt"}]

7. List Directory: List files and folders in a directory.
   Action: [{"tool": "list_directory", "path": "E:\\path\\to\\folder", "depth": 1}]

8. Write File: Write content to a file on disk.
   Action: [{"tool": "write_file", "path": "E:\\path\\to\\file.txt", "content": "file content", "mode": "w"}]

9. Run Command: Execute shell commands.
   Action: [{"tool": "start_process", "command": "dir C:\\Users"}]

10. Query Task Status: Look up task status by keyword.
    Action: [{"tool": "query_task_status", "keyword": "task name"}]

### Execution Loop ###
Follow this format strictly:
Thought: Why you are doing what you're doing (1-2 sentences, plain English)
Action: [{"tool": "tool_name", "param1": "value1", "param2": "value2"}]
Glint: [Wait for system response]
... repeat until complete ...
Final Answer: Your response to Alkama

### Rules ###
1. ALWAYS output Thought before any Action.
2. Batch independent tool calls in one Action array.
3. Trust Glints — do not re-calculate.
4. On tool failure, diagnose and correct in the next turn.
5. Output Final Answer only when you have all needed information.
6. Never output Final Answer and Action in the same turn.
7. Use python_repl for ALL calculations, never mental math.
8. For filesystem tools, always use FULL ABSOLUTE PATHS.
9. When reading files, synthesize — don't dump raw content.
10. Use proper JSON format with named parameters for all tools.

### Examples ###

User: List files in core_logic directory.
Thought: I need to see the directory structure.
Action: [{"tool": "list_directory", "path": "E:\\ML PROJECTS\\AGENT_ZERO\\core_logic", "depth": 1}]
Glint: [FILE] agent.py [FILE] orchestrator.py ...
Final Answer: The core_logic directory contains agent.py, orchestrator.py, and others.

User: Write a Python test file.
Thought: I'll create a test file with the specified content.
Action: [{"tool": "write_file", "path": "E:\\ML PROJECTS\\AGENT_ZERO\\tests\\test_example.py", "content": "def test_example():\\n    assert True", "mode": "rewrite"}]
Glint: File written successfully.
Final Answer: Created test_example.py in the tests directory.

User: Search for Bitcoin price and today's date.
Thought: These are independent lookups so I can fetch both at once.
Action: [{"tool": "web_search", "query": "Bitcoin price USD"}, {"tool": "date_time"}]
Glint from web_search: Bitcoin is $95,000 USD.
Glint from date_time: 2026-04-27 12:53:55
Final Answer: Bitcoin is $95,000 USD. Today is April 27, 2026.

User: Calculate compound interest: ₹50,000 at 8% for 5 years.
Thought: I need exact calculation — use Python.
Action: [{"tool": "python_repl", "code": "print(round(50000 * (1 + 0.08)**5, 2))"}]
Glint: 73466.44
Final Answer: ₹50,000 at 8% compounded annually for 5 years grows to ₹73,466.44.

### Memory ###
At the start of each conversation, you receive [MEMORY_CONTEXT_BLOCK] containing your episodic history and long-term facts with Alkama.

Treat it as your memory. Use it to maintain continuity and avoid repeating known information.
"""
        self.chat_history = ""
        self.db = crud()
        slog.info(f"Initializing Clara with model : {model_name}")
        self.llm = None
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        slog.info(f"Loading MiniLM model for episodic memory on {device}...")
        self.miniLM = SentenceTransformer('all-MiniLM-L6-v2').to(device)
        self._miniLM_lock = asyncio.Lock()
        self._vault_lock = threading.Lock()  # guards vault writes against concurrent memorize_episode calls
        # Makes the (episodic_log append, episodic_embeddings append) PAIR atomic.
        # memorize_episode (background thread) and log_system_episode (event loop)
        # both append to the two parallel lists; interleaving between a writer's two
        # appends misaligns them at EQUAL lengths — invisible to the length-only
        # context_warmup check, and semantic retrieval then returns the WRONG episode
        # (Brief 36 B-10). Writers encode FIRST, then append both under this lock.
        self._episodic_lock = threading.Lock()
        self._event_loop = None  # set at first async call
        self.episodic_embeddings = self._build_episodic_embeddings()
        self.load_clara(model_name)
        self.tool_registry = None   # injected from api.py after startup
        self.mcp_client = None      # injected from api.py after startup
        slog.info("Brain loaded")

    def _build_episodic_embeddings(self) -> list:
        """
        Cold-start: encode all existing episodic summaries once at startup.
        Returns a list of tensors parallel to db.memory["episodic_log"].
        """
        episodes = self.db.memory.get("episodic_log", [])
        if not episodes:
            slog.info("   [Memory] No episodic entries to embed at startup.")
            return []
        summaries = [ep.get("summary", "") for ep in episodes]
        slog.info(f"   [Memory] Encoding {len(summaries)} episodic entries at startup...")
        embs = self.miniLM.encode(summaries, convert_to_tensor=True)
        return [e.to('cpu') for e in embs]  # store on CPU — must match memorize_episode embeddings

    async def _encode(self, texts, convert_to_tensor=True):
        """
        Thread-safe MiniLM encoder. All miniLM.encode() calls must go through here.
        The asyncio.Lock serializes all encode access (CUDA is not thread-safe for
        concurrent kernels on one model instance); the actual encode runs in a worker
        thread so a large batch (e.g. a 1000-summary re-sync) no longer stalls the
        event loop for its duration (Brief 36 A-1). Serialization is unchanged — the
        lock is held across the to_thread call.
        """
        async with self._miniLM_lock:
            return await asyncio.to_thread(
                self.miniLM.encode, texts, convert_to_tensor=convert_to_tensor
            )

    def _encode_sync(self, texts):
        """
        Sync wrapper for use inside background threads (e.g. memorize_episode).
        Submits encode to the event loop and blocks until complete.
        Raises concurrent.futures.TimeoutError if encode takes > 30s.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._encode(texts, convert_to_tensor=True),
            self._event_loop
        )
        return future.result(timeout=30)

    def load_clara(self, model_name="deepseek-chat"):
        try:
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
            if not api_key:
                raise ValueError("DEEPSEEK_API_KEY not set in .env")
            self.client = None  # No longer a persistent client — created fresh per request
            slog.info("Clara Brain loaded (DeepSeek V4 Flash).")
        except Exception as e:
            slog.error(f"Failed to load Clara Brain: {e}")
        
    def unload_clara(self):
        print("Putting Clara Brain to sleep...")
        free_gpu_memory(self.llm)
        self.llm = None
    

    @staticmethod
    def _extract_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
        """Return the balanced substring starting at text[0] (which must be open_ch),
        respecting JSON string literals + escapes. None if no matching close is found.

        Used so brackets/braces INSIDE a quoted JSON string (e.g. Python code like
        text[:3000] or a list comprehension) never affect structural balancing.
        """
        if not text or text[0] != open_ch:
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[:i + 1]
        return None

    def parse_actions(self, llm_output: str) -> list:
        """
        Three-layer parser for batched JSON action format.
        Always returns a list of dicts: [{"tool": str, "query": str}]
        Returns [] only if absolutely no action is found.
        Each failed extraction is represented as {"tool": None, "query": None, "error": "reason"}.
        """
        # Build VALID_TOOLS dynamically from the registry so all MCP tools
        # and tool_search are always included without manual maintenance.
        # Falls back to core native set if registry is not yet available.
        if self.tool_registry and self.tool_registry.is_ready:
            VALID_TOOLS = set(self.tool_registry._tools.keys()) | {"tool_search"}
        else:
            VALID_TOOLS = {
                "web_search", "python_repl", "date_time", "vision_tool",
                "consult_archive", "query_task_status", "tool_search",
            }

        # ── Locate "Action:" in the output ────────────────────────────────────────
        action_match = re.search(r"Action:\s*", llm_output)
        if not action_match:
            return []

        after_action = llm_output[action_match.end():]

        # Strip markdown code fences (```json ... ```) — the model often wraps the
        # Action in one, and the fence markers interfere with JSON extraction.
        after_action = re.sub(r"```(?:json)?", "", after_action)

        last_json_error: str | None = None

        # ── BARE-OBJECT PATH (2026-06-01 fix) ─────────────────────────────────────
        # The model sometimes emits {...} instead of the required [{...}]. The array
        # path below uses find("[") and would latch onto a [ INSIDE the code string
        # (e.g. text[:3000], a list comprehension), extracting garbage like "[:3000]"
        # → "Expecting value: line 1 column 2". So when a { precedes any [ (or there is
        # no [), parse the object directly and wrap it as a single-action list.
        bracket_pos = after_action.find("[")
        brace_pos = after_action.find("{")
        if brace_pos != -1 and (bracket_pos == -1 or brace_pos < bracket_pos):
            obj_str = self._extract_balanced(after_action[brace_pos:], "{", "}")
            if obj_str:
                try:
                    parsed = json.loads(obj_str)
                    if isinstance(parsed, dict):
                        return self._validate_actions([parsed], VALID_TOOLS)
                except json.JSONDecodeError as e:
                    last_json_error = str(e)
            # A bare object must NOT fall through to the array path — find("[") there
            # would re-trigger the bracket collision. Report the real cause instead.
            if last_json_error:
                # Same backslash/path repair for the bare-{...} case before reporting failure.
                try:
                    repaired = _repair_json_for_parse(obj_str)
                    if repaired != obj_str:
                        parsed, _ = json.JSONDecoder().raw_decode(repaired)
                        if isinstance(parsed, dict):
                            slog.info("   [Parser] Recovered bare-object via Windows-path/backslash repair.")
                            return self._validate_actions([parsed], VALID_TOOLS)
                except (json.JSONDecodeError, ValueError):
                    pass
                slog.warning(f"   [Parser] Object-action JSON parse failed: {last_json_error}")
                return [{"tool": None, "query": None, "error": (
                    f"Malformed JSON in Action: {last_json_error}. The Action must be a JSON "
                    f"array, e.g. [{{\"tool\": \"python_repl\", \"code\": \"...\"}}]. Put any "
                    f"multi-line code in ONE JSON string using \\n for newlines; do not wrap "
                    f"the Action in a markdown code block."
                )}]

        # ── LAYER 1 & 2: JSON array path ──────────────────────────────────────────
        bracket_start = bracket_pos
        if bracket_start != -1:
            # Layer 1: Direct json.loads on everything from [ onward
            candidate = after_action[bracket_start:]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    # Only treat as JSON action format if at least one item is a dict
                    # (a list of strings = misidentified old format, fall through to Layer 3)
                    if any(isinstance(item, dict) for item in parsed):
                        return self._validate_actions(parsed, VALID_TOOLS)
            except json.JSONDecodeError as e:
                last_json_error = str(e)

            # Layer 2: Bracket counting to find true closing ]
            depth = 0
            end_idx = -1
            in_string = False
            escape_next = False
            for i, ch in enumerate(candidate):
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        end_idx = i
                        break

            if end_idx != -1:
                clean = candidate[:end_idx + 1]
                try:
                    parsed = json.loads(clean)
                    if isinstance(parsed, list):
                        # Only treat as JSON action format if at least one item is a dict
                        if any(isinstance(item, dict) for item in parsed):
                            return self._validate_actions(parsed, VALID_TOOLS)
                except json.JSONDecodeError as e:
                    last_json_error = str(e)

            # Both JSON layers failed — if we have a JSON error, report it instead of
            # silently falling through. Clara needs to know her JSON was malformed so
            # she can fix it, not retry the same broken action indefinitely.
            if last_json_error:
                # Repair the dominant failure (unescaped Windows-path backslashes) and re-parse
                # before giving up — recovers the action on the FIRST pass instead of burning a
                # turn on a retry. raw_decode tolerates any trailing junk after the array.
                try:
                    repaired = _repair_json_for_parse(candidate)
                    if repaired != candidate:
                        parsed, _ = json.JSONDecoder().raw_decode(repaired)
                        if isinstance(parsed, list) and any(isinstance(i, dict) for i in parsed):
                            slog.info("   [Parser] Recovered via Windows-path/backslash repair.")
                            return self._validate_actions(parsed, VALID_TOOLS)
                except (json.JSONDecodeError, ValueError):
                    pass
                slog.warning(f"   [Parser] JSON parse failed: {last_json_error}")
                return [{"tool": None, "query": None, "error": (
                    f"Malformed JSON in Action: {last_json_error}. Emit the Action as a single "
                    f"JSON array, e.g. [{{\"tool\": \"python_repl\", \"code\": \"...\"}}]. Put any "
                    f"multi-line code in ONE JSON string using \\n for newlines (not real line "
                    f"breaks); use forward slashes in Windows paths; do not wrap it in a code block."
                )}]

        # ── LAYER 3: Old format fallback  tool_name[input] ────────────────────────
        old_match = re.search(r"(\w+)\[(.+?)\]", after_action, re.DOTALL)
        if old_match:
            tool = old_match.group(1).strip()
            query = old_match.group(2).strip().strip('"').strip("'")
            if tool in VALID_TOOLS:
                slog.warning(f"   [Parser] Fell back to old format. Tool: {tool}")
                return [{"tool": tool, "query": query}]
            else:
                return [{"tool": None, "query": None, "error": f"Unknown tool in old format: '{tool}'"}]

        return []

    def _validate_actions(self, parsed: list, valid_tools: set) -> list:
        """
        Validates each item in a parsed JSON array.
        Returns a list where invalid items are replaced with error dicts.
        Handles both old format (single "query" param) and new format (named parameters).
        """
        result = []
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                result.append({"tool": None, "query": None, "error": f"Item {i} is not a dict"})
                continue

            # Graceful remap of the LangChain ReAct format the model sometimes drifts into:
            # {"action": "web_search", "action_input": {...} | "..."} → {"tool": ..., <named/query>}.
            # We parse it (so the turn isn't wasted) but flag it so run_task intimates Clara that
            # her format was off and she should use {"tool": ..., "query": ...} next. (2026-06-02)
            reformatted = False
            if "tool" not in item and isinstance(item.get("action"), str):
                item = dict(item)  # copy — don't mutate the caller's parsed list
                item["tool"] = item.pop("action")
                ai = item.pop("action_input", None)
                if isinstance(ai, dict):
                    item.update(ai)        # merge named params (query / code / path / etc.)
                elif ai is not None:
                    item["query"] = str(ai)
                reformatted = True

            tool = str(item.get("tool", "")).strip()

            if tool not in valid_tools:
                result.append({"tool": None, "query": None, "error": f"Unknown tool: '{tool}'"})
                continue

            # Get schema to understand tool's required parameters
            schema = None
            required_params = []
            is_no_arg_tool = False
            if self.tool_registry and self.tool_registry.is_ready:
                schema = self.tool_registry.get_schema(tool)
                if schema:
                    required_params = schema.get("inputSchema", {}).get("required", [])
                    is_no_arg_tool = len(required_params) == 0

            # Check for required parameters
            has_required_args = all(param in item for param in required_params) if required_params else True

            # Build query string — three cases:
            # 1. Item uses named params (anything beyond "tool"/"query") → serialize full JSON
            #    so the executor can unpack the right fields regardless of param count.
            # 2. Item uses flat "query" key → use it directly (old-style).
            # 3. No-arg tool → empty string, passes validation below.
            has_named_params = any(k not in ("tool", "query") for k in item)
            if has_named_params:
                query = json.dumps(item)
            else:
                query = str(item.get("query", "")).strip()

            # Validation: all required args must be present OR it's a no-arg tool
            if not has_required_args and not is_no_arg_tool:
                result.append({
                    "tool": None,
                    "query": None,
                    "error": f"Missing required parameters for tool '{tool}': {required_params}"
                })
                continue

            # Validation: flat-query tools (no named params) must have a non-empty query
            if not has_named_params and not is_no_arg_tool and not query:
                result.append({
                    "tool": None,
                    "query": None,
                    "error": f"Empty query for tool '{tool}'"
                })
                continue

            action = {"tool": tool, "query": query}
            if reformatted:
                action["_reformatted"] = True
            result.append(action)

        return result
    
    def parse_json_safely(self, text):
        original = text

        # 1. Hard clean: remove BOM + whitespace
        text = text.strip().lstrip("\ufeff")

        # 2. Remove markdown fences properly
        text = re.sub(r"```(?:json)?|```", "", text).strip()

        # 2b. Fix invalid JSON escape sequences (e.g. \' is not valid JSON)
        text = text.replace("\\'", "'")

        # 3. Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_error = str(e)

        # 4. Extract smallest JSON object (non-greedy)
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0).strip())
            except json.JSONDecodeError as e:
                last_error = str(e)

        slog.error(f"JSON Parse Failed: {last_error} | Input: {original[:80]}...")
        return None

    def log_system_episode(self, summary: str) -> None:
        """
        Write an autonomous/system episodic entry with a zero-vector embedding
        to maintain episodic_embeddings sync with episodic_log.
        System entries are filtered from retrieval ([AUTONOMOUS] prefix) so
        the zero vector will never pollute semantic search results.
        """
        zero_emb = torch.zeros(384, dtype=torch.float32)  # MiniLM output dim
        # Pair-atomic with memorize_episode's append (B-10) — see _episodic_lock.
        with self._episodic_lock:
            self.db.add_episodic_log(summary)
            self.episodic_embeddings.append(zero_emb)

    def memorize_episode(self, chat_snapshot: str, source: str = "user"):
        """
        Dual-Layer Memory Processing:
        1. Summarizes the last session for the Episodic Stream (Always).
        2. Extracts permanent facts for the Long-Term Vault (Conditional).
        """
        if not chat_snapshot: return
        slog.info("   [Memory] Consolidating memories...")
        
        # The prompt asks for a JSON object with two keys: 'summary' and 'facts'
        memory_prompt = (
            "You are Clara's memory consolidation system. Your job is to compress a raw conversation into a clean memory entry.\n\n"
            "RULES:\n"
            "- Write the summary as a plain description of what was discussed and what happened. Example: 'Alkama asked about Galaxy S26 pricing in India. Clara searched and found base at ₹79,990.'\n"
            "- Do NOT mention internal system details: no 'CHAT mode', 'TASK mode', 'memory context block', 'gatekeeper', 'routing', or any technical pipeline terms.\n"
            "- Do NOT mention the prefix 'Now, execute this request:' — strip it and focus on what Alkama actually said.\n"
            "- Keep the summary to 1-2 sentences focused purely on the content of the exchange.\n\n"
            "- FACTS: Extract only TRULY PERMANENT facts worth remembering forever. Each fact MUST be a plain string sentence. DO NOT use dicts or objects — strings only.\n"
            "  A fact qualifies if it is:\n"
            "  * A personal attribute of Alkama (name, relationship, personality trait, confirmed preference)\n"
            "  * A stable project decision or architectural constraint\n"
            "  * A real-world fact about a person, place, or thing that won't change\n"
            "  * Something Alkama explicitly stated as a standing preference or rule\n\n"
            "- DO NOT extract as facts:\n"
            "  * Architectural or operational facts about Clara herself — those belong in self_learning, not facts\n"
            "  * File paths, file counts, file sizes, screenshot metadata, directory listings\n"
            "  * Timestamps, dates of events, or anything time-sensitive\n"
            "  * Tool outputs or Glints (web search results, command output)\n"
            "  * Anything that could be stale within days or weeks\n"
            "  * Negative-existence claims from a tool that returned no results, errored, or reported a "
            "search/index problem — an empty or failed search is NOT proof that something is absent\n\n"
            "- style_update: If Alkama explicitly stated a response style preference (e.g. 'be more detailed', "
            "'shorter responses', 'stop being verbose', 'I want more detail'), extract as one of: "
            "\"concise\", \"detailed\", \"default\". Otherwise null.\n\n"
            "- self_learning: Extract ONLY if ONE of these occurred:\n"
            "  (a) Clara made a clear mistake then corrected it mid-session (e.g. wrong tool, wrong path, hallucinated result)\n"
            "  (b) Clara discovered a new definitive fact about her own architecture not already in CLAUDE.md\n"
            "  If neither happened, leave null. DO NOT extract routine successes, facts about Alkama, or things documented in CLAUDE.md.\n"
            "  CRITICAL: NEVER record that something 'does not exist', 'is not defined', 'is not in file X', or "
            "'the codebase lacks Y' when the evidence is an empty result, a tool error, or a 'stale/broken search index'. "
            "A failed or empty tool call is a tool failure, NOT evidence of absence — recording it poisons memory with a false fact.\n"
            "  When extracted, provide:\n"
            "  { \"category\": \"architecture_facts|failure_patterns|recovery_methods\",\n"
            "    \"key\": \"one-line summary/trigger/problem (the dedup key for this category)\",\n"
            "    \"detail\": \"specific actionable detail/correct_approach/method\",\n"
            "    \"confidence\": 0.75 }\n\n"
            "- discourse: 1-5 SHORT noun-phrase tags naming the concrete subjects/topics being "
            "discussed in THIS exchange (e.g. [\"Seiko Presage watch\", \"Omega Seamaster\", \"price by region\"] "
            "or [\"parse_actions bracket bug\", \"JSON action format\"]). Concrete subjects only — NOT process/meta "
            "terms, NOT 'Alkama', NOT 'Clara', NOT execution-mode names. Empty list for a pure greeting/acknowledgment.\n\n"
            "Output ONLY a JSON object, no extra text:\n"
            "{ \"summary\": \"Alkama asked X. Clara did Y.\", \"facts\": [], \"style_update\": null, \"self_learning\": null, \"discourse\": [] }\n"
            "If no permanent facts qualify, leave 'facts' as []. If no style change, leave 'style_update' as null. If no learning, leave 'self_learning' as null. If purely a greeting, leave 'discourse' as []."
        )
        
        try:
            sync_client = _ds_sync_client()
            messages = [
                {"role": "system", "content": memory_prompt},
                {"role": "user", "content": f"Interaction:\n{chat_snapshot}"},
            ]
            _mem_resp = sync_client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                stream=False,
            )
            content = _mem_resp.choices[0].message.content or ""
            slog.info(f"   [Memory] Raw consolidation output: {content}")
            temp_llm=None
            
            # # 2. Sanitize JSON
            # if "```" in content:
            #     content = content.split("```")[1]
            #     if content.startswith("json"):
            #         content = content[4:]
            #     content = content.strip()
            # Using a different approach to extract JSON that is more robust to formatting issues:
            
            # 3. Parse
            data = self.parse_json_safely(content)
            if data is None:
                slog.error("   [Memory] parse_json_safely returned None — raw output was not valid JSON. Consolidation aborted.")
                return

            # 4. Save to The Stream (Episodic). Encode FIRST, then append the
            # (log entry, embedding) pair atomically — a concurrent log_system_episode
            # between the two appends would misalign the parallel lists (B-10).
            summary = data.get("summary", "Interaction completed.")
            new_emb = self._encode_sync(summary).to('cpu')
            with self._episodic_lock:
                self.db.add_episodic_log(summary)
                self.episodic_embeddings.append(new_emb)
            slog.info(f"   [Memory] Episodic embedding updated ({len(self.episodic_embeddings)} total)")

            # 4b. Response style update — if Alkama stated a style preference
            style_update = data.get("style_update")
            if style_update and style_update in ("concise", "detailed", "default"):
                self.db.update_response_style(style_update, note=f"Alkama requested {style_update} responses")
                slog.info(f"   [Memory] Response style updated to: {style_update}")

            # 4c. Active-discourse state (Topic 4, Phase 2) — salient subjects of this exchange.
            # USER turns ONLY: discourse_state anchors "what WE are discussing", so a system/
            # autonomous task (health_check, memory_maintenance, a cancelled task) must not leak
            # into it. (episodic/facts/self_learning above stay universal — Clara learns from
            # autonomous work too; only discourse is conversation-scoped, like recent_exchanges.)
            if source == "user":
                disc = data.get("discourse")
                if isinstance(disc, list) and disc:
                    tags = [d for d in disc if isinstance(d, str)]
                    if tags:
                        self.db.update_discourse_state(tags)
                        slog.info(f"   [Memory] Discourse state updated: {tags}")

            # 5. Save to The Vault (Long Term) - Only if facts exist
            facts = data.get("facts", [])
            if facts and isinstance(facts, list) and len(facts) > 0:
                slog.info(f"   [Memory] Found {len(facts)} permanent facts.")
                with self._vault_lock:
                    # Re-read inside the lock so concurrent threads see each other's writes
                    existing_facts = list(self.db.memory.get("long_term", []))
                    existing_embs = self._encode_sync(existing_facts).to('cpu') if existing_facts else None
                    for fact in facts:
                        if not isinstance(fact, str):
                            slog.warning(f"   [Memory] Skipping non-string fact (model put dict in facts[]): {str(fact)[:80]}")
                            continue
                        # Fast path: exact string match (catches identical concurrent writes)
                        if fact in existing_facts:
                            slog.info(f"   [Memory] Skipping exact duplicate: {fact[:60]}")
                            continue
                        fact_emb = self._encode_sync(fact).to('cpu')
                        if existing_embs is not None:
                            sims = torch.nn.functional.cosine_similarity(fact_emb.unsqueeze(0), existing_embs)
                            if sims.max().item() >= 0.85:
                                slog.info(f"   [Memory] Skipping near-duplicate (sim={sims.max().item():.2f}): {fact[:60]}")
                                continue
                        self.db.add_long_term_fact(fact)
                        existing_facts.append(fact)
                        if existing_embs is not None:
                            existing_embs = torch.cat([existing_embs, fact_emb.unsqueeze(0)], dim=0)
                        else:
                            existing_embs = fact_emb.unsqueeze(0)

            # 6. Self-learning — operational knowledge Clara discovered about herself
            sl = data.get("self_learning")
            if sl and isinstance(sl, dict):
                category = sl.get("category", "")
                key = sl.get("key", "").strip()
                detail = sl.get("detail", "").strip()
                confidence = float(sl.get("confidence", 0.75))
                if category in ("architecture_facts", "failure_patterns", "recovery_methods") and key and detail:
                    key_map = {
                        "architecture_facts": "summary",
                        "failure_patterns": "trigger",
                        "recovery_methods": "problem",
                    }
                    detail_map = {
                        "architecture_facts": "detail",
                        "failure_patterns": "correct_approach",
                        "recovery_methods": "method",
                    }
                    from datetime import date as _date
                    existing = self.db.memory.get("self_knowledge", {}).get(category, [])
                    new_id = f"{category[:2]}_{len(existing) + 1:03d}"
                    entry = {
                        "id": new_id,
                        key_map[category]: key,
                        detail_map[category]: detail,
                        "confidence": confidence,
                        "learned_at": str(_date.today()),
                        "status": "active",
                    }
                    if category == "failure_patterns":
                        entry["what_i_did"] = key
                    added = self.db.add_self_knowledge(category, entry)
                    if added:
                        slog.info(f"   [Memory] Self-learning saved to {category}: {key[:60]}")

        except Exception as e:
            slog.error(f"   [Memory] Consolidation failed: {e}")

    async def process_request(self, query, image_data=None, file_data=None, on_step_update=None,
                               source="user", task_context=None):
        try:
            if self._event_loop is None:
                self._event_loop = asyncio.get_running_loop()
            slog.info(f"\n=== New Mission [{source}]: {query[:80]} ===")

            total_timer = Timer()   # starts now, covers full request

            final_prompt = query
            if image_data:
                try:
                    import uuid as _uuid_mod
                    if "," in image_data:
                        image_data = image_data.split(",")[1]
                    image_path = f"temp_image_{_uuid_mod.uuid4().hex[:8]}.png"
                    with open(image_path, "wb") as f:
                        f.write(base64.b64decode(image_data))
                    abs_path = os.path.abspath(image_path)
                    final_prompt = (
                        f"{query} \n\n[SYSTEM: An image has been uploaded and saved at "
                        f"'{abs_path}'. If the user asks about it, use the 'vision' tool "
                        f"to analyze this file.]"
                    )
                except Exception as e:
                    slog.error(f"   Failed to save image: {e}")

            # Document upload (PDF / DOCX / XLSX / PPTX / etc.) — mirrors the image path
            # but routes to convert_to_markdown (MarkItDown) instead of vision. Appends to
            # final_prompt so an image + document in the same turn both keep their notes.
            if file_data:
                try:
                    import uuid as _uuid_mod
                    doc_name = file_data.get("name", "document")
                    doc_b64 = file_data.get("data", "")
                    if "," in doc_b64:
                        doc_b64 = doc_b64.split(",", 1)[1]
                    ext = os.path.splitext(doc_name)[1] or ".bin"
                    doc_path = f"temp_doc_{_uuid_mod.uuid4().hex[:8]}{ext}"
                    with open(doc_path, "wb") as f:
                        f.write(base64.b64decode(doc_b64))
                    abs_doc_path = os.path.abspath(doc_path)
                    file_uri = "file:///" + abs_doc_path.replace("\\", "/")
                    final_prompt = (
                        f"{final_prompt} \n\n[SYSTEM: A document named '{doc_name}' has been uploaded "
                        f"and saved at '{abs_doc_path}'. To read its contents, use the "
                        f"convert_to_markdown tool with uri '{file_uri}' — it returns the document "
                        f"(PDF/DOCX/XLSX/PPTX/etc.) as clean Markdown. Do NOT use read_file on it; "
                        f"binary office formats are unreadable that way.]"
                    )
                except Exception as e:
                    slog.error(f"   Failed to save uploaded document: {e}")

            # Brief 35 — retry context: this is a detached re-attempt of a task that soft-failed.
            # Tell Clara what was already achieved + why it failed, so she CONTINUES from progress
            # (idempotency — don't redo a write that succeeded) and adapts where she was blocked.
            if task_context and task_context.get("is_retry"):
                _reason = task_context.get("failure_reason", "") or "unknown"
                _partial = (task_context.get("partial_answer", "") or "")[:600]
                final_prompt = (
                    f"{final_prompt}\n\n[SYSTEM: This is a RE-ATTEMPT of a task that did NOT complete on "
                    f"the previous try. Why it failed: {_reason}. What was already achieved (do NOT redo "
                    f"this — continue from it): {_partial or 'nothing usable yet'}. Take a different "
                    f"approach where the last attempt was blocked, and finish the task.]"
                )

            # 1. Get memory context (always — feeds Interpreter)
            q_emb = await self._encode(final_prompt, convert_to_tensor=True)
            q_emb_cpu = q_emb.to('cpu')
            # Interpreter context excludes [SELF KNOWLEDGE] (it only routes — doesn't need
            # Clara's operational learnings). The block is appended to llm_context below so
            # the LLM paths still receive it. Saves ~2k tokens on every interpreter call.
            mem_context = self.db.get_smart_context(
                final_prompt, q_emb_cpu, self.episodic_embeddings,
                include_self_knowledge=False,
            )
            self_knowledge_block = self.db._self_knowledge_block()

            # 1b. Conditional archive context — same embedding, no extra MiniLM call
            archive_context = await asyncio.to_thread(
                get_archive_context, q_emb_cpu, final_prompt
            )
            if archive_context:
                slog.info(f"   [Archive] Context injected ({len(archive_context)} chars)")

            # Dynamic tool discovery — inject relevant schemas before Interpreter
            tool_context = ""
            discovered = []
            if self.tool_registry and self.tool_registry.is_ready:
                discovered = self.tool_registry.search(q_emb_cpu, top_k=8)

                # Mandatory injection: cosine similarity cannot reliably detect
                # enumeration intent (query describes target, not operation).
                # Guarantee list_directory and start_search are present for
                # any query that implies finding or listing files.
                ENUMERATION_KEYWORDS = (
                    "find", "list", "all", "search", "what files", "which files",
                    "show files", "directory", "folder", "files in", "images in",
                    "locate", "where is", "enumerate"
                )
                query_lower = final_prompt.lower()
                if any(kw in query_lower for kw in ENUMERATION_KEYWORDS):
                    discovered_names = {s.get("name") for s in discovered}
                    ld_schema = self.tool_registry.get_schema("list_directory")
                    ss_schema = self.tool_registry.get_schema("start_search")
                    if ld_schema and "list_directory" not in discovered_names:
                        discovered.append(ld_schema)
                        slog.info("   [Registry] Mandatory injection: list_directory")
                    if ss_schema and "start_search" not in discovered_names:
                        discovered.append(ss_schema)
                        slog.info("   [Registry] Mandatory injection: start_search")

                if discovered:
                    tool_context = format_tool_schemas_for_context(discovered)
                    slog.info(
                        f"   [Registry] Injecting {len(discovered)} discovered tools."
                    )
                    slog.debug(
                        f">> [DISCOVERED_TOOLS] Full context injected to Interpreter:\n{tool_context}"
                    )

            # Layer 2: active task awareness — injected by orchestrator._run_worker
            active_tasks_context = task_context.get("active_tasks_context", "") if task_context else ""
            # Layer 3: resource callback — registered by orchestrator._run_worker
            resource_callback = task_context.get("resource_callback") if task_context else None
            # Layer 3+: task_id for resource ledger (read-hash + write-lock checks)
            task_id = task_context.get("task_id") if task_context else None
            # Brief 32: harness sets return_trace to get the raw ReAct loop back for Layer-2 diagnosis.
            return_trace = bool(task_context and task_context.get("return_trace"))

            full_context = mem_context
            if archive_context:
                full_context += "\n" + archive_context
            if active_tasks_context:
                full_context += "\n" + active_tasks_context

            # tool_context goes to Interpreter only at this stage.
            # Whether it also enters [MEMORY_CONTEXT_BLOCK] is decided after routing —
            # DELIBERATE needs tool schemas in context; CHAT must never receive them
            # (bloated assistant prefix causes context-echo on short/ambiguous messages).
            interp_context = full_context + tool_context if tool_context else full_context

            # 2. Interpret
            interp_timer = Timer()
            interpreted, interp_usage = await interpret(
                content=final_prompt,
                source=source,
                context=interp_context,
                client=self.client,
                task_context=task_context,
            )
            interp_ms = interp_timer.elapsed_ms()

            # 3. Route
            mode = route(interpreted)
            slog.info(f">> [Router] Mode: {mode}")

            # Fix 1: DELIBERATE mandatory tool injection.
            # Cosine search targets the query's goal, not the operation — it misses
            # start_search and read_file whenever the query describes what to achieve
            # rather than what filesystem action to take. DELIBERATE almost always needs
            # these two tools, so guarantee their presence regardless of cosine score.
            if mode == "DELIBERATE" and self.tool_registry and self.tool_registry.is_ready:
                _discovered_names = {s.get("name") for s in discovered}
                _deliberate_extras = []
                for _tn in ("start_search", "get_more_search_results", "read_file"):
                    if _tn not in _discovered_names:
                        _schema = self.tool_registry.get_schema(_tn)
                        if _schema:
                            _deliberate_extras.append(_schema)
                            slog.info(f"   [Registry] DELIBERATE mandatory injection: {_tn}")
                if _deliberate_extras:
                    full_context += format_tool_schemas_for_context(_deliberate_extras)

            on_interpreted = task_context.get("on_interpreted") if task_context else None
            if on_interpreted:
                on_interpreted(interpreted, mode)

            # 4. Create a fresh LLM instance per request — isolates concurrent tasks
            #    Model selection by mode:
            #    CHAT:      non-reasoning — ~0.5s TTFT vs 3-8s for reasoning; no planning needed
            #    DELIBERATE: reasoning — ReAct loop quality requires it
            #    FAST:      reasoning (consolidation-only; model matters less here)
            llm = []  # plain message list — populated below with .append()

            if mode == "DELIBERATE":
                llm.append(system(self.system_prompt))
                if archive_context:
                    llm.append(system(
                        "SYSTEM ARCHITECTURE DOCUMENTATION (ground truth):\n"
                        "The following is factual documentation about how this system works. "
                        "It describes real file locations, module names, and behaviors. "
                        "If a tool result contradicts information stated here, treat the tool "
                        "result as suspect and cross-validate with an alternative approach "
                        "before accepting it.\n"
                        + archive_context
                    ))

            elif mode == "CHAT":
                llm.append(system(CHAT_SYSTEM_PROMPT))

            # FAST: no system prompt appended — llm is consolidation-only

            # CHAT must not receive tool schemas in [MEMORY_CONTEXT_BLOCK] — it has no
            # ReAct loop and never calls tools, so tool schemas only bloat the assistant
            # prefix and cause context-echo on short/ambiguous user messages.
            if mode == "CHAT":
                llm_context = full_context
            else:
                llm_context = full_context + tool_context if tool_context else full_context

            # [SELF KNOWLEDGE] goes to the LLM (all paths) but NOT the interpreter — appended
            # here rather than inside get_smart_context so only llm_context carries it.
            if self_knowledge_block:
                llm_context += self_knowledge_block

            llm.append(assistant(
                f"[MEMORY_CONTEXT_BLOCK]\n{llm_context}\n[/MEMORY_CONTEXT_BLOCK]"
            ))
            llm.append(user(f"Now, execute this request: {final_prompt}"))

            # 5. Execute
            exec_timer = Timer()
            fast_usage = None
            chat_usage = None
            deliberate_usage_list = []
            if mode == "FAST":
                final_answer, fast_usage = await self._run_fast(interpreted, on_step_update, llm, resource_callback=resource_callback, task_id=task_id)
            elif mode == "CHAT":
                final_answer, chat_usage = await self._run_chat(llm, on_step_update)
            else:
                final_answer, deliberate_usage_list = await self.run_task(on_step_update=on_step_update, llm=llm, resource_callback=resource_callback, task_id=task_id)
            exec_ms = exec_timer.elapsed_ms()

            # Brief 32 — capture the raw ReAct trace (post-routing turns) for Self-Assessment Layer 2.
            # `llm` was mutated in place by run_task/_run_fast/_run_chat, so the full loop is here now.
            # Gated on return_trace (harness only) → stashed on task_context for the worker to return.
            if return_trace and task_context is not None:
                task_context["react_trace"] = _capture_react_trace(llm)

            # Brief 35 — task completion status (DELIBERATE only). Parse + STRIP the [[TASK: …]]
            # marker so the user never sees it, and record the status on the task context so the
            # orchestrator worker can decide whether to spawn a detached retry. FAST/CHAT have no
            # marker and are always COMPLETE (a single tool / one conversational turn — nothing to retry).
            # ALWAYS strip any [[TASK: …]] marker so it never leaks — incl. on a FAST→DELIBERATE
            # escalation (the answer then comes from run_task and carries the marker even though
            # mode is still "FAST"; escalation is detected by fast_usage being a list of turn usages).
            # Honor the status for the RETRY decision ONLY when a ReAct loop actually ran; pure
            # FAST (single tool) and CHAT (one turn) have nothing to retry → always COMPLETE.
            final_answer, _mstatus, _mreason = _parse_completion(final_answer)
            ran_react = (mode == "DELIBERATE") or (mode == "FAST" and isinstance(fast_usage, list))
            completion_status = _mstatus if ran_react else "COMPLETE"
            incomplete_reason = _mreason if ran_react else ""
            _is_retry = bool(task_context.get("is_retry")) if task_context else False
            will_retry = (completion_status == "INCOMPLETE" and not _is_retry)
            if task_context is not None:
                task_context["completion_status"] = completion_status
                task_context["incomplete_reason"] = incomplete_reason

            # 6. Token aggregation
            token_usage = TokenUsage()
            if interp_usage:
                token_usage.add("interpreter", interp_usage)
            if mode == "FAST":
                if isinstance(fast_usage, list):
                    for i, u in enumerate(fast_usage):
                        token_usage.add(f"deliberate_turn_{i+1}", u)
                elif fast_usage:
                    token_usage.add("fast_execution", fast_usage)
            elif mode == "CHAT" and chat_usage:
                token_usage.add("chat", chat_usage)
            elif mode == "DELIBERATE":
                for i, u in enumerate(deliberate_usage_list or []):
                    token_usage.add(f"deliberate_turn_{i+1}", u)

            slog.info(
                f">> [Tokens] total={token_usage.total_tokens} "
                f"prompt={token_usage.prompt_tokens} "
                f"completion={token_usage.completion_tokens} "
                f"cached={token_usage.cached_tokens}"
            )

            if source == "user" and on_step_update:
                await on_step_update(
                    "",
                    type="token_usage",
                    turn_id=None,
                    extra=token_usage.to_dict()
                )

            # 7. Benchmark log (user requests only — skip system/background noise)
            if source == "user":
                log_request(
                    mode=mode,
                    tool=interpreted.get("tool"),
                    total_ms=total_timer.elapsed_ms(),
                    interp_ms=interp_ms,
                    exec_ms=exec_ms,
                    query=query,
                    token_usage=token_usage,
                )

            # memory_mode (test traffic via /query — real users default "full"):
            #   "full"      → persist normally.
            #   "ephemeral" → transient recent_exchanges only (coherence drill needs
            #                 within-dialogue recall) but NO permanent episodic/vault.
            #   "none"      → write nothing (L1-L5 harness — full isolation).
            # The 2026-06-07 confabulation leaked through PERMANENT episodic, so the drill
            # keeps its recall apparatus (recent_exchanges, reset between dialogues) while
            # never writing a persisted memory.
            memory_mode = (task_context or {}).get("memory_mode", "full")
            write_recent = memory_mode != "none"
            write_episodic = memory_mode == "full"

            # 6. Verbatim recent-conversation buffer (Topic 4, Phase 1) — user turns only.
            # Stores raw query + final answer (NOT the ReAct loop). Decoupled from
            # consolidation so a parse-failure in memorize_episode never costs a turn.
            if source == "user" and final_answer and write_recent:
                asyncio.create_task(
                    asyncio.to_thread(self.db.append_recent_exchange, query, final_answer)
                )

            # 6b. Memory consolidation — SKIP the first soft-failed attempt that will be retried.
            # Don't canonize a failure the retry may resolve (a "I couldn't" episode that resurfaces
            # becomes self-narrative ground truth — the exact Q15/Shobha class). The detached retry's
            # TERMINAL outcome consolidates instead. recent_exchanges above still captured this turn
            # (short-term coherence — she remembers she said she'd retry). Brief 35.
            if not will_retry and write_episodic:
                chat_snapshot = "\n".join([
                    f"{'User' if m['role'] == 'user' else 'Clara'}: {m['content']}"
                    for m in llm
                    if m['role'] != 'system'
                    and "[MEMORY_CONTEXT_BLOCK]" not in m['content']
                ])
                # Cap the consolidation input (B-18): an 8-turn DELIBERATE loop with 3KB
                # Glints is mostly bulk the summarizer doesn't need. Keep the head (the
                # user's request) + the tail (final answer + last Glints).
                if len(chat_snapshot) > 6000:
                    chat_snapshot = (
                        chat_snapshot[:1500]
                        + "\n…[middle of the exchange truncated for consolidation]…\n"
                        + chat_snapshot[-4500:]
                    )
                mem_task = asyncio.create_task(
                    asyncio.to_thread(self.memorize_episode, chat_snapshot, source)
                )
                def _on_memorize_done(t):
                    if not t.cancelled() and t.exception():
                        slog.error(
                            f"   [Memory] memorize_episode failed: {t.exception()}"
                        )
                mem_task.add_done_callback(_on_memorize_done)
            elif not write_episodic:
                slog.info(f"   [Memory] Skipping episodic consolidation — memory_mode={memory_mode} (test traffic).")
            else:
                slog.info("   [Memory] Skipping consolidation — first INCOMPLETE attempt, retry pending (Brief 35).")

            return final_answer

        except Exception as e:
            err_str = str(e).lower()
            slog.error(f"   [process_request] Unhandled error: {e}")
            # DeepSeek via the OpenAI SDK raises openai.* exceptions — classify on
            # message content (the old grpc/DEADLINE_EXCEEDED branches were Grok/Gemini
            # era vestiges that never matched, Brief 36 B-19).
            if "timeout" in err_str or "timed out" in err_str:
                return "The request timed out reaching the AI service. Please try again."
            if "connection" in err_str or "unreachable" in err_str or "unavailable" in err_str:
                return "The AI service is temporarily unreachable. Please try again in a moment."
            return "Something went wrong on my end. Please try again."

    async def _run_fast(self, interpreted: dict, on_step_update=None, llm=None, resource_callback=None, task_id=None) -> str:
        """
        FAST_EXECUTION: execute the Interpreter-specified tool directly,
        or respond conversationally when tool is None.
        On any failure, escalate to DELIBERATE_EXECUTION (run_task).
        """
        tool_name = interpreted.get("tool")
        args      = interpreted.get("args", {})
        intent    = interpreted.get("intent", "")

        try:
            tool_result = None
            if tool_name is not None:
                slog.info(f">> [FAST] tool={tool_name} args={str(args)[:80]}")
                if on_step_update:
                    await on_step_update(f"Running {tool_name}...", type="status")
                tool_result = await self._execute_fast_tool(tool_name, args, task_id=task_id)
                if tool_result.startswith("Error"):
                    raise ValueError(tool_result)
                # Register resource into live ledger (Layer 3)
                if resource_callback and tool_name in (_FS_WRITE_TOOLS | _FS_READ_TOOLS):
                    path = args.get("path", "")
                    if path:
                        mode = "write" if tool_name in _FS_WRITE_TOOLS else "read"
                        resource_callback(tool_name, path, mode)

            # Format response with non-reasoning model for speed
            format_messages = []
            if tool_name == "vision_tool":
                # Vision responses must describe ONLY what is visually present.
                # Passing intent (derived from full_context including memory) causes
                # memory details to bleed into the image description.
                format_messages.append(system(
                    PERSONA + "\n\n---\n\n"
                    "Describe ONLY what you can see in the image analysis result. "
                    "Do not reference session history, memory, or prior conversations. "
                    "Do not mention tool names or pipeline details. "
                    "The image analysis result is the sole source of truth."
                ))
                prompt_parts = [f"Image analysis result: {tool_result}"]
            else:
                format_messages.append(system(
                    PERSONA + "\n\n---\n\n"
                    "Format the tool result into a natural response. "
                    "Do not mention tool names or pipeline details. "
                    "Use ONLY the information present in the tool result. "
                    "Do not add, infer, or supplement from your training knowledge. "
                    "Reproduce every number, value, hash, and identifier from the tool result "
                    "EXACTLY as it appears — digit for digit. Never re-derive, round, or alter a value. "
                    "Present the tool output faithfully — you may rephrase and organize it, "
                    "but do NOT interpret, analyze, or assert anything about behavior, "
                    "correctness, existence, or runtime effects beyond what the output literally states. "
                    "For a search result, list the file names and line numbers as returned; "
                    "do NOT claim what the code does, whether it works, or whether it is a bug. "
                    "If the tool result is empty or an error, say so directly."
                ))
                prompt_parts = [f"Request: {intent}"]
                if tool_result:
                    prompt_parts.append(f"Tool result: {tool_result}")
            format_messages.append(user("\n".join(prompt_parts)))

            ds = _ds_client()
            _fast_response = await ds.chat.completions.create(
                model="deepseek-chat",
                messages=format_messages,
                stream=False,
            )
            response = _fast_response.choices[0].message.content or ""
            fast_usage = _fast_response.usage

            # Numeric-fidelity guard: format_llm is a non-reasoning relay and can
            # transpose a digit (observed: print(2**16)=65536 rendered as 65636). For
            # python_repl the tool output IS the answer, so if any number it printed is
            # not preserved in the formatted response, fall back to the raw output.
            # Targeted to numbers, so it never over-triggers on legitimate reframing
            # (e.g. a bare "True" becoming "97 is prime").
            if tool_name == "python_repl" and tool_result:
                raw = str(tool_result).strip()
                raw_nums = re.findall(r"\d[\d,]*\.?\d*", raw)
                if raw_nums:
                    resp_stripped = response.replace(",", "")
                    if any(n.replace(",", "") not in resp_stripped for n in raw_nums):
                        slog.warning("[FAST] format_llm altered a python_repl value — "
                                     "returning raw tool output for numeric fidelity.")
                        response = raw

            slog.info(f">> [FAST] Response:\n{response}")
            if on_step_update:
                await on_step_update(response, type="stream", turn_id=0)

            # Append to request-local LLM for memory consolidation
            if llm is not None:
                llm.append(assistant(response))
            return response, fast_usage

        except Exception as e:
            slog.warning(f">> [FAST] Failed ({e}). Escalating to DELIBERATE.")
            if on_step_update:
                await on_step_update("Thinking more carefully...", type="status")

            # Build failure context for DELIBERATE — tell it what was attempted,
            # what result was obtained (if any), and why it failed.
            # This prevents DELIBERATE from blindly repeating the same approach.
            failure_parts = [
                "[FAST_EXECUTION_FAILED]",
                f"Tool attempted: {tool_name}",
                f"Args: {args}",
                f"Error: {e}",
            ]
            if tool_result is not None:
                # FAST got a result but something downstream failed (e.g. format_llm)
                # Give DELIBERATE the raw data so it doesn't re-fetch
                failure_parts.append(
                    f"Partial result obtained before failure:\n{str(tool_result)[:1000]}"
                )
            failure_parts.append(
                "Reason through the failure and do not repeat the same thing. "
                "Use the partial result if available. "
                "Reason through an alternative if not."
            )
            failure_note = "\n".join(failure_parts)

            if llm is not None:
                llm.append(assistant(failure_note))

            final_answer, deliberate_usage_list = await self.run_task(on_step_update=on_step_update, llm=llm, resource_callback=resource_callback, task_id=task_id)
            return final_answer, deliberate_usage_list

    async def _run_chat(self, llm, on_step_update=None) -> tuple:
        """
        CHAT_EXECUTION: direct conversational response with no tool loop.
        Streams tokens straight to the UI. Used when Interpreter returns tool=None
        and requires_planning=False — e.g. greetings, follow-up questions, opinions.
        """
        slog.info(">> [CHAT] Direct conversational response.")
        raw = ""
        sent_len = 0
        chat_usage = None

        ds = _ds_client()
        async for chunk in await ds.chat.completions.create(
            model="deepseek-chat",
            messages=llm,
            stream=True,
            stream_options={"include_usage": True},
        ):
            if chunk.usage:
                chat_usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            token = (delta.content or "") if delta else ""
            if not token:
                continue
            raw += token
            if on_step_update:
                await on_step_update(token, type="stream", turn_id=1)
                sent_len += len(token)
                # Yield only — the old sleep(0.01) PER CHUNK added ~1-2s of pure
                # artificial latency to long CHAT answers (Brief 36 C-23).
                await asyncio.sleep(0)

        response = raw.strip()
        slog.info(f">> [CHAT] Response:\n{response}")
        llm.append(assistant(response))
        return response, chat_usage

    async def _execute_fast_tool(self, tool_name: str, args: dict, task_id: str = None) -> str:
        """Delegates to unified tool executor."""
        return await execute_fast(
            tool_name, args, self.tool_registry, self.mcp_client, task_id=task_id
        )

    # def run(self, direct_input=None, image_data=None) -> str:
        """
        Main Loop: Now Powered by Ears 👂 (Async Wrapper Version)
        """
        # --- MODE A: DIRECT INPUT (Used by API/CLI arguments) ---
        if direct_input:
            final_prompt = direct_input
            if image_data:
                print("🖼️ Image received from Interface. Processing...")
                try:
                    import uuid as _uuid_mod
                    if "," in image_data:
                        image_data = image_data.split(",")[1]

                    image_path = f"temp_image_{_uuid_mod.uuid4().hex[:8]}.png"

                    with open(image_path, "wb") as f:
                        f.write(base64.b64decode(image_data))
                        
                    abs_path = os.path.abspath(image_path)
                    final_prompt = f"{direct_input} \n\n[SYSTEM: An image has been uploaded and saved at '{abs_path}'. If the user asks about it, use the 'vision' tool to analyze this file.]"
                    
                    print(f"   Saved to: {image_path}")
                except Exception as e:
                    print(f"   ❌ Failed to save image: {e}")
            
            # ⚠️ FIX: Wrap the async call in asyncio.run()
            try:
                # If there's already an event loop running (unlikely in simple CLI, but possible), use it
                loop = asyncio.get_event_loop()
                if loop.is_running():
                     # This happens if you call run() from inside another async function (bad practice, but safety net)
                     response = loop.run_until_complete(self.process_request(final_prompt))
                else:
                     response = asyncio.run(self.process_request(final_prompt))
            except RuntimeError:
                # Fallback for complex environments (like Jupyter or some servers)
                response = asyncio.run(self.process_request(final_prompt))

            # Optional: Speak locally
            # speak(response)
            
            return response

        # --- MODE B: CLI / VOICE LOOP (Terminal) ---
        else:
            print("🎤 Voice Mode Active. (Say 'Clara' to trigger, or Ctrl+C to type)")
            
            while True:
                try:
                    # 1. Listen (Blocking - this is fine to stay sync)
                    # user_input = listen_local()
                    
                    if user_input:
                        # 2. Wake Word Check
                        if "clara" not in user_input.lower():
                            print(f"   [Ignored] Heard: '{user_input}' (No wake word)")
                            continue
                        
                        print(f"✅ Wake Word Detected: '{user_input}'")
                        
                        # 3. Process (⚠️ FIX: Wrap in asyncio.run)
                        response = asyncio.run(self.process_request(user_input))
                        
                        # 4. Speak

                        # speak(response)
                        
                except KeyboardInterrupt:
                    print("\n\n⌨️ MANUAL OVERRIDE ENGAGED")
                    try:
                        manual_input = input("   Enter command for CLARA: ")
                        if not manual_input.strip():
                            print("   (Cancelled)")
                            continue
                            
                        # Manual Input Processing (⚠️ FIX: Wrap in asyncio.run)
                        response = asyncio.run(self.process_request(manual_input))
                        # speak(response)
                        print("🎤 Returning to Voice Mode...\n")
                        
                    except KeyboardInterrupt:
                        print("\n👋 System Shutdown.")
                        break
                
                
            
    async def run_task(self, on_step_update=None, llm=None, resource_callback=None, task_id=None):
        if llm is None:
            llm = self.llm
        max_turns = 8
        llm.append(user(
            f"[SYSTEM MODE: TASK] [Turn 1/{max_turns}] Begin. "
            "Emit Thought: then Action: in the SAME response — one combined output. "
            "A Thought without an Action wastes the turn budget. "
            "Do not write Final Answer unless the task is trivially answered from memory right now."
        ))
        turn_count = 0
        thought_only_streak = 0
        deliberate_usage_list = []
        last_response_text = ""

        while turn_count < max_turns:
            turn_count += 1
            slog.info(f"[Loop {turn_count}] Thinking (Streaming)...")

            raw_content = ""
            turn_usage = None

            # 1. Open the Live Pipe (DeepSeek OpenAI-compatible streaming)
            #    Thinking mode (DELIBERATE only) reasons before emitting each ReAct turn —
            #    the CoT arrives as reasoning_content (ignored below; we read delta.content).
            ds = _ds_client()
            _think_kw = ({"reasoning_effort": DELIBERATE_REASONING_EFFORT,
                          "extra_body": {"thinking": {"type": "enabled"}}}
                         if DELIBERATE_THINKING else {})
            async for chunk in await ds.chat.completions.create(
                model="deepseek-chat",
                messages=llm,
                stream=True,
                stream_options={"include_usage": True},
                **_think_kw,
            ):
                if chunk.usage:
                    turn_usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                token = (delta.content or "") if delta else ""
                if not token:
                    continue

                raw_content += token

                # STATE B: The code.
                if "Action:" in raw_content:
                    pass

                # STATE A: The internal monologue.
                elif "Thought:" in raw_content:
                    start_idx = raw_content.find("Thought:") + 8
                    current_thought = raw_content[start_idx:].strip()
                    clean_thought = re.split(r'\n?(?:Action|Final Answer|Glint):?', current_thought)[0].strip()

                    if current_thought and on_step_update:
                        await on_step_update(clean_thought, type="thought", turn_id=turn_count)

            # Capture usage from this turn's stream
            if turn_usage:
                deliberate_usage_list.append(turn_usage)

            await asyncio.sleep(0.05)  # yield to event loop so UI updates flush before next turn

            # Matches both "Glint:" and "Glint from tool_name:" hallucination patterns
            _glint_re = re.compile(r'Glint(?:\s+from\s+[\w._-]+)?\s*:', re.IGNORECASE)
            has_glint = bool(_glint_re.search(raw_content))
            pre_glint = _glint_re.split(raw_content)[0].strip() if has_glint else None

            if has_glint and "Action:" not in raw_content:
                # Bare fabricated Glint — no Action at all
                slog.warning("   [System] Hallucinated Glint detected (no Action) — correcting.")
                # pre_glint is "" when the turn BEGAN with "Glint:" — an empty assistant
                # message confuses some chat APIs, so substitute a placeholder (C-30).
                llm.append(assistant(pre_glint or "(fabricated Glint discarded by system)"))
                llm.append(user(
                    "System: You generated a Glint without calling a tool. "
                    "Glints can ONLY come from actual tool execution. "
                    "If you need information, call the tool using Action: [...]. "
                    "Do not simulate or assume tool results. Continue with a valid Action."
                ))
                continue
            elif has_glint and "Action:" in raw_content:
                # Inline fabrication — model wrote Action then immediately invented the Glint
                # without waiting for system execution. Strip the fabricated Glint, execute real Action.
                slog.warning("   [System] Inline hallucination detected (Action + fabricated Glint in same turn) — stripping fabricated Glint.")
                response_text = pre_glint
                last_response_text = response_text
                slog.info(f"Clara (Task turn {turn_count}):\n{response_text}")
                llm.append(assistant(response_text))
                llm.append(user(
                    "System: You generated a Glint before the system executed your Action. "
                    "Glints are ONLY produced by the system after real tool execution — never by you. "
                    "The fabricated Glint was discarded. Your Action is being executed now — wait for the real Glint."
                ))
            else:
                response_text = raw_content.strip()
                last_response_text = response_text
                slog.info(f"Clara (Task turn {turn_count}):\n{response_text}")
                llm.append(assistant(response_text))

            if "Final Answer:" in response_text:
                final = response_text.split("Final Answer:")[-1].strip()
                if on_step_update:
                    await on_step_update(final, type="stream", turn_id=turn_count)
                slog.info(f">> [DELIBERATE] Final Answer:\n{final}")
                return final, deliberate_usage_list

            # Fix (2026-06-09): the model very often delivers a COMPLETE, CORRECT answer ending in
            # the [[TASK: COMPLETE/INCOMPLETE]] marker but WITHOUT the literal "Final Answer:" prefix
            # — it replaced the ceremony with the completion marker we asked for. The off-format net
            # below then wasted a whole turn (~9/run, measured) making it re-send. The marker IS the
            # completion signal: if it's present with no Action, accept the turn as the Final Answer
            # on ANY turn. (The [[TASK: …]] marker is stripped downstream by _parse_completion.)
            if _TASK_MARKER_RE.search(response_text) and "Action:" not in response_text:
                final = (response_text.split("Final Answer:")[-1].strip()
                         if "Final Answer:" in response_text else response_text.strip())
                if on_step_update:
                    await on_step_update(final, type="stream", turn_id=turn_count)
                slog.info(f">> [DELIBERATE] Final Answer (via [[TASK]] marker, no prefix):\n{final}")
                return final, deliberate_usage_list

            # Safety net: detect off-format turns — no Thought, no Action, no Final Answer.
            # Early turns (1-4): inject a corrective and continue — the model may be
            # warming up into ReAct format. Late turns (5+): implicit Final Answer.
            has_format_markers = (
                "Thought:" in response_text
                or "Action:" in response_text
                or "Final Answer:" in response_text
            )
            if not has_format_markers and response_text.strip():
                if turn_count <= 4:
                    slog.warning(
                        f"   [Loop] Off-format turn {turn_count} — correcting (early turn)."
                    )
                    llm.append(user(
                        f"[SYSTEM MODE: TASK] [Turn {turn_count}/{max_turns}]\n"
                        "System: Your last response had no ReAct markers (Thought/Action/Final Answer), "
                        "so it was NOT shown to the user — they cannot see it. "
                        "If that response already fully answered the question, re-send it now IN FULL, "
                        "prefixed with 'Final Answer:'. Do NOT write 'as above', 'already delivered', or "
                        "otherwise refer to a previous turn — the user only ever sees your Final Answer, "
                        "so it must contain the complete answer itself.\n"
                        "If you still need a tool, continue instead with:\n"
                        "Thought: <your reasoning>\n"
                        "Action: [{\"tool\": \"tool_name\", \"query\": \"...\"}]"
                    ))
                    continue
                else:
                    slog.warning(
                        f"   [Loop] Off-format turn {turn_count} — treating as implicit Final Answer."
                    )
                    slog.info(f">> [DELIBERATE] Final Answer (implicit):\n{response_text}")
                    return response_text, deliberate_usage_list

            # Fix 2: Thought-only corrective.
            # A Thought without an Action is half a ReAct cycle — the model knows what
            # it wants to do but stalls instead of acting. Inject a targeted corrective
            # that names the exact violation and the recovery path (call tool_search if
            # the needed tool is absent from [DISCOVERED_TOOLS]).
            if ("Thought:" in response_text
                    and "Action:" not in response_text
                    and "Final Answer:" not in response_text):
                thought_only_streak += 1
                slog.warning(
                    f"   [Loop] Turn {turn_count}: Thought with no Action — streak {thought_only_streak}. Correcting."
                )
                if thought_only_streak >= 3:
                    llm.append(user(
                        f"[SYSTEM MODE: TASK] [Turn {turn_count}/{max_turns}]\n"
                        f"CRITICAL: You have stalled {thought_only_streak} consecutive turns with Thought but no Action. "
                        "Stop reasoning. Pick ONE tool from [DISCOVERED_TOOLS] and execute it immediately. "
                        "Your next response must contain Action: [...] — nothing else before it. "
                        "If no tool fits, write Final Answer with whatever partial results you have."
                    ))
                else:
                    llm.append(user(
                        f"[SYSTEM MODE: TASK] [Turn {turn_count}/{max_turns}]\n"
                        "System: Your last response had a Thought but no Action followed. "
                        "Every Thought MUST be immediately followed by an Action or Final Answer "
                        "in the same response — a Thought alone wastes the turn budget. "
                        "If the tool you need is absent from [DISCOVERED_TOOLS], call tool_search "
                        "first with a semantic query to locate it. "
                        "Re-emit your Thought and follow it with an Action now."
                    ))
                continue

            # Parse all actions
            actions = self.parse_actions(response_text)

            if actions:
                thought_only_streak = 0
                # Separate valid actions from failed extractions
                valid_actions = [a for a in actions if a.get("tool")]
                failed_actions = [a for a in actions if not a.get("tool")]

                # Log failed extractions to glints
                glints = []
                for f in failed_actions:
                    msg = f"System: Action extraction failed — {f.get('error', 'unknown reason')}. Skipped."
                    glints.append(msg)
                    slog.warning(f"   [Parser] Action extraction failed: {msg}")

                # Execute all valid actions in parallel
                async def execute_tool(action: dict) -> str:
                    tool_name  = action["tool"]
                    tool_input = action["query"]
                    slog.info(f"   -> Tool: {tool_name} ({tool_input})")
                    result = await execute_deliberate(
                        tool_name,
                        tool_input,
                        self.tool_registry,
                        self.mcp_client,
                        encode_fn=self._encode,
                        task_id=task_id,
                    )
                    # Register filesystem touches into live resource ledger (Layer 3)
                    if resource_callback and tool_name in (_FS_WRITE_TOOLS | _FS_READ_TOOLS):
                        path = _extract_resource_path(tool_input)
                        if path and not result.lower().startswith(("error", "tool error")):
                            mode = "write" if tool_name in _FS_WRITE_TOOLS else "read"
                            resource_callback(tool_name, path, mode)
                    return result

                # Run all valid tools concurrently
                if valid_actions:
                    results = await asyncio.gather(*[execute_tool(a) for a in valid_actions])
                    for action, result in zip(valid_actions, results):
                        glint = f"Glint from {action['tool']}[{action['query']}]: {result}"
                        glints.append(glint)
                        slog.info(f"   -> Glint: {glint[:120]}...")
                        slog.debug(f">> [Glint] {action['tool']}:\n{result}")

                    # Format correction (non-fatal): the action was parsed from the LangChain
                    # {"action","action_input"} format. It ran — but tell Clara to use the
                    # canonical format next so she self-corrects instead of wasting turns. (2026-06-02)
                    if any(a.get("_reformatted") for a in valid_actions):
                        glints.append(
                            "System: Your last Action used the {\"action\": ..., \"action_input\": ...} "
                            "format. I parsed it this time, but going forward emit the canonical format: "
                            "Action: [{\"tool\": \"tool_name\", \"query\": \"...\"}]."
                        )
                        slog.info("   [Loop] Reformatted LangChain-style Action; advised canonical format.")

                # Feed all Glints back as a single combined message
                combined_glints = "\n".join(glints)
                llm.append(user(_turn_message(turn_count, max_turns, combined_glints)))

            else:
                llm.append(user(_turn_message(turn_count, max_turns, "System: No valid Action found. Please continue.")))

        # Fallback: exhausted all turns without a Final Answer.
        # Should be rare after final-turn wrap-up — model was told to conclude on last turn.
        slog.warning("[DELIBERATE] Turn budget exhausted without Final Answer.")
        # Brief 35: the model never got to declare a marker — auto-tag INCOMPLETE so the
        # orchestrator can spawn a retry (turn-exhaustion is the canonical retriable failure).
        _exhausted = "\n[[TASK: INCOMPLETE — turn budget exhausted before completion]]"
        if last_response_text:
            slog.info(f">> [DELIBERATE] Final Answer (turn limit — last content):\n{last_response_text}")
            return last_response_text + _exhausted, deliberate_usage_list
        return "Task incomplete — turn limit reached." + _exhausted, deliberate_usage_list