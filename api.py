# api.py
import sys
import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import psutil
import platform
import asyncio
import threading
import uuid as _uuid

# --- PATH SETUP ---
sys.path.append(os.path.join(os.path.dirname(__file__), "core_logic"))

from core_logic.agent import Clara_Agent
from core_logic.task_graph import TaskGraph
from core_logic.event_queue import EventQueue, make_event
from core_logic.orchestrator import Orchestrator
from core_logic.background_tasks import BackgroundScheduler
from core_logic.environment import EnvironmentWatcher
from core_logic.tracer import Tracer
from core_logic.tools import set_task_graph
from core_logic.session_logger import init_session_log, slog
from core_logic.bench_logger import init_bench_log, close_bench_log
from core_logic.tool_registry import ToolRegistry
from core_logic.mcp_client import MCPClient, MCPError
from core_logic.voice import VoiceCoordinator, set_voice
from core_logic.telegram_bot import TelegramBot
from starlette.websockets import WebSocketState

# Start session log before anything else
init_session_log()

# --- Module-level singletons (set during lifespan startup) ---
clara: Clara_Agent | None = None
task_graph: TaskGraph | None = None
event_queue: EventQueue | None = None
orchestrator: Orchestrator | None = None
scheduler: BackgroundScheduler | None = None
env_watcher: EnvironmentWatcher | None = None
tracer: Tracer | None = None
tool_registry: ToolRegistry | None = None
mcp_client: MCPClient | None = None
voice: VoiceCoordinator | None = None
telegram_bot: TelegramBot | None = None
active_connections: set = set()  # live WebSocket connections — used for speaking_start/stop broadcast

async def _broadcast(payload: dict) -> None:
    """Send a JSON payload to all connected WS clients, pruning dead connections."""
    if not active_connections:
        return
    dead = set()
    for ws in active_connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    if dead:
        active_connections.difference_update(dead)


async def broadcast_task_event(task_id: str, goal: str, state: str, priority: float = 0.5, source: str = "system", message_id: str = ""):
    await _broadcast({
        "type": "task_event",
        "task_id": task_id,
        "goal": goal,
        "state": state,
        "priority": priority,
        "source": source,
        "message_id": message_id,
    })


async def _broadcast_speaking(is_speaking: bool):
    await _broadcast({"type": "speaking_start" if is_speaking else "speaking_stop"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    global clara, task_graph, event_queue, orchestrator, scheduler, env_watcher, tracer, voice

    # Startup
    slog.info("[API] Starting CLARA system...")
    _pid_file = os.path.join(os.path.dirname(__file__), "clara_backend.pid")
    try:
        with open(_pid_file, "w") as _f:
            _f.write(str(os.getpid()))
    except Exception:
        pass
    init_bench_log("benchmarks")
    slog.info("[API] Benchmark logger initialized.")
    tracer = Tracer(enabled=True, traces_dir="traces")
    slog.info("[API] Tracer initialized.")
    clara = Clara_Agent()
    task_graph = TaskGraph()
    set_task_graph(task_graph)
    slog.info("[API] TaskGraph reference injected into tools.")
    # Inject the agent's LIVE crud instance into the tool executor (Brief 36 C-35 —
    # it previously imported the crud CLASS, so fsmap auto-population never ran).
    from core_logic.tool_executor import set_db
    set_db(clara.db)
    slog.info("[API] Memory db reference injected into tool executor.")
    event_queue = EventQueue()
    orchestrator = Orchestrator(clara, event_queue, task_graph, tracer=tracer)
    await orchestrator.start()
    orchestrator._broadcast_fn = broadcast_task_event  # inject callback — avoids circular import
    orchestrator._send_message_fn = _broadcast  # general WS push for Brief 35 proactive retry delivery
    slog.info("[API] Orchestrator running.")
    scheduler = BackgroundScheduler(task_graph, event_queue, clara)
    await scheduler.start()
    slog.info("[API] BackgroundScheduler running.")
    env_watcher = EnvironmentWatcher(
        task_graph=task_graph,
        event_queue=event_queue,
        agent=clara,
        event_loop=asyncio.get_event_loop(),
        watch_paths=[
            "core_logic/",
            "CLAUDE.md",
            "briefs/ROADMAP.md",
        ],
    )
    await env_watcher.start()
    slog.info("[API] EnvironmentWatcher running.")

    # Build/verify RAG knowledge base at startup
    try:
        from core_logic.rag_db_builder import build_knowledge_base
        from core_logic.tools import reload_rag_engine
        slog.info("[API] Building RAG knowledge base...")
        await asyncio.to_thread(build_knowledge_base)
        reload_rag_engine()
        slog.info("[API] RAG knowledge base ready.")
    except Exception as e:
        slog.error(f"[API] RAG build failed at startup: {e}")

    # ── Tool Registry + MCP Client ────────────────────────────────────────────
    global tool_registry, mcp_client

    tool_registry = ToolRegistry()
    tool_registry.register_native_tools()

    mcp_client = MCPClient()

    dc_node = os.getenv("DC_NODE_PATH", "")
    dc_cli  = os.getenv("DC_CLI_PATH", "")

    if dc_node and dc_cli and os.path.exists(dc_node) and os.path.exists(dc_cli):
        try:
            dc_tools = await mcp_client.connect("desktop_commander", dc_node, [dc_cli])
            tool_registry.register_server_tools("desktop_commander", dc_tools)
            slog.info(f"[API] Desktop Commander connected: {len(dc_tools)} tools registered.")
        except MCPError as e:
            slog.warning(f"[API] Desktop Commander connection failed: {e}. Continuing without DC tools.")
    else:
        slog.warning("[API] DC_NODE_PATH or DC_CLI_PATH not set. DC tools unavailable.")

    # MarkItDown — STDIO MCP server (Microsoft). One tool: convert_to_markdown(uri).
    # Fills the gap DC read_file cannot: PDF / DOCX / XLSX / PPTX / EPUB and other
    # binary office formats → clean Markdown. Runs in the same venv as the backend.
    try:
        md_tools = await mcp_client.connect("markitdown", sys.executable, ["-m", "markitdown_mcp"])
        tool_registry.register_server_tools("markitdown", md_tools)
        slog.info(f"[API] MarkItDown connected: {len(md_tools)} tools registered.")
    except MCPError as e:
        slog.warning(f"[API] MarkItDown connection failed: {e}. Continuing without document-conversion tools.")

    await tool_registry.rebuild_embeddings(clara._encode)
    slog.info(f"[API] Tool registry ready: {tool_registry.tool_count} tools indexed.")

    clara.tool_registry = tool_registry
    clara.mcp_client = mcp_client
    slog.info("[API] Tool registry injected into agent.")

    # ── Telegram Bot ──────────────────────────────────────────────────────────
    global telegram_bot
    tg_token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "")

    if tg_token and tg_chat_id:
        telegram_bot = TelegramBot(orchestrator, tg_token, tg_chat_id)
        await telegram_bot.start()
        slog.info("[API] Telegram bot active.")
    else:
        slog.info("[API] Telegram not configured — TELEGRAM_BOT_TOKEN or CHAT_ID missing.")

    # Voice system — load after everything else; failure is non-fatal
    try:
        voice = VoiceCoordinator()
        voice.load()
        set_voice(voice)
        loop = asyncio.get_event_loop()
        voice.set_speaking_callback(
            lambda is_spk: asyncio.run_coroutine_threadsafe(
                _broadcast_speaking(is_spk), loop
            )
        )
        slog.info("[API] Voice system loaded.")
    except Exception as e:
        slog.warning(f"[API] Voice system unavailable: {e}. Continuing without voice.")
        voice = None

    yield  # server is live here

    # Shutdown
    slog.info("[API] Shutting down CLARA system...")
    try:
        if os.path.exists(_pid_file):
            os.remove(_pid_file)
    except Exception:
        pass
    close_bench_log()
    if voice:
        voice.unload()
        slog.info("[API] Voice system unloaded.")
    if telegram_bot:
        await telegram_bot.stop()
    if mcp_client:
        await mcp_client.disconnect_all()
    await env_watcher.stop()
    slog.info("[API] EnvironmentWatcher stopped.")
    await scheduler.stop()
    slog.info("[API] BackgroundScheduler stopped.")
    await orchestrator.stop()
    slog.info("[API] Clean shutdown complete.")


app = FastAPI(lifespan=lifespan)

# Enable React to talk to Python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)

    async def send_update(content: str, type="thought",
                          turn_id=None, message_id=None, extra=None):
        if not active_connections:
            return
        payload = {
            "type": type,
            "content": content,
            "turn_id": turn_id,
            "message_id": message_id,
        }
        if extra:
            payload["extra"] = extra
        await _broadcast(payload)

    def _voice_ready() -> bool:
        return bool(voice and voice.is_enabled())

    def _speak_ack(interpreted: dict, mode: str):
        if _voice_ready():
            ack = voice.get_acknowledgment(interpreted, mode)
            if ack:
                voice.speak(ack, block=False)

    async def handle_message(user_text: str, image_data, file_data, message_id: str, via_voice: bool = False):
        try:
            async def on_step(content, type="thought", turn_id=None, extra=None):
                await send_update(
                    content, type=type,
                    turn_id=turn_id, message_id=message_id, extra=extra
                )
            # 600s ceiling (Brief 36 A-13): without it, ANY bug that drops a response
            # future means permanent silence for this message. On timeout the awaited
            # future is cancelled, so a late worker result is dropped harmlessly
            # (set_result is guarded by future.done()).
            response = await asyncio.wait_for(
                orchestrator.submit_user_event(
                    text=user_text,
                    image_data=image_data,
                    file_data=file_data,
                    message_id=message_id,
                    on_step_update=on_step,
                    on_interpreted=_speak_ack if via_voice else None,
                ),
                timeout=600,
            )
            env_watcher.notify_interaction()
            if via_voice and _voice_ready():
                slog.info(f"[Voice] Speaking response ({len(response)} chars), speaking={voice.is_speaking()}")
                # Start synthesis in background thread before sending WS — hides synthesis latency
                threading.Thread(target=voice.speak, args=(response,), kwargs={"block": True}, daemon=True).start()
            await _broadcast({
                "type": "final_answer",
                "content": response,
                "message_id": message_id,
            })
        except asyncio.TimeoutError:
            slog.error(f"[WS] handle_message timed out after 600s (message {message_id}).")
            await _broadcast({
                "type": "final_answer",
                "content": ("This is taking far longer than it should — I've let it go for now. "
                            "The task may still finish in the background; ask me again in a moment."),
                "message_id": message_id,
            })
        except Exception as e:
            slog.error(f"[WS] handle_message failed: {e}")
            await _broadcast({
                "type": "final_answer",
                "content": f"Error: {e}",
                "message_id": message_id,
            })

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                payload    = json.loads(raw_data)
                msg_type   = payload.get("type", "")
                message_id = payload.get("message_id", str(_uuid.uuid4()))

                if msg_type == "voice_start":
                    if _voice_ready():
                        voice.start_recording()
                    continue

                if msg_type == "voice_stop":
                    if _voice_ready():
                        text = await voice.stop_recording_async()
                        if text:
                            await websocket.send_json({
                                "type": "user_transcript",
                                "content": text,
                                "message_id": message_id,
                            })
                            asyncio.create_task(
                                handle_message(text, None, None, message_id, via_voice=True)
                            )
                    continue

                if msg_type == "voice_interrupt":
                    if voice:
                        voice.interrupt_speech()
                    continue

                if msg_type == "cancel_task":
                    target_id = payload.get("task_id", "")
                    if target_id and orchestrator:
                        cancelled = await orchestrator.cancel_task(target_id)
                        await websocket.send_json({
                            "type": "task_cancelled",
                            "task_id": target_id,
                            "success": cancelled,
                        })
                    continue

                user_text  = payload.get("text", "")
                image_data = payload.get("image", None)
                file_data  = payload.get("file", None)
            except json.JSONDecodeError:
                user_text  = raw_data
                image_data = None
                file_data  = None
                message_id = str(_uuid.uuid4())

            # Fire and forget — do NOT await
            asyncio.create_task(
                handle_message(user_text, image_data, file_data, message_id)
            )

    except WebSocketDisconnect:
        slog.info("[API] Client disconnected.")
    finally:
        # Always remove — a non-Disconnect exception (e.g. send_json on a socket that
        # closed mid-reply) previously left the dead socket in active_connections.
        active_connections.discard(websocket)


@app.get("/soul")
async def get_soul():
    """
    Returns the Agent's perception of the User + Real Hardware Vitals.
    """
    profile = {
        "identity": {"name": "Alkama", "role": "Unknown", "location": "India", "clearance": "Lvl 1"},
        "skills": ["System Offline"],
        "mission": {"current": "Initializing...", "status": "WAIT", "phase": "Init"},
        "vitals": {"cpu": "Unknown", "gpu": "Offline", "memory_usage": "0%", "status": "OFFLINE"}
    }

    try:
        # Serve from the agent's LIVE in-RAM memory (Brief 36 D-5). The old disk read
        # was the documented READER causing os.replace PermissionError contention in
        # crud._save_memory — and the RAM dict is always fresher anyway.
        if clara is not None:
            memory = clara.db.memory

            user = memory.get("user_profile", {})
            state = memory.get("project_state", {})

            profile["identity"] = {
                "name": user.get("name", "Alkama"),
                "role": user.get("role", "Architect"),
                "location": "India",
                "clearance": "Lvl 5 (Admin)"
            }

            tools = user.get("preferences", {}).get("tools", [])
            interests = user.get("interests", [])
            profile["skills"] = (tools + interests)[:8] or [
                "Python (AsyncIO)", "React + Vite", "FastAPI",
                "Grok API", "Docker", "Generative AI"
            ]

            profile["mission"] = {
                "current": state.get("current_phase", "Unknown"),
                "status": "IN PROGRESS",
                "phase": "V2.0"
            }
    except Exception as e:
        slog.error(f"Memory Load Error: {e}")

    try:
        ram_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_name = platform.processor()
        if "Intel" in cpu_name: cpu_name = "Intel Core i5"
        if "AMD" in cpu_name: cpu_name = "AMD Ryzen 4800H"

        # VRAM via torch if available
        vram_used_gb, vram_total_gb = 0.0, 4.0
        try:
            import torch
            if torch.cuda.is_available():
                vram_used_gb  = round(torch.cuda.memory_allocated(0) / 1e9, 2)
                vram_total_gb = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
        except Exception:
            pass

        profile["vitals"] = {
            "cpu":          f"{cpu_percent}%",
            "cpu_name":     cpu_name,
            "gpu":          f"{vram_used_gb}GB / {vram_total_gb}GB",
            "memory_usage": f"{ram_percent}%",
            "status":       "ONLINE"
        }
    except Exception as e:
        slog.error(f"Vitals Error: {e}")

    return {**profile, "version": "v2.6"}


class QueryRequest(BaseModel):
    text: str
    # Test-only endpoint. memory_mode isolates test traffic from Clara's real memory —
    # without it, scripted drill fixtures (fake job offers, manager "Priya", brother in
    # "Lisbon") leaked into episodic memory and Clara later surfaced them as real facts in
    # genuine conversations (2026-06-07 confabulation). Values:
    #   "none"      — write nothing (L1-L5 harness; single-turn, needs full isolation)
    #   "ephemeral" — transient recent_exchanges only, NO permanent episodic/vault
    #                 (coherence drill; needs within-dialogue recall, resets between dialogues)
    #   "full"      — normal persistence (never used by the harness; real users only)
    memory_mode: str = "none"
    # Brief 32: when True, the response includes the raw post-routing ReAct loop
    # (react_trace) so the harness can feed a FAILED query's actual turns to Clara for
    # Self-Assessment Layer 2 root-cause diagnosis. Off by default (real callers never need it).
    return_trace: bool = False

@app.post("/query")
async def query_endpoint(req: QueryRequest):
    """
    Simple HTTP endpoint for the daily test harness.
    Fires a query through the full orchestrator pipeline and returns the final answer.
    Local-only, unauthenticated — do not expose publicly.
    memory_mode defaults "none" so test traffic never persists to Clara's memory.
    """
    if not orchestrator:
        return {"response": "Error: orchestrator not ready."}
    try:
        response = await asyncio.wait_for(
            orchestrator.submit_user_event(
                text=req.text, memory_mode=req.memory_mode, return_trace=req.return_trace
            ),
            timeout=600,  # Brief 36 A-13 — a dropped future becomes an honest error, not a hang
        )
        # With return_trace, the worker resolves with {"response", "react_trace"}; pass it through.
        if isinstance(response, dict):
            return response
        return {"response": response}
    except Exception as e:
        slog.error(f"[/query] Error: {e}")
        return {"response": f"Error: {e}"}


@app.post("/reset_conversation")
async def reset_conversation_endpoint():
    """Clear ONLY the short-term conversational substrate (recent_exchanges + discourse_state)
    — episodic memory, vault and self_knowledge are untouched. Used by the Coherence Drill to
    isolate scripted dialogues. Local-only, unauthenticated — do not expose publicly."""
    if not clara:
        return {"ok": False, "error": "agent not ready"}
    try:
        cleared = clara.db.reset_conversation_state()
        return {"ok": True, "cleared": cleared}
    except Exception as e:
        slog.error(f"[/reset_conversation] Error: {e}")
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
