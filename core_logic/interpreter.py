import json
import os
from openai import AsyncOpenAI
from .session_logger import slog
from .llm_config import DEEPSEEK_MODEL

_DS_CLIENT: "AsyncOpenAI | None" = None


def _ds_client() -> AsyncOpenAI:
    """Shared DeepSeek async client (lazy singleton) — a fresh client per interpret()
    call discarded the httpx keep-alive pool and paid TCP+TLS setup on every request
    (Brief 36 C-1)."""
    global _DS_CLIENT
    if _DS_CLIENT is None:
        _DS_CLIENT = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )
    return _DS_CLIENT

# Tool argument schemas — tells the Interpreter what args each tool needs.
# Filesystem tools are NO LONGER listed here. They are discovered via tool_search
# or appear in [DISCOVERED_TOOLS] context block injected before this call.
TOOL_ARG_SCHEMAS = {
    # Core always-available native tools
    "web_search":        {"query": "string — search query"},
    "python_repl":       {"code": "string — python code to execute"},
    "date_time":         {"offset_days": "int — optional: days from today for a relative-date question (future +, past −); returns the COMPUTED target date+weekday", "offset_minutes": "int — optional: minutes from now for a relative-TIME question ('what time in N hours/minutes', future +, past −); returns the COMPUTED target clock time (12h+24h)"},
    "vision_tool":       {"path": "string — absolute path to image file",
                          "question": "string — what to ask about the image",
                          "paths": "list[string] — optional: multiple image paths"},
    "consult_archive":   {"query": "string — question for the archive"},
    "episodic_search":   {"query": "string — topic to find in past conversations (not the time-word)",
                          "k": "int — optional, how many results (default 5)"},
    "whatsapp_missed":   {"query": "string — optional. Absent = unread digest; a sender name = that sender's messages verbatim (and marks them read)",
                          "limit": "int — optional, max messages (default 20)",
                          "status": "string — optional: 'unread' | 'read' | 'all'",
                          "mark_read": "bool — optional: false to peek without marking read"},
    "ocr_pdf":           {"path": "string — filesystem path to the scanned/image-only PDF",
                          "max_pages": "int — optional, max pages to OCR (default 10)"},
    "query_task_status": {"keyword": "string — keyword from task goal"},
    "ambient_recall":    {"date": "string — a specific day: '2026-06-11', 'June 11', 'yesterday' (preferred for a named day)",
                          "window": "string — hours to look back, e.g. '2', '24' (used only when no date given)",
                          "query": "string — optional keyword filter (explicit app name only)"},

    # Dynamic tool discovery
    "tool_search":       {"query": "string — semantic description of capability needed"},
}

INTERPRETER_SYSTEM_PROMPT = """
You are CLARA's Interpreter. Your job is to parse any input and produce
a structured intent JSON object. You output ONLY valid JSON, no other text.

Given an input (user message, system trigger description, or task goal),
output this exact schema:

{
  "intent": "brief description of what needs to be done",
  "tool": "tool_name or null",
  "args": {},
  "confidence": 0.0-1.0,
  "uncertainty": 0.0-1.0,
  "requires_planning": true/false
}

Rules:
- tool: name of the single best tool if one tool clearly suffices, else null
- args: tool-specific args matching the schema for the chosen tool. Empty if no tool.
- confidence: how confident you are in this interpretation (1.0 = certain)
- uncertainty: how ambiguous the input is (0.0 = crystal clear)
- requires_planning: true if multi-step reasoning is needed, false if one step suffices

Routing guidance:
- Single clear tool + clear args + no dependency chain → tool set, requires_planning=false
- Compound query with multiple INDEPENDENT sub-tasks, each trivially answerable in one tool call
  with no output feeding into another → tool=null, requires_planning=false.
  Example: "What is 847 * 293? Also what is the current UTC time?" — two independent FAST
  sub-tasks (python_repl + date_time), no dependency, no ambiguity → requires_planning=false.
  Example: "What's the capital of France and what time is it?" → requires_planning=false.
  Do NOT escalate to DELIBERATE just because tool=null on a compound query.
- Vague request, multiple steps where outputs feed into next step → requires_planning=true
- Greetings, opinions, conversation → tool=null, requires_planning=false
- System triggers (health_check, memory_maintenance, etc.) → tool=null, requires_planning=false
  (these are handled by existing background workers, do not assign tools to them)
- write_file where content must be GENERATED (code, structured text, analysis, class drafts)
  rather than directly transcribed from the query → requires_planning=true, even if the path
  is clear. Generating content is always multi-step: compose first, then write.
  write_file where content IS the query (e.g. "write 'hello world' to file.txt") → requires_planning=false.
- EVIDENCE DEMANDS → requires_planning=true. If Alkama asks for PROOF, evidence, verification,
  or to substantiate a claim — "do you have proof", "verify that", "check the log/file/report",
  "show me where", "back that up" — the answer requires actually READING the cited source with
  tools. A conversational route (tool=null, no planning) cannot open files, and answering an
  evidence demand from memory produces fabricated citations (2026-07-08: a chat-routed "do you
  have proof?" invented bench-log contents). Even if the question FEELS conversational,
  evidence = tools = requires_planning=true.

web_search — use ONLY when the answer requires live or post-training data:
- Current prices, rates, scores, weather, news, stock values
- Events or releases after mid-2025 (training cutoff)
- Anything explicitly marked "latest", "current", "today", "now"

Do NOT use web_search for:
- Stable factual knowledge (capitals, historical facts, scientific concepts, definitions)
- Well-established technical knowledge (language features, algorithms, best practices)
- Questions that can be answered from training data with high confidence
- Explanations, opinions, creative tasks, reasoning, analysis

When in doubt: if the answer could have been in a textbook 5 years ago, do not search.

Filesystem path rules:
- If Alkama explicitly provides the full path → use it as-is, confidence can be high
- If you are inferring or constructing a path → set requires_planning=true, confidence ≤ 0.70
- NEVER assume directory names, filenames, or casing
- File existence must NEVER be inferred from the filename. If the query asks to read or open a specific path, requires_planning=true — the filesystem must be checked regardless of what the name implies.
- start_search searchType ENUM: valid values are "files" (by filename) or "content" (inside file). Never "file".

[DISCOVERED_TOOLS] block:
- When a [DISCOVERED_TOOLS] block is present in context, use those tool names
  and schemas EXACTLY as provided — including arg names and types
- Discovered tools take precedence for filesystem, process, and search operations
- If a filesystem/process/search task is needed and NO [DISCOVERED_TOOLS] block
  is present, assign tool="tool_search" with a semantic query describing what
  capability is needed (e.g. "read file from disk", "list directory", "run shell command")

Ambient activity rules:
- Questions about Alkama's MACHINE ACTIVITY — "what was I doing an hour ago", "which
  apps did I use last night", "when did I start working today", "how long was I idle" —
  → tool=ambient_recall, requires_planning=false (single lookup; window in hours).
  args, in priority order:
  - If the question names a SPECIFIC DAY (an explicit date, or "yesterday"/"today" — and
    an explicit date in parentheses ALWAYS wins over a relative word like "yesterday"),
    set date="<that day>" (e.g. date="June 11" or date="2026-06-11"). Do NOT also set window.
    This is preferred — it avoids hours-back math and reaches any day in the store.
  - Otherwise, for a rolling recent period, set window = hours back, computed from the
    [NOW] line ([NOW] gives the current date/time; "2 hours ago" → window "2").
  - query = ONLY a specific app/site name the user explicitly mentions ("chrome", "VS Code");
    for general "what was I doing / which apps" questions OMIT query — descriptive phrases
    like "foreground app" are not payload keywords and match nothing.
- This is DISTINCT from conversation memory: "what did WE discuss" / "do you remember
  X" stays with the memory context (tool=null). ambient_recall is for observed
  activity, not dialogue.

Personal memory rules:
- For questions about people Alkama has mentioned, past conversations, things
  you discussed previously, or anything phrased as "do you remember X" or
  "did I tell you about X" → answer from [MEMORY_CONTEXT_BLOCK] directly.
  Set tool=null, requires_planning=false.
- EXCEPTION — episodic_search: when the question is an explicit TEMPORAL-LOCATOR
  or exhaustive recall over past conversations that the injected context may not
  cover — "WHEN did I (first) mention/say X", "have I EVER talked about X",
  "the first/last time I brought up X", "search/look through my memory for X" →
  tool=episodic_search, args {"query": "<the topic, not the time-word>"},
  requires_planning=false. It returns matching past interactions WITH timestamps,
  so the answer can give the date. Use the TOPIC as the query ("the gym", "Shobha",
  "the job offer") — never "when" alone. Casual "do you remember X" that the
  context already answers stays tool=null (don't pay a tool call for it).
- WhatsApp held-message recall: "what did I miss on WhatsApp", "any whatsapp
  messages (today)", "who messaged me on whatsapp" → tool=whatsapp_missed (no
  query = unread digest), requires_planning=false. A SPECIFIC sender — "what did
  Yash say on whatsapp", "show me <name>'s messages" → tool=whatsapp_missed with
  query=<sender> (returns their messages verbatim and marks them read). "mark X
  read" → whatsapp_missed query=<sender>. Read-only; NEVER for sending anything.
- Relative-date questions (Brief 50): "what's the date / weekday N days from now",
  "N days ago", "the date X days before/after today" → tool=date_time with
  offset_days=±N (future +, past −), requires_planning=false. The tool returns the
  COMPUTED target date + weekday — so Clara never hand-computes calendar arithmetic
  (she reliably errs on month-boundary rollovers).
- Relative-TIME questions (G25, 2026-08-01): "what time will it be in N hours/minutes",
  "N minutes from now", "the time X hours before/after now" → tool=date_time with
  offset_minutes=±N (future +, past −), requires_planning=false. The tool returns the
  COMPUTED target clock time (12h+24h) — so Clara never hand-adds minutes. Convert hours
  to minutes ("6 hours 53 minutes from now" → offset_minutes=413). Was previously routed
  as a plain CHAT answer, which let a degraded turn emit a bogus tool-call (07-31e Q22).
- COMPUTATION ALWAYS USES A TOOL, NEVER CHAT (2026-08-01): any question that asks to COMPUTE
  or CALCULATE a value — arithmetic, a sum/product/prime-factor, a statistic, a date or time
  offset, a count — routes to a tool with requires_planning=false: python_repl for
  arithmetic/math, date_time for date/time offsets. tool=null (CHAT) is for conversational and
  knowledge answers ONLY — never make CHAT hand-compute a value (it will guess, or emit a bogus
  tool-call it cannot run, the 07-31e time-delta bug). A genuinely multi-STEP computation
  (compute X, then compute Y from it) → requires_planning=true (DELIBERATE). Note: discussing or
  explaining numbers is NOT computing them — "explain tail latency (p99)" stays CHAT.
- Do NOT use consult_archive for personal memory lookups.
  consult_archive searches indexed documentation (CLAUDE.md, ROADMAP.md,
  resume) — it does not contain conversation history.
- If a casual recall has no match in the injected context, say so directly — but a
  "when did I ever…" locator should use episodic_search before concluding absence.

Follow-up resolution:
If the query is short (under 6 words), uses demonstrative references without
specifying what they refer to ("these", "that", "it", "the same", "in india",
"over there"), or clearly lacks a subject noun — treat it as a continuation of
the most recent exchange in [RELEVANT PAST INTERACTIONS] before interpreting
as a new topic.
Examples:
- "In india clara" after a watch price query → interpret as asking for India
  prices of the watches just discussed, not a new topic about India
- "What's the major difference in these versions?" with no prior context about
  versions → check recent interactions first; if Porsche was just discussed,
  "these versions" means Porsche variants
- "How much is it there?" → refer to the most recent item and location discussed
Do NOT default to CLARA architecture or project topics when the recent
conversation was about something else entirely.

CRITICAL — filesystem read requests:
"Read X and tell me what it does" → requires_planning=true, even if X sounds like it doesn't exist.
The filesystem must be checked. You cannot know from the filename whether a file exists.
Example:
- Input: "Read core_logic/nonexistent_module.py and tell me what it does, then check agent.py for imports"
- WRONG: {"tool": null, "requires_planning": false, "confidence": 1.0}
- CORRECT: {"tool": "read_file", "requires_planning": true, "confidence": 0.95}
  Reason: file existence is a filesystem fact, not inferable from the name.

CRITICAL — CLARA architecture self-knowledge:
Any question about CLARA's own modules, file locations, execution modes, class names,
behaviors, or implementation details → requires_planning=true, tool=null.
These questions MUST go to DELIBERATE so Clara can search CLAUDE.md and verify from source.
Parametric knowledge of CLARA's own architecture is unreliable — never route to CHAT.
Examples that must route DELIBERATE:
- "What are the three execution modes in CLARA?" → requires_planning=true
- "Which file handles conflict arbitration?" → requires_planning=true
- "What does ResourceLedger do?" → requires_planning=true
- "How does memory consolidation work?" → requires_planning=true
- "Where is the orchestrator defined?" → requires_planning=true
Signal words: "in CLARA", "which file", "what module", "how does CLARA", "where is X handled",
"what does X do in the system", execution mode names, module/class names from the codebase.

CONCRETE CODE REFERENCE (the load-bearing case — do NOT route to CHAT):
Even when a question LOOKS answerable from general programming knowledge, if it names a SPECIFIC
file path (e.g. core_logic/crud.py), a codebase identifier (a function/method/class/constant such as
_save_memory, _vault_lock, MAX_ATTEMPTS, _TASK_MARKER_RE), OR asks for a CONCRETE code detail — an
exact value, a line number, a verbatim quote, a function signature, an exact prefix/argument string —
set requires_planning=true (DELIBERATE). Answering these from parametric memory FABRICATES the
specifics (wrong line, wrong prefix, wrong signature, stale value) even when the general concept is
right. The file MUST be read, not recalled.
Examples that MUST route DELIBERATE, never CHAT:
- "core_logic/crud.py's _save_memory: name the stdlib function it uses and the exact prefix" → requires_planning=true
- "quote verbatim the line where _vault_lock is created" → requires_planning=true
- "what is MAX_ATTEMPTS and on exactly which line is it defined?" → requires_planning=true
- "give the def line of _number_read_file_lines with its parameter names" → requires_planning=true
Trigger: a *.py path, a codebase identifier, or any request for an exact value / line / quote / signature.

CRITICAL — completeness enumeration:
Queries that ask to find or list EVERY occurrence, ALL matches, EACH place a string/pattern
appears across files, or to enumerate a result set where missing a single item is a failure
→ requires_planning=true (DELIBERATE), even if the tool is obvious (start_search).
Rationale: the FAST path's formatter summarizes lists and silently drops items (it once
reported "9 across 3 files" for a search whose true result was 15 across 4). Only the ReAct
loop preserves the full set, because its Final Answer is composed by the reasoning model
(which sees the raw results and is bound by the completeness check), not by a one-shot relay.
Examples that must route DELIBERATE:
- "Search for every place in core_logic/ where 'memorize_episode' appears, list each file+line"
  → requires_planning=true
- "List all functions that call run_task" → requires_planning=true
- "Find every file that imports torch" → requires_planning=true
This does NOT apply to single-value lookups: "does file X exist", "search the web for today's
gold price", "find the path of agent.py" → those stay FAST (the answer is one value, not a set).
"""


async def interpret(
    content: str,
    source: str,
    context: str,
    client,
    task_context: dict = None,
) -> dict:
    """
    Interpret any input and return a structured intent dict.

    Args:
        content:      The raw input text (user message, task goal, trigger description)
        source:       "user" | "system" | "worker"
        context:      Relevant memory context string (from get_smart_context)
        client:       unused (kept for call-site compatibility)
        task_context: Optional task context dict — may contain failure_summary for retries

    Returns dict with keys: intent, tool, args, confidence, uncertainty,
    requires_planning. Returns safe fallback on any failure.
    """
    FALLBACK = {
        "intent": content[:100],
        "tool": None,
        "args": {},
        "confidence": 0.5,
        "uncertainty": 0.5,
        "requires_planning": True,
    }

    try:
        messages = []
        messages.append({"role": "system", "content": INTERPRETER_SYSTEM_PROMPT})

        tool_schema_str = json.dumps(TOOL_ARG_SCHEMAS, indent=2)

        failure_note = ""
        if task_context and "failure_summary" in task_context:
            fs = task_context["failure_summary"]
            failure_note = (
                f"\nPREVIOUS ATTEMPT FAILED:\n"
                f"Reason: {fs.get('reason', '')}\n"
                f"Attempt: {fs.get('attempt', 1)}\n"
                f"Adjust your approach — avoid the previous failure pattern.\n"
            )

        prompt = (
            f"Source: {source}\n"
            f"Input: {content}\n"
            + failure_note +
            f"\nAvailable tools and their arg schemas:\n{tool_schema_str}\n\n"
            f"Relevant context:\n{context}\n\n"
            "Output ONLY the JSON object."
        )
        messages.append({"role": "user", "content": prompt})
        ds = _ds_client()
        _interp_response = await ds.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=messages,
            stream=False,
        )
        raw = _interp_response.choices[0].message.content or ""
        interp_usage = _interp_response.usage
        slog.info(f">> [Interpreter] Raw output:\n{raw}")

        # Strip markdown fences if present
        clean = raw.strip().lstrip("\ufeff")
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()

        result = json.loads(clean)

        # Validate required keys
        for key in ("intent", "tool", "args", "confidence",
                    "uncertainty", "requires_planning"):
            if key not in result:
                slog.warning(
                    f">> [Interpreter] Missing key '{key}' — using fallback"
                )
                return FALLBACK, None

        # Normalize a stringified null tool → real None. The model sometimes emits
        # "tool": "null" (quoted) instead of JSON null; left as the string "null" it
        # passes route()'s `tool is not None` check, mis-routes to FAST, and fails with
        # "Tool 'null' not found" before a wasteful DELIBERATE escalation. (2026-06-02)
        if isinstance(result.get("tool"), str) and result["tool"].strip().lower() in ("null", "none", ""):
            result["tool"] = None

        slog.info(
            f">> [Interpreter] Parsed → tool={result['tool']} | "
            f"confidence={result['confidence']:.2f} | "
            f"uncertainty={result['uncertainty']:.2f} | "
            f"requires_planning={result['requires_planning']} | "
            f"intent={result['intent'][:80]}"
        )
        return result, interp_usage

    except Exception as e:
        slog.error(f">> [Interpreter] Failed: {e}. Using fallback.")
        return FALLBACK, None
