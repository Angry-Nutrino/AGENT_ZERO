import asyncio
from datetime import datetime, timezone
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .event_queue import EventQueue, make_event
from .task_graph import TaskGraph
from .session_logger import slog
from .crud import SYSTEM_PREFIXES  # shared system-episode filter (Brief 36 B-4/B-8)


# ---------------------------------------------------------------------------
# Priority table
# ---------------------------------------------------------------------------

_TRIGGER_PRIORITIES: dict = {
    "file_change":         0.4,
    "memory_growth":       0.35,
    "interaction_density": 0.3,
}

# Paths / patterns that generate high-frequency noise and must be ignored
IGNORED_PATTERNS: list = [
    "__pycache__",
    ".pyc",
    "tasks.db",
    "tasks.db-wal",
    "tasks.db-shm",
    ".log",
    "session_",
    "knowledge_base",   # RAG index output — never trigger rebuild on its own writes
    ".faiss",
    ".pkl",
    ".tmp.",             # Editor temp files (e.g., agent.py.tmp.xxxxx) — ignore, debounce real file
    ".memory.json.",     # crud._save_memory atomic-write temp (.memory.json.XXXX.tmp, unique per write) — ignore
    "admissibility_ledger",  # BRIEF_54 gate audit ledger (+ its .admissibility_ledger.* temps via substring) —
                             # written on every gated action; must never spawn file_change tasks
    "ambient.json",      # A0 watcher store (+ its .ambient.json.* temps match via substring) — flushes
    "ambient_patterns.json",  # backend-derived baseline. Without these, every ~30s flush spawns a
    "ambient_watch.log",      # file_change task. (ambient.py CODE edits still trigger normally.)
    "ambient_shadow.jsonl",   # A2 Y1c shadow log (loop writes candidate remarks here in shadow mode)
    "ambient_loop_state.json", # A2 Y1c cursor state (+ .tmp via substring); both are runtime, not code
    "ambient_ledger.json",    # A2 Y1e live feed + 👍/👎 store (runtime, written on every nudge/vote)
    ".swp",              # Vim/Neovim swap files
    ".swo",              # Vim/Neovim swap files (older)
    "node_modules",      # JS deps. An npm install under core_logic/interface/ emitted 12,640
                         # file_change events in ONE harness run (2026-06-04) — each spawned an
                         # autonomous task and saturated the orchestrator until user requests
                         # (Q17-Q20) timed out at 180s. node_modules must never reach the watcher.
    ".git",              # VCS metadata churn
]


# ---------------------------------------------------------------------------
# Watchdog file-system event handler
# ---------------------------------------------------------------------------

class _FileEventHandler(FileSystemEventHandler):
    """Bridges watchdog OS-thread callbacks into the asyncio event loop."""

    def __init__(self, watcher: "EnvironmentWatcher"):
        super().__init__()
        self._watcher = watcher

    def _should_ignore(self, path: str) -> bool:
        return any(pat in path for pat in IGNORED_PATTERNS)

    def on_modified(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if self._should_ignore(path):
            return
        asyncio.run_coroutine_threadsafe(
            self._watcher._on_file_changed(path, "modified"),
            self._watcher._event_loop,
        )

    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if self._should_ignore(path):
            return
        asyncio.run_coroutine_threadsafe(
            self._watcher._on_file_changed(path, "created"),
            self._watcher._event_loop,
        )

    def on_deleted(self, event):
        # Deletions only matter for RAG sources: a doc removed from core_logic/docs/
        # previously NEVER triggered a rebuild, so its chunks haunted the FAISS index
        # until an unrelated rebuild (Brief 36 B-5). Other deletions stay ignored.
        if event.is_directory:
            return
        path = event.src_path
        if self._should_ignore(path):
            return
        normalised = path.replace("\\", "/")
        if any(src in normalised for src in ("CLAUDE.md", "ROADMAP.md", "/docs/")):
            asyncio.run_coroutine_threadsafe(
                self._watcher._on_file_changed(path, "deleted"),
                self._watcher._event_loop,
            )


# ---------------------------------------------------------------------------
# EnvironmentWatcher
# ---------------------------------------------------------------------------

class EnvironmentWatcher:
    """
    Observes the external environment and emits system_trigger events when
    meaningful state changes occur. Complements BackgroundScheduler (clock-driven)
    with event-driven signals.

    Three observation targets:
      1. File system watch — watchdog monitors specified directories
      2. Memory growth watch — fires when episodic log crosses a growth threshold
      3. Interaction density — fires after N user interactions in a session
    """

    def __init__(
        self,
        task_graph: TaskGraph,
        event_queue: EventQueue,
        agent,
        event_loop: asyncio.AbstractEventLoop,
        watch_paths: list = None,
        memory_growth_threshold: int = 20,
        interaction_density_threshold: int = 10,
    ):
        self._task_graph  = task_graph
        self._event_queue = event_queue
        self._agent       = agent
        self._event_loop  = event_loop
        self._watch_paths = watch_paths if watch_paths is not None else ["core_logic/"]
        self._memory_growth_threshold      = memory_growth_threshold
        self._interaction_density_threshold = interaction_density_threshold

        self._running: bool = False
        self._observer = None
        self._last_episode_count: int = 0
        self._interaction_count: int  = 0
        self._emit_lock: asyncio.Lock = asyncio.Lock()
        self._last_file_change: dict  = {}  # path → last emit timestamp (monotonic)

    # ------------------------------------------------------------------ public

    async def start(self) -> None:
        if self._running:
            slog.warning("[EnvWatcher] Already running — start() ignored.")
            return
        self._running = True

        # Snapshot current user-facing episode count as baseline
        episodes = self._agent.db.memory.get("episodic_log", [])
        self._last_episode_count = sum(
            1 for ep in episodes
            if not ep.get("summary", "").startswith(SYSTEM_PREFIXES)
        )

        # Start watchdog Observer
        handler = _FileEventHandler(self)
        self._observer = Observer()
        for path in self._watch_paths:
            self._observer.schedule(handler, path, recursive=True)
        self._observer.start()

        slog.info(
            f"[EnvWatcher] Started. Watching: {self._watch_paths} | "
            f"Memory threshold: {self._memory_growth_threshold} | "
            f"Interaction threshold: {self._interaction_density_threshold}"
        )

    async def stop(self) -> None:
        self._running = False
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        slog.info("[EnvWatcher] Stopped.")

    def notify_interaction(self) -> None:
        """
        Called after each user interaction. Increments counter and fires
        interaction_density trigger when threshold is reached.
        Safe to call from sync context (WebSocket handler).
        """
        self._interaction_count += 1
        if self._interaction_count >= self._interaction_density_threshold:
            self._interaction_count = 0
            asyncio.run_coroutine_threadsafe(
                self._emit_trigger("interaction_density"),
                self._event_loop,
            )

    async def check_memory_growth(self) -> None:
        """
        Compare current user-facing episodic entry count against last snapshot.
        Only counts entries without [AUTONOMOUS]/[TASK *] prefixes — autonomous
        background entries should not trigger memory_growth noise.
        Emits memory_growth trigger when user-facing growth >= threshold.
        """
        episodes = self._agent.db.memory.get("episodic_log", [])
        user_count = sum(
            1 for ep in episodes
            if not ep.get("summary", "").startswith(SYSTEM_PREFIXES)
        )
        # Clamp after an external prune (count can drop BELOW the baseline, which
        # would silence the trigger until regrowth crossed the stale high-water mark).
        if user_count < self._last_episode_count:
            self._last_episode_count = user_count
        if user_count - self._last_episode_count >= self._memory_growth_threshold:
            self._last_episode_count = user_count
            await self._emit_trigger("memory_growth")

    # ------------------------------------------------------------------ private

    async def _on_file_changed(self, path: str, change_type: str) -> None:
        import time
        if not self._running:
            return

        # Normalise separators so Windows paths work with pattern checks
        normalised = path.replace("\\", "/")

        # Filter noise — same patterns as _FileEventHandler._should_ignore
        if any(pat in normalised for pat in IGNORED_PATTERNS):
            return

        # memory.json change → check growth instead of generic file_change
        if normalised.endswith("memory.json"):
            await self.check_memory_growth()
            return

        # Debounce: skip if same path fired within 5 seconds
        now = time.monotonic()
        if now - self._last_file_change.get(normalised, 0) < 5.0:
            return  # coalesce rapid saves — still processing the previous one
        self._last_file_change[normalised] = now
        # Keep the debounce dict bounded (one entry per unique path forever — B-6).
        if len(self._last_file_change) > 256:
            self._last_file_change = {
                k: v for k, v in self._last_file_change.items() if now - v < 3600
            }

        # RAG source files → rag_rebuild trigger instead of generic file_change
        RAG_SOURCES = ("CLAUDE.md", "ROADMAP.md", "/docs/")
        if any(src in normalised for src in RAG_SOURCES):
            await self._emit_trigger(
                trigger_name="rag_rebuild",
                extra_context={"path": path, "change_type": change_type},
            )
            return

        await self._emit_trigger(
            trigger_name="file_change",
            extra_context={"path": path, "change_type": change_type},
        )

    async def _emit_trigger(
        self,
        trigger_name: str,
        extra_context: dict = None,
    ) -> None:
        """Write-ahead: Task persisted to SQLite before the wake event is emitted."""
        async with self._emit_lock:
            try:
                # Dedupe (Brief 36 A-17): a same-trigger same-path task still in flight
                # means this signal is already being handled — don't stack a second
                # (two rapid RAG-source saves racing two concurrent FAISS rebuilds).
                new_path = (extra_context or {}).get("path")
                for t in self._task_graph._tasks.values():
                    if (t.origin == "system"
                            and t.context.get("trigger") == trigger_name
                            and t.state in ("pending", "active", "running")
                            and t.context.get("path") == new_path):
                        slog.debug(f"[EnvWatcher] '{trigger_name}' for this path already in flight — skipped.")
                        return

                context = {
                    "trigger": trigger_name,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
                if extra_context:
                    context.update(extra_context)

                task = self._task_graph.add_task(
                    goal=f"[ENVIRONMENT] {trigger_name}",
                    priority=_TRIGGER_PRIORITIES.get(trigger_name, 0.3),
                    reversibility="reversible",
                    dependencies=[],
                    context=context,
                    origin="system",
                )

                await self._event_queue.emit(make_event(
                    type="system_trigger",
                    payload={"trigger": trigger_name, "task_id": task.id},
                    priority=_TRIGGER_PRIORITIES.get(trigger_name, 0.3),
                    source="system",
                ))
                slog.info(
                    f"[EnvWatcher] Trigger emitted: {trigger_name} "
                    f"-> Task {task.id[:8]}"
                )
            except Exception as e:
                slog.error(
                    f"[EnvWatcher] Failed to emit trigger '{trigger_name}': {e}"
                )
