import asyncio
import os
from datetime import datetime, timezone
from .event_queue import EventQueue, make_event
from .task_graph import TaskGraph
from .session_logger import slog


DEFAULT_INTERVALS: dict = {
    "memory_maintenance": 300,   # every 5 minutes
    "context_warmup":     600,   # every 10 minutes
    "health_check":       120,   # every 2 minutes
}

_PRIORITIES: dict = {
    "memory_maintenance": 0.3,
    "context_warmup":     0.2,
    "health_check":       0.1,
}


# ---------------------------------------------------------------------------
# BackgroundScheduler
# ---------------------------------------------------------------------------

class BackgroundScheduler:
    """
    Runs alongside the Orchestrator. Emits system_trigger events on a schedule.
    Follows the write-ahead contract: Task written to TaskGraph FIRST, then
    the wake event is emitted. If the event is lost, SQLite still holds the
    pending task for crash recovery.
    """

    def __init__(
        self,
        task_graph: TaskGraph,
        event_queue: EventQueue,
        agent,
        intervals: dict = None,
    ):
        self._task_graph = task_graph
        self._event_queue = event_queue
        self._agent = agent
        self._intervals = intervals if intervals is not None else dict(DEFAULT_INTERVALS)
        self._running: bool = False
        self._tasks: dict = {}       # trigger_name → asyncio.Task
        self._last_run: dict = {}    # trigger_name → datetime

    async def start(self) -> None:
        if self._running:
            slog.warning("[Scheduler] Already running — start() ignored.")
            return
        self._running = True
        for trigger_name, interval in self._intervals.items():
            self._tasks[trigger_name] = asyncio.create_task(
                self._schedule_loop(trigger_name, interval)
            )
        slog.info(f"[Scheduler] Started. Triggers: {list(self._intervals.keys())}")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks.values():
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        slog.info("[Scheduler] Stopped.")

    async def _schedule_loop(self, trigger_name: str, interval: int) -> None:
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            await self._emit_trigger(trigger_name)

    async def _emit_trigger(self, trigger_name: str) -> None:
        try:
            # Dedupe (Brief 36 A-17): if an identical trigger task is still pending or
            # in flight (e.g. the loop stalled and a backlog formed), don't stack
            # another — the existing one will run.
            for t in self._task_graph._tasks.values():
                if (t.origin == "system"
                        and t.context.get("trigger") == trigger_name
                        and t.state in ("pending", "active", "running")):
                    slog.debug(f"[Scheduler] '{trigger_name}' already in flight — skipped.")
                    return

            # 1. Write Task to TaskGraph FIRST (write-ahead durability)
            task = self._task_graph.add_task(
                goal=f"[BACKGROUND] {trigger_name}",
                priority=_PRIORITIES.get(trigger_name, 0.3),
                reversibility="reversible",
                dependencies=[],
                context={
                    "trigger": trigger_name,
                    "scheduled_at": datetime.now(timezone.utc).isoformat(),
                },
                origin="system",
            )
            self._last_run[trigger_name] = datetime.now(timezone.utc)

            # 2. THEN emit wake signal
            await self._event_queue.emit(make_event(
                type="system_trigger",
                payload={
                    "trigger": trigger_name,
                    "task_id": task.id,
                },
                priority=_PRIORITIES.get(trigger_name, 0.3),
                source="system",
            ))
            slog.info(f"[Scheduler] Trigger emitted: {trigger_name} → Task {task.id[:8]}")
        except Exception as e:
            slog.error(f"[Scheduler] Failed to emit trigger '{trigger_name}': {e}")


# ---------------------------------------------------------------------------
# Worker dispatch table
# ---------------------------------------------------------------------------

async def run_background_task(trigger_name: str, agent, task_graph: TaskGraph, ctx: dict = None) -> str:
    """
    Dispatch table for background task execution.
    Returns a result string for task_completed event.
    ctx: the task's context dict, used by environment-triggered workers.
    """
    if ctx is None:
        ctx = {}
    if trigger_name == "memory_maintenance":
        return await _memory_maintenance(agent, task_graph)
    elif trigger_name == "context_warmup":
        return await _context_warmup(agent)
    elif trigger_name == "health_check":
        return await _health_check(task_graph)
    elif trigger_name == "file_change":
        return await _handle_file_change(ctx)
    elif trigger_name == "memory_growth":
        return await _handle_memory_growth(agent)
    elif trigger_name == "interaction_density":
        return await _handle_interaction_density(agent)
    elif trigger_name == "rag_rebuild":
        return await _handle_rag_rebuild(ctx)
    else:
        slog.warning(f"[BG] Unknown trigger: {trigger_name}")
        return f"Unknown trigger: {trigger_name}"


# Full janitor sweep at most every 6h (the trigger fires every 5 min — sweeping each
# time would be pointless disk churn). Between sweeps it's the old counts heartbeat.
_JANITOR_INTERVAL_S = 6 * 3600
_last_janitor_ts: float = 0.0


def _janitor_sweep(task_graph) -> list:
    """Real maintenance (Brief 36 A-16): retention for traces/logs (A-12 found 653 MB
    of tick spam with no retention anywhere), terminal task rows (A-9: 796 rows, never
    pruned), orphaned upload temp files (B-17 — age-gated >1 day because a Brief-35
    detached retry may still need a recent temp_doc/temp_image), and memory.json
    backup rotation. Returns a list of action strings (empty = nothing to do)."""
    import glob
    import time as _time
    actions = []
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    now = _time.time()

    def _prune_dir(dirname: str, pattern: str, max_age_days: float):
        deleted = 0
        for path in glob.glob(os.path.join(root, dirname, pattern)):
            try:
                if now - os.path.getmtime(path) > max_age_days * 86400:
                    os.remove(path)
                    deleted += 1
            except OSError:
                pass  # current session's open log/trace — skip
        if deleted:
            actions.append(f"deleted {deleted} {dirname} file(s) older than {max_age_days:g}d")

    _prune_dir("traces", "trace_*.jsonl", 14)
    _prune_dir("logs", "session_*.log", 14)
    _prune_dir("benchmarks", "bench_*.log", 30)

    # Orphaned upload temps in the project root (>1 day — never sweep fresh ones).
    deleted = 0
    for pattern in ("temp_image_*", "temp_doc_*"):
        for path in glob.glob(os.path.join(root, pattern)):
            try:
                if now - os.path.getmtime(path) > 86400:
                    os.remove(path)
                    deleted += 1
            except OSError:
                pass
    if deleted:
        actions.append(f"deleted {deleted} orphaned upload temp file(s)")

    # Terminal task rows older than 7 days.
    try:
        pruned = task_graph.prune_terminal(days=7)
        if pruned:
            actions.append(f"pruned {pruned} terminal task row(s)")
    except Exception as e:
        slog.warning(f"[BG:janitor] task prune failed: {e}")

    # memory.json backup rotation — keep the 3 newest of each backup class.
    for pattern in ("memory.json.bak-*", "memory.json.corrupt-*"):
        backups = sorted(
            glob.glob(os.path.join(root, "core_logic", pattern)),
            key=os.path.getmtime, reverse=True,
        )
        for path in backups[3:]:
            try:
                os.remove(path)
                actions.append(f"removed old backup {os.path.basename(path)}")
            except OSError:
                pass

    return actions


async def _memory_maintenance(agent, task_graph) -> str:
    """
    Memory status heartbeat + (every ~6h) a real janitor sweep. The sweep result
    contains action keywords (pruned/deleted/removed) ONLY when something was done —
    the orchestrator's episodic gate logs an [AUTONOMOUS] episode only then, so
    routine heartbeats stay out of permanent memory (Brief 36 B-20).
    """
    global _last_janitor_ts
    import time as _time

    episode_count = len(agent.db.memory.get("episodic_log", []))
    vault_count   = len(agent.db.memory.get("long_term", []))
    status = f"Memory status: {episode_count} episodes, {vault_count} vault facts."

    if _time.time() - _last_janitor_ts >= _JANITOR_INTERVAL_S:
        _last_janitor_ts = _time.time()
        actions = await asyncio.to_thread(_janitor_sweep, task_graph)
        if actions:
            status += " Janitor: " + "; ".join(actions) + "."
            slog.info(f"[BG:memory_maintenance] Janitor: {'; '.join(actions)}")

    slog.info(
        f"[BG:memory_maintenance] Episodes: {episode_count} | Vault facts: {vault_count}"
    )
    return status


async def _context_warmup(agent) -> str:
    """
    Verify episodic embeddings are in sync with episodic log.
    If out of sync, re-encodes all summaries to restore alignment.
    """
    ep_count  = len(agent.db.memory.get("episodic_log", []))
    emb_count = len(agent.episodic_embeddings)
    in_sync   = (ep_count == emb_count)

    if not in_sync:
        slog.warning(
            f"[BG:context_warmup] Out of sync: {ep_count} episodes, "
            f"{emb_count} embeddings. Re-encoding all..."
        )
        try:
            summaries = [
                ep.get("summary", "")
                for ep in agent.db.memory.get("episodic_log", [])
            ]
            if summaries:
                # MUST be await agent._encode(...) — this coroutine runs ON the event
                # loop, and _encode_sync blocks its calling thread on a future scheduled
                # on that same loop: a guaranteed 30s freeze + TimeoutError, so the
                # self-repair could never succeed (Brief 36 A-2). _encode_sync is for
                # background THREADS (memorize_episode) only.
                embs = await agent._encode(summaries)
                if embs.dim() == 2:
                    agent.episodic_embeddings = [embs[i].to('cpu') for i in range(len(summaries))]
                else:
                    agent.episodic_embeddings = [embs.to('cpu')]
            slog.info(
                f"[BG:context_warmup] Re-sync complete. "
                f"{len(agent.episodic_embeddings)} embeddings."
            )
            return f"Re-synced {len(summaries)} embeddings."
        except Exception as e:
            slog.error(f"[BG:context_warmup] Re-sync failed: {e}")
            return f"Re-sync failed: {e}"

    slog.info(
        f"[BG:context_warmup] Episodes: {ep_count} | "
        f"Embeddings: {emb_count} | In sync: True"
    )
    return f"Episodes: {ep_count} | Embeddings: {emb_count} | In sync: True"


async def _handle_file_change(ctx: dict) -> str:
    path        = ctx.get("path", "unknown")
    change_type = ctx.get("change_type", "unknown")
    slog.info(f"[BG:file_change] {change_type}: {path}")
    return f"File {change_type}: {path}"


async def _handle_memory_growth(agent) -> str:
    episode_count = len(agent.db.memory.get("episodic_log", []))
    slog.info(f"[BG:memory_growth] Episodic log grew to {episode_count} entries.")
    return f"Memory growth noted: {episode_count} episodes."


async def _handle_interaction_density(agent) -> str:
    episode_count = len(agent.db.memory.get("episodic_log", []))
    slog.info(
        f"[BG:interaction_density] High interaction density detected. "
        f"Episodes: {episode_count}"
    )
    return f"Interaction density threshold reached. Episodes: {episode_count}"


async def _handle_rag_rebuild(ctx: dict) -> str:
    """
    Triggered when a watched source file changes (CLAUDE.md, ROADMAP.md,
    or any file in core_logic/docs/).
    Runs full rebuild in a thread (CPU-bound), then hot-reloads engine.
    """
    from .rag_db_builder import build_knowledge_base
    from .tools import reload_rag_engine

    trigger_path = ctx.get("path", "unknown")
    slog.info(f"[BG:rag_rebuild] Source changed: {trigger_path}. Rebuilding...")

    try:
        result = await asyncio.to_thread(build_knowledge_base)
        reloaded = reload_rag_engine()
        status = f"RAG rebuild complete. {result} Engine reloaded: {reloaded}"
        slog.info(f"[BG:rag_rebuild] {status}")
        return status
    except Exception as e:
        slog.error(f"[BG:rag_rebuild] Rebuild failed: {e}")
        return f"RAG rebuild failed: {e}"


async def _health_check(task_graph: TaskGraph) -> str:
    """
    Log system health metrics. No mutations.
    """
    import psutil
    import torch

    ram  = psutil.virtual_memory().percent
    vram = "N/A"
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved  = torch.cuda.memory_reserved()  / 1024**3
        vram      = f"{allocated:.2f}GB allocated / {reserved:.2f}GB reserved"

    pending = len(task_graph.get_tasks_by_state("pending"))
    running = len(task_graph.get_all_active())
    paused  = len(task_graph.get_paused_tasks())

    report = (
        f"RAM: {ram}% | VRAM: {vram} | "
        f"Tasks — pending: {pending}, active/running: {running}, paused: {paused}"
    )
    slog.info(f"[BG:health_check] {report}")
    return report
