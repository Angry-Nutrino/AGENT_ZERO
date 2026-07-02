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
    
def get_time_date(offset_days: int = 0) -> str:
    """Rich temporal grounding (upgraded 2026-06-12 — the old version returned a bare
    datetime repr). Gives Clara everything needed to resolve relative time: weekday,
    both clock formats, timezone, part of day, and yesterday/tomorrow anchors.

    `offset_days` (Brief 50): when non-zero, appends a DETERMINISTICALLY-computed target line for
    'N days from now / N days ago' questions — so Clara never hand-computes a calendar date/weekday
    (she reliably errs on month-boundary rollovers; +10d failed 06-24m/06-25m). Sign: future +, past −."""
    now = datetime.now().astimezone()
    from datetime import timedelta
    yest, tom = now - timedelta(days=1), now + timedelta(days=1)
    hour = now.hour
    part = ("early morning" if hour < 6 else "morning" if hour < 12
            else "afternoon" if hour < 17 else "evening" if hour < 21 else "night")
    tz = now.strftime("%z")
    tz_fmt = f"UTC{tz[:3]}:{tz[3:]}" if tz else "local"
    out = (
        f"Date: {now.strftime('%A, %d %B %Y')} ({now.strftime('%Y-%m-%d')})\n"
        f"Time: {now.strftime('%H:%M:%S')} (24h) / {now.strftime('%I:%M:%S %p').lstrip('0')} (12h) — {part}\n"
        f"Timezone: {tz_fmt} (IST)\n"
        f"Week {now.isocalendar()[1]} of {now.year}, day {now.timetuple().tm_yday} of the year\n"
        f"Yesterday was {yest.strftime('%A, %Y-%m-%d')}; tomorrow is {tom.strftime('%A, %Y-%m-%d')}"
    )
    try:
        n = int(offset_days)
    except (TypeError, ValueError):
        n = 0
    if n:
        tgt = now + timedelta(days=n)
        rel = f"{abs(n)} day(s) {'from today' if n > 0 else 'ago'}"
        out += (f"\n{rel.capitalize()}: {tgt.strftime('%A, %d %B %Y')} "
                f"({tgt.strftime('%Y-%m-%d')})  (computed -- do not recompute by hand)")
    return out

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


_OCR_PROMPT = (
    "Transcribe ALL text visible in this image VERBATIM, preserving reading order and line breaks. "
    "Output only the transcribed text — no commentary, no description. If there is no text, output '(no text)'."
)


def ocr_pdf(path: str, max_pages: int = 10, question: str = "") -> str:
    """
    OCR a SCANNED / image-only PDF (Brief 36 F.6 / Y2): rasterize each page and transcribe it via the
    Gemini vision tool. FALLBACK ONLY — for PDFs with a real text layer, convert_to_markdown (markitdown)
    is faster and more accurate; this exists for scans markitdown returns empty/garbage on. If the PDF
    already has a substantial text layer, the text is extracted directly (cheap) instead of OCR'd.
    Read-only; never raises (returns an error string). Page count is bounded by max_pages.
    """
    try:
        import fitz  # PyMuPDF — self-contained wheel, no onnxruntime/magika (avoids the markitdown footgun)
    except Exception:
        return "Error: PyMuPDF (fitz) is not installed — cannot OCR PDFs."
    p = pathlib.Path(str(path).strip().strip('"').strip("'"))
    if not p.exists():
        return f"Error: PDF not found at path: {path}"
    try:
        max_pages = max(1, min(int(max_pages or 10), 25))
    except (TypeError, ValueError):
        max_pages = 10
    try:
        doc = fitz.open(str(p))
    except Exception as e:
        return f"Error: could not open PDF: {e}"
    try:
        n_pages = doc.page_count
        if n_pages == 0:
            return "Error: PDF has no pages."
        # If the PDF already has a real text layer, skip OCR — cheaper and more accurate.
        existing = "".join(doc[i].get_text() for i in range(min(n_pages, max_pages)))
        if len(existing.strip()) >= 100:
            return (f"[PDF has a text layer — extracted directly, no OCR needed ({n_pages} page(s))]\n"
                    + existing.strip())
        # Scanned / image-only → rasterize + OCR each page via Gemini.
        import tempfile
        out = []
        pages_to_do = min(n_pages, max_pages)
        for i in range(pages_to_do):
            try:
                pix = doc[i].get_pixmap(dpi=200)
                fd, tmp = tempfile.mkstemp(prefix=f"ocr_pg{i + 1}_", suffix=".png")
                os.close(fd)
                try:
                    pix.save(tmp)
                    text = analyze_image_grok(None, path=tmp, question=question or _OCR_PROMPT)
                finally:
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            except Exception as e:
                text = f"(page {i + 1} OCR error: {e})"
            out.append(f"--- Page {i + 1} ---\n{str(text).strip()}")
        note = "" if n_pages <= max_pages else f"\n\n[Note: OCR'd the first {max_pages} of {n_pages} pages.]"
        return "\n\n".join(out) + note
    except Exception as e:
        # Honor the "never raises" contract: get_text()/page_count can raise on an encrypted or
        # corrupt PDF (a realistic weird-scan input) — return an error string, don't propagate.
        return f"Error: OCR failed while reading the PDF: {e}"
    finally:
        doc.close()


# ── Ambient Recall (BRIEF_39 A1) ────────────────────────────────────────────

def ambient_recall(window: str = "24", query: str = "", date: str = "") -> str:
    """Grounded recall over the A0 watcher's observation store (read-only).
    date:   a specific day to recall — '2026-06-11', 'June 11', 'yesterday'. PREFERRED
            for "what was I doing on <day>" (no error-prone hours-back math). Overrides window.
    window: hours to look back ('24', '2', '48') when no date is given.
    query:  optional keyword filter (an explicit app/site name only)."""
    from .ambient import recall as _recall, _parse_date_anchor
    d = str(date or "").strip()
    w = str(window or "24").lower().strip()
    # If no explicit date but `window` is actually a date phrase ('june 11', 'yesterday',
    # an ISO date), route it to the date anchor instead of misparsing it as hours.
    if not d and _parse_date_anchor(w):
        d = w
    if d:
        return _recall(query=query or "", date=d)
    import re as _re
    mnum = _re.search(r"[\d.]+", w)
    hours = float(mnum.group(0)) if mnum else 24.0
    if "day" in w:
        hours *= 24
    return _recall(window_hours=hours, query=query or "")


# ── Task Status Tool ───────────────────────────────────────────────────────

# Injected at startup by api.py — allows query_task_status to access
# the live TaskGraph without circular imports.
_task_graph_ref = None

def set_task_graph(tg) -> None:
    """Called once by api.py after TaskGraph is created."""
    global _task_graph_ref
    _task_graph_ref = tg


# Injected at startup by api.py — the live Clara_Agent, so episodic_search can read
# the in-RAM episodic_log + episodic_embeddings and reuse the agent's encoder.
_agent_ref = None

def set_agent_ref(agent) -> None:
    """Called once by api.py after Clara_Agent is created."""
    global _agent_ref
    _agent_ref = agent


def whatsapp_missed(query: str = "", limit: int = 20, status: str = "", mark_read=None) -> str:
    """
    Read-only retrieval over the HELD WhatsApp archive (non-priority senders; Shobha is surfaced
    straight into the chat and is never held). TWO behaviours, by whether you name a sender:
      • No `query` → a DIGEST of UNREAD held messages ("what did I miss on WhatsApp"): grouped by
        sender, counts + a short preview. Marks NOTHING read (a glance is not engagement).
      • A sender/text in `query` → that sender's messages VERBATIM (the exact-fetch drill-down,
        "what did Yash say"). This IS engagement, so the shown messages flip unread→read
        (engage-to-read). They are never removed — ask again any time (they return under status='all').
    `status`: 'unread' | 'read' | 'all' (default: unread for the digest, all for a drill-down so a
    re-ask still returns already-read messages). `mark_read`: override the auto engage-to-read
    (True = mark shown messages read even on a digest; False = peek without marking). Read is a LABEL,
    never a delete. Brief 49.
    """
    try:
        from .conversations import read_whatsapp_held, mark_whatsapp_read
    except ImportError:
        from conversations import read_whatsapp_held, mark_whatsapp_read
    try:
        limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        limit = 20

    q = (query or "").lower().strip()
    drilldown = bool(q)
    # status default depends on intent: a drill-down wants ALL of that sender's messages (so a re-ask
    # after engage-to-read still returns them); the digest wants only what's NEW (unread).
    st = (status or "").lower().strip()
    if st not in ("unread", "read", "all"):
        st = "all" if drilldown else "unread"
    status_filter = None if st == "all" else st

    rows = read_whatsapp_held(limit=0, status=status_filter)   # whole filtered archive, not the tail
    if drilldown:
        rows = [r for r in rows
                if q in str(r.get("sender", "")).lower() or q in str(r.get("text", "")).lower()]
    rows = rows[-limit:]

    if not rows:
        if drilldown:
            return f"No held WhatsApp messages match {query!r}."
        return ("Nothing new on WhatsApp — you're caught up. (Priority senders like Shobha come straight "
                "to the chat; ask for any sender by name to see their earlier messages, read or not.)")

    # engage-to-read: a drill-down marks EXACTLY the shown rows read (precise, by id), unless overridden.
    do_mark = mark_read if mark_read is not None else drilldown
    marked = 0
    if do_mark:
        ids = [r.get("id") for r in rows if r.get("id") and r.get("status") != "read"]
        if ids:
            marked = mark_whatsapp_read(ids=ids)

    from collections import OrderedDict
    by_sender = OrderedDict()
    for r in rows:
        by_sender.setdefault(str(r.get("sender", "unknown")), []).append(r)

    if drilldown:
        # VERBATIM: every matched message, full text, no truncation.
        head = f"{len(rows)} WhatsApp message(s) from {len(by_sender)} sender(s)"
        head += " (now marked read)" if marked else ""
        lines = [head + ":"]
        for sender, msgs in by_sender.items():
            lines.append(f"\n**{sender}** ({len(msgs)}):")
            for m in msgs:
                ts = str(m.get("ts", ""))[:16].replace("T", " ") or "undated"
                body = " ".join(str(m.get("text", "")).split())
                lines.append(f"  [{ts}] {body}")
        return "\n".join(lines)

    # DIGEST: unread overview, grouped, short preview, last 5 per sender.
    lines = [f"{len(rows)} unread held WhatsApp message(s) from {len(by_sender)} sender(s) "
             f"(priority senders go straight to the chat). Ask for a sender by name to read theirs:"]
    for sender, msgs in by_sender.items():
        lines.append(f"\n**{sender}** ({len(msgs)}):")
        for m in msgs[-5:]:
            ts = str(m.get("ts", ""))[:16].replace("T", " ") or "undated"
            body = " ".join(str(m.get("text", "")).split())
            if len(body) > 160:
                body = body[:160] + "…"
            lines.append(f"  [{ts}] {body}")
    return "\n".join(lines)


def episodic_search(query: str, k: int = 5) -> str:
    """
    Semantic search over the FULL user-facing episodic log, returning the top-k most
    relevant past interactions WITH their timestamps (best match first).

    Why this exists (Brief 47): get_smart_context injects only the top-2 semantic hits +
    last-3 by recency. That passive window structurally misses (a) older interactions, and
    (b) the two-part temporal follow-up — "have I said X?" matches on content, but the bare
    follow-up "when?" embeds to nothing near the original episode, so the timestamp is
    unreachable. A deliberate tool call reaches the whole log and returns the timestamp
    inline, so the FIRST answer can already say "yes — on June 11 ~21:30".
    """
    if _agent_ref is None or getattr(_agent_ref, "db", None) is None:
        return "Error: episodic memory not available."
    try:
        k = max(1, min(int(k or 5), 10))
    except (TypeError, ValueError):
        k = 5

    # Memory dict lives on the agent's CRUD instance (clara.db.memory), not the agent itself.
    episodes = (_agent_ref.db.memory or {}).get("episodic_log", [])
    if not episodes:
        return "No episodic memories recorded yet."

    try:
        from .crud import SYSTEM_PREFIXES
    except ImportError:
        SYSTEM_PREFIXES = ("[AUTONOMOUS]", "[TASK")
    user_idx = [i for i, ep in enumerate(episodes)
                if not ep.get("summary", "").startswith(SYSTEM_PREFIXES)]
    if not user_idx:
        return "No user-facing episodic memories recorded yet."

    def _fmt(idx, score=None):
        ep = episodes[idx]
        ts = ep.get("timestamp", "")[:16].replace("T", " ") or "undated"
        rel = f" (relevance {score:.2f})" if score is not None else ""
        return f"- [{ts}]{rel} {ep.get('summary', '')}"

    embs = getattr(_agent_ref, "episodic_embeddings", None)
    # Semantic path — only when embeddings are present AND index-aligned with the log.
    if embs and len(embs) == len(episodes):
        try:
            import torch
            q_emb = _agent_ref._encode_sync(query).to("cpu")
            user_embs = torch.stack([embs[i] for i in user_idx])
            sims = torch.nn.functional.cosine_similarity(q_emb.unsqueeze(0), user_embs)
            kk = min(k, len(user_idx))
            top = sims.topk(kk).indices.tolist()
            lines = [_fmt(user_idx[li], float(sims[li])) for li in top]
            header = "Most relevant past interactions (best match first):"
            if float(sims[top[0]]) < 0.30:
                header = ("No strongly matching memory — closest interactions below "
                          "(low relevance; treat as weak matches):")
            return header + "\n" + "\n".join(lines)
        except Exception:
            pass  # fall through to keyword scan

    # Keyword fallback — embeddings missing or drifted out of alignment.
    q_words = [w for w in query.lower().split() if len(w) > 2]
    scored = []
    for i in user_idx:
        s = episodes[i].get("summary", "").lower()
        hits = sum(1 for w in q_words if w in s)
        if hits:
            scored.append((hits, i))
    if not scored:
        return f"No episodic memory mentions: {query!r}."
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return "Past interactions mentioning that (keyword match):\n" + "\n".join(
        _fmt(i) for _, i in scored[:k])


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