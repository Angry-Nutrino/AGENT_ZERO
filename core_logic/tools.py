import sys
from io import StringIO
from datetime import datetime
from tavily import TavilyClient
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from .session_logger import slog
import os

load_dotenv()  # Load once at module level


RAG_ENGINE= None
current_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH=os.path.join(current_dir, "knowledge_base")

# Pre-loading rag for faster inference.
slog.info("   [Archive] Pre-loading RAG Engine for instant access...")
_embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}  # RAG on CPU — VRAM reserved for agent MiniLM + Phi3
)

if os.path.exists(DB_PATH):
    RAG_ENGINE = FAISS.load_local(
        DB_PATH,
        _embeddings,
        allow_dangerous_deserialization=True
    )
    slog.info("   [Archive] RAG Engine is Hot.")
else:
    RAG_ENGINE = None
    slog.info("   [Archive] DB Not found. RAG will be disabled.")


def reload_rag_engine() -> bool:
    """
    Reload the FAISS index from disk into the global RAG_ENGINE.
    Called after a successful rag_rebuild background task.
    Returns True on success, False on failure.
    """
    global RAG_ENGINE
    try:
        if os.path.exists(DB_PATH):
            RAG_ENGINE = FAISS.load_local(
                DB_PATH,
                _embeddings,
                allow_dangerous_deserialization=True,
            )
            slog.info("   [Archive] RAG Engine reloaded from disk.")
            return True
        else:
            slog.warning("   [Archive] DB not found during reload.")
            return False
    except Exception as e:
        slog.error(f"   [Archive] Reload failed: {e}")
        return False


def get_archive_context(q_emb_cpu, query: str, threshold: float = 0.35) -> str:
    """
    Relevance-gated archive lookup using a pre-computed MiniLM embedding.
    q_emb_cpu: CPU-side torch tensor (384-dim) from agent._encode().
    threshold: minimum cosine similarity to inject (0.35 = reasonably relevant).
    Returns a formatted [ARCHIVE CONTEXT] string, or "" if nothing relevant found.

    Uses the FAISS index directly with a numpy vector — avoids the langchain
    similarity_search() path which requires re-encoding the query string.
    """
    global RAG_ENGINE
    if RAG_ENGINE is None:
        return ""

    try:
        import numpy as np
        # Convert torch tensor → numpy float32 array for FAISS
        q_np = q_emb_cpu.numpy().astype("float32").reshape(1, -1)

        # FAISS inner product search (index is L2-normalised → equivalent to cosine)
        scores, indices = RAG_ENGINE.index.search(q_np, k=3)

        # scores[0] are inner-product scores; for normalised vectors, range is [-1, 1]
        best_score = float(scores[0][0]) if len(scores[0]) > 0 else 0.0
        if best_score < threshold:
            return ""

        # Retrieve the actual documents for the top indices
        chunks = []
        id_map = RAG_ENGINE.index_to_docstore_id
        for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
            if idx == -1 or float(score) < threshold:
                continue
            doc_id = id_map.get(int(idx))
            if doc_id is None:
                continue
            doc = RAG_ENGINE.docstore._dict.get(doc_id)
            if doc:
                chunks.append(doc.page_content.strip())

        if not chunks:
            return ""

        block = "\n[ARCHIVE CONTEXT]:\n"
        for i, chunk in enumerate(chunks):
            block += f"[{i+1}] {chunk}\n"
        block += "[END ARCHIVE]\n"
        return block

    except Exception as e:
        from .session_logger import slog
        slog.warning(f"   [Archive] Context injection failed: {e}")
        return ""


def run_python_code(code: str) -> str:
    # Output capture is SCOPED via a print-override in the exec namespace — the old
    # implementation swapped the process-global sys.stdout, so two concurrent
    # python_repl calls (parallel Actions run via asyncio.gather in worker threads)
    # could steal/interleave each other's output (Brief 36 D-15). Code that writes
    # via sys.stdout.write directly bypasses capture — a known, accepted trade-off
    # (model code overwhelmingly uses print()).
    buf = StringIO()

    def _capture_print(*args, sep=" ", end="\n", **kwargs):
        buf.write(sep.join(str(a) for a in args) + end)

    try:
        # Inject a UTF-8-defaulting open() so model code that omits encoding= does
        # not hit Windows cp1252 charmap errors on UTF-8 files (e.g. memory.json
        # contains multibyte chars). This removes the TRIGGER of the Q08-class
        # cascade: on Windows bare open() defaults to cp1252 → 'charmap' decode
        # error → FAST escalates → the model embeds fragile multi-line code in a
        # JSON Action → malformed JSON. A working open() short-circuits all of it.
        import builtins as _bi

        def _utf8_open(*a, **kw):
            mode = a[1] if len(a) > 1 else kw.get("mode", "r")
            if "b" not in mode and "encoding" not in kw:
                kw["encoding"] = "utf-8"
            return _bi.open(*a, **kw)

        # A single namespace dict also serves as BOTH globals and locals. With bare
        # exec(code), top-level assignments land in the function's locals while
        # comprehensions resolve free variables against globals — so multiline code
        # like `content = open(...).read(); [x for x in content]` fails with
        # "name 'content' is not defined". A shared module-level namespace fixes that.
        exec_ns: dict = {"open": _utf8_open, "print": _capture_print}
        exec(code, exec_ns)
        output = buf.getvalue()

        if not output.strip():
            output = "Code executed successfully with no output. Check your format and checkcode for return values."

    except Exception as e:
        output = f"Error: {str(e)}"

    return output

def web_search(query: str) -> dict:
    try:
        ap = os.getenv("tavily_api")
        client = TavilyClient(ap)
        response = client.search(
            query=query,
            include_answer="advanced",
            search_depth="advanced",
            max_results=2
        )
        return response
    except Exception as e:
        return {"answer": f"Error doing web_search: {e}", "results": []}
    
def get_time_date() -> str:
    return str(datetime.now())

def consult_archive(query: str) -> str:
    global RAG_ENGINE
    global DB_PATH
    
    if RAG_ENGINE is None:
        if os.path.exists(DB_PATH):
            slog.info("   [Archive] Loading Vector Database into RAM...")
            embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
            RAG_ENGINE = FAISS.load_local(
                DB_PATH, 
                embeddings, 
                allow_dangerous_deserialization=True 
            )
        else:
            return "Error: Knowledge base not found. Run core_logic/rag_db_builder.py (or restart the backend) to build it."
    
    slog.debug(f"   [Archive] Searching for: '{query}'")
    results = RAG_ENGINE.similarity_search(query, k=4)
    
    # Pro-tip: Join with a separator so the LLM knows where one chunk ends and another begins
    return "\n---\n".join([doc.page_content for doc in results])


# response_web_search = web_search("What is the price of iphone 15 pro max in INR?")
# print("Web Search Result:", response_web_search)


# NOTE (Brief 36 D-9/D-12, removed 2026-06-10): the dead fs_* quartet
# (fs_read_file / fs_list_directory / fs_write_file / fs_run_command — replaced by
# Desktop Commander tools long ago, nothing imported them) and the dead pre-Gemini
# vision helpers (_pick_detail / _compress_image — the Gemini path below does its own
# inline thumbnail+JPEG) were deleted. Git history preserves them.

import pathlib


# ── Vision Tool (Gemini 2.5 Flash; function name is legacy from the Grok era) ──

import base64


def analyze_image_grok(
    client,
    path: str,
    question: str = "Describe what you see in this image in detail.",
    paths=None,
) -> str:
    """
    Analyze image(s) using Gemini 2.5 Flash (google-genai SDK).
    'client' parameter kept for API compatibility but unused.
    """
    import io
    from google import genai
    from google.genai import types
    from PIL import Image

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return "Error: GEMINI_API_KEY not set in .env"

    image_paths = []
    if path:
        image_paths.append(path)
    if paths:
        image_paths += [p for p in paths if p and p != path]

    parts = []
    for img_path in image_paths:
        try:
            p = pathlib.Path(img_path.strip().strip('"').strip("'"))
            if not p.exists():
                return f"Error: Image not found at path: {img_path}"
            with Image.open(p) as img:
                if img.width > 1280 or img.height > 1280:
                    img.thumbnail((1280, 1280), Image.LANCZOS)
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=85)
                parts.append(types.Part.from_bytes(
                    data=buf.getvalue(),
                    mime_type="image/jpeg",
                ))
        except Exception as e:
            return f"Error loading image {img_path}: {e}"

    if not parts:
        return "Error: No valid images provided"

    parts.append(question)

    # Free-tier gemini-2.5-flash throws transient 503 UNAVAILABLE ("high demand")
    # fairly often — observed on the very first wired-up call (2026-06-11). Retry
    # a couple of times with backoff before reporting failure; a 503 surfaced to
    # the ReAct loop reads like a broken tool when it's a 15-second blip.
    import time as _time
    gc = genai.Client(api_key=gemini_key)
    last_err = None
    for attempt in range(3):
        try:
            response = gc.models.generate_content(
                model="gemini-2.5-flash",
                contents=parts,
            )
            return response.text
        except Exception as e:
            last_err = e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                _time.sleep(8 * (attempt + 1))
                continue
            return f"Vision error: {e}"
    return f"Vision error after retries: {last_err}"


def analyze_images_grok(
    client,
    paths: list,
    question: str = "Describe what you see in these images.",
    detail: str = "high",
) -> str:
    """Wrapper — delegates to analyze_image_grok with multiple paths."""
    return analyze_image_grok(client, path=paths[0] if paths else "", question=question, paths=paths[1:] if len(paths) > 1 else None)


# ── Task Status Tool ───────────────────────────────────────────────────────

# Injected at startup by api.py — allows query_task_status to access
# the live TaskGraph without circular imports.
_task_graph_ref = None

def set_task_graph(tg) -> None:
    """Called once by api.py after TaskGraph is created."""
    global _task_graph_ref
    _task_graph_ref = tg


def query_task_status(keyword: str) -> str:
    """
    Search the TaskGraph for tasks whose goal contains the keyword.
    Returns a formatted status report for all matching tasks.
    Used by CLARA to answer questions like "why hasn't X finished yet?"
    """
    if _task_graph_ref is None:
        return "Error: Task graph not available."

    keyword_lower = keyword.lower().strip()

    # Search non-terminal tasks in memory
    all_tasks = list(_task_graph_ref._tasks.values())

    # Also search terminal tasks in SQLite for recent history
    try:
        import sqlite3
        conn = sqlite3.connect(_task_graph_ref._db_path)
        rows = conn.execute(
            "SELECT id, goal, state, priority, origin, context, last_updated "
            "FROM tasks ORDER BY last_updated DESC LIMIT 50"
        ).fetchall()
        conn.close()
    except Exception:
        rows = []

    # Build a unified search set — in-memory tasks take precedence
    seen_ids = {t.id for t in all_tasks}
    import json as _json

    for row in rows:
        if row[0] not in seen_ids:
            try:
                all_tasks.append(type('T', (), {
                    'id': row[0],
                    'goal': row[1],
                    'state': row[2],
                    'priority': row[3],
                    'origin': row[4],
                    'context': _json.loads(row[5]) if row[5] else {},
                    'last_updated': row[6],
                    'dependencies': [],
                })())
            except Exception:
                pass

    # Filter by keyword
    matches = [
        t for t in all_tasks
        if keyword_lower in t.goal.lower()
    ]

    if not matches:
        return f"No tasks found matching '{keyword}'."

    lines = [f"Task status report for '{keyword}':\n"]
    for t in matches[:5]:  # cap at 5 results
        checkpoint = t.context.get("checkpoint", {})
        reason     = checkpoint.get("reason", "")
        paused_at  = checkpoint.get("interrupted_at", "")

        status_line = f"• [{t.state.upper()}] {t.goal[:80]}"
        if t.state == "paused" and reason:
            status_line += f"\n  ↳ Paused: {reason}"
            if paused_at:
                status_line += f" at {paused_at[:19]}"
        elif t.state == "pending" and t.dependencies:
            status_line += f"\n  ↳ Waiting on: {len(t.dependencies)} dependency/ies"
        elif t.state == "failed":
            err = t.context.get("error", "unknown error")
            status_line += f"\n  ↳ Failed: {err[:100]}"
        elif t.state == "invalidated":
            status_line += "\n  ↳ Invalidated (resource conflict or superseded)"

        status_line += f"\n  ↳ Priority: {t.priority:.1f} | Origin: {t.origin}"
        lines.append(status_line)

    return "\n".join(lines)