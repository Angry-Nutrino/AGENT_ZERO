import json
import os
import time
import tempfile
import threading
from datetime import datetime
from .session_logger import slog

# Episodic entries with these prefixes are SYSTEM-origin (autonomous work, task-state
# transitions) and are excluded from user-facing retrieval + growth counting. ONE shared
# constant, prefix-matched — the old per-module literal tuples drifted: get_smart_context
# knew 3 prefixes while the orchestrator wrote 7 variants, so [TASK SOFT-RETRY] /
# [TASK CANCELLED] / [TASK DEFERRED] episodes leaked into retrieval as "user-facing"
# context (Brief 36 B-4, confirmed live). "[TASK" catches every current+future variant.
SYSTEM_PREFIXES = ("[AUTONOMOUS]", "[TASK")


class crud:
    def __init__(self, filepath="core_logic/memory.json"):
        self.filepath = filepath
        # Guards self.memory against concurrent mutation across threads (event loop,
        # consolidation thread, tool-executor fsmap merges). Without it, json.dump in
        # _save_memory could iterate a dict/list mid-mutation → dropped save or a torn
        # snapshot on disk (Brief 36 B-1). RLock: mutators call _save_memory (nested).
        self._lock = threading.RLock()
        self.memory = self._load_memory()

    def _load_memory(self):
        if not os.path.exists(self.filepath):
            return self._create_default_memory()
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            # Corrupt memory file. Preserve it with a timestamped backup BEFORE
            # falling back to default memory — otherwise the next _save_memory would
            # overwrite (and permanently destroy) any recoverable data. Backing up
            # first keeps the system bootable AND prevents silent data loss.
            import shutil, time
            backup = f"{self.filepath}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                shutil.copy2(self.filepath, backup)
                slog.warning(f"[Memory] memory.json corrupt ({e}). Backed up to {backup}; loading default memory.")
            except Exception:
                pass
            return self._create_default_memory()

    def _create_default_memory(self):
        return {
            "user_profile": {},
            "project_state": {},
            "long_term": [],
            "episodic_log": [],
            "self_knowledge": {
                "architecture_facts": [],
                "failure_patterns": [],
                "recovery_methods": []
            },
            "filesystem_map": {}
        }

    def _save_memory(self):
        # Atomic write: serialize to a UNIQUE temp file in the same directory, fsync,
        # then os.replace() (atomic on Windows + POSIX). A crash or hard-kill mid-write
        # can no longer truncate the live memory file — the worst case is an orphan .tmp.
        # (Root cause of the 2026-05-29 truncation: the old open('w') zeroed the file
        # then streamed, and a kill mid-stream left it truncated, losing ~4000 episodes.)
        #
        # The temp name MUST be unique per call: memorize_episode runs in a background
        # thread and log_system_episode fires from autonomous tasks, so two writers can
        # be in _save_memory at once. A shared temp name would let them interleave the
        # same file and corrupt it despite os.replace — mkstemp gives each its own.
        # The ".memory.json." prefix keeps EnvironmentWatcher's ignore rule matching.
        with self._lock:
            d = os.path.dirname(self.filepath) or "."
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(prefix=".memory.json.", suffix=".tmp", dir=d)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(self.memory, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                # os.replace is atomic, but on WINDOWS it raises PermissionError
                # (ERROR_ACCESS_DENIED / SHARING_VIOLATION) when another handle has the
                # target open — e.g. a harness python_repl reading memory.json as we
                # swap. The contention is transient (readers hold the handle for
                # milliseconds), so retry with a short backoff rather than silently
                # dropping the write. (Caught in a 12-thread stress test: bare
                # os.replace lost ~all writes under concurrent reads on Windows.)
                for attempt in range(10):
                    try:
                        os.replace(tmp, self.filepath)
                        tmp = None
                        break
                    except PermissionError:
                        time.sleep(0.02 * (attempt + 1))
                else:
                    slog.error("[Memory] Failed to save memory: target locked after retries.")
            except Exception as e:
                slog.error(f"[Memory] Failed to save memory: {e}")
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

    # --- PUBLIC TOOLS ---

    def get_full_context(self):
        """
        DEPRECATED — replaced by get_smart_context(). Kept for reference.
        Fetches the Soul (Profile), The Vault (Long Term), and The Stream (Last 10 interactions).
        """
        profile = self.memory.get("user_profile", {})
        project = self.memory.get("project_state", {})
        long_term = self.memory.get("long_term", [])
        episodes = self.memory.get("episodic_log", [])

        # Get last 10 interactions (The Stream)
        recent_history = episodes[-10:] if len(episodes) > 0 else []

        context = "--- LONG-TERM MEMORY CONTEXT ---\n"
        
        # 1. Identity
        context += f"USER: {profile.get('name', 'Unknown')} | ROLE: {profile.get('role', 'User')}\n"
        context += f"TECH STACK: {', '.join(profile.get('preferences', {}).get('tools', []))}\n"
        
        # 2. Project State
        context += f"CURRENT PHASE: {project.get('current_phase', 'Unknown')}\n"
        
        # 3. The Vault (Permanent Facts)
        if long_term:
            context += "\n[PERMANENT KNOWLEDGE VAULT]:\n"
            for fact in long_term:
                context += f"- {fact}\n"

        # 4. The Stream (Recent History)
        if recent_history:
            context += "\n[RECENT CONVERSATION STREAM (Last 10)]:\n"
            for ep in recent_history:
                context += f"- [{ep.get('timestamp', '')[:16]}] {ep.get('summary', '')}\n"

        context += "--------------------------------"
        return context

    def get_smart_context(self, query: str, q_emb, episodic_embeddings: list,
                          include_self_knowledge: bool = True) -> str:
        """
        Smart retrieval: last 3 USER episodic entries + top 2 semantic hits.
        Vault always included. Deduplicates overlaps.
        Autonomous system logs ([AUTONOMOUS] prefix) are excluded from retrieval —
        they pollute user query context with irrelevant system activity.
        q_emb: pre-computed CPU tensor from agent._encode(); avoids calling miniLM here.
        include_self_knowledge=False omits the [SELF KNOWLEDGE] block — the Interpreter
        doesn't need Clara's operational learnings (it only routes), so it is fed a
        context without them to save ~2k tokens/request (the LLM paths still get it).
        """
        import torch

        profile   = self.memory.get("user_profile", {})
        project   = self.memory.get("project_state", {})
        long_term = self.memory.get("long_term", [])
        episodes  = self.memory.get("episodic_log", [])

        # Build a filtered index map: only user-facing interactions.
        # SYSTEM_PREFIXES is the module-level shared constant — "[TASK" prefix-matches
        # every task-state variant the orchestrator writes (B-4 fix).
        user_indices = [
            i for i, ep in enumerate(episodes)
            if not ep.get("summary", "").startswith(SYSTEM_PREFIXES)
        ]

        selected_indices = set()

        # 1. Last 3 user entries by recency
        if user_indices:
            last3 = user_indices[-3:]
            for idx in last3:
                selected_indices.add(idx)

        # 2. Top 2 semantic hits — only over user entries
        if user_indices and episodic_embeddings and len(episodic_embeddings) == len(episodes):
            user_embs = torch.stack([episodic_embeddings[i] for i in user_indices])
            cos_sims = torch.nn.functional.cosine_similarity(q_emb.unsqueeze(0), user_embs)
            top_k = min(2, len(user_indices))
            top_vals, top_idx = cos_sims.topk(top_k)
            # Y3 (Topic-4 Phase-3, DORMANT behind SEMANTIC_RETRIEVAL_V2): relevance-gate the semantic hits.
            # A fixed top-2 with NO floor injects the two least-irrelevant episodes as if relevant even on an
            # off-topic query — noise in every request's context. When the flag is ON, drop hits below the
            # cosine floor; when OFF (default), floor = -1.0 admits every top-k hit, i.e. byte-for-byte the
            # prior always-top-2 behavior (cosine is bounded [-1, 1]).
            _v2 = os.getenv("SEMANTIC_RETRIEVAL_V2", "").strip().lower() in ("on", "1", "true", "yes")
            _floor = float(os.getenv("SEMANTIC_RETRIEVAL_FLOOR", "0.30")) if _v2 else -1.0
            for _val, local_idx in zip(top_vals.tolist(), top_idx.tolist()):
                if _val >= _floor:
                    selected_indices.add(user_indices[local_idx])

        # 3. Build context string — opening with temporal grounding (2026-06-12):
        # Clara gets the clock on EVERY call. Placed here (not the system prompt) on
        # purpose: this block already varies per request, so the per-second timestamp
        # costs nothing extra against the DeepSeek prefix cache, and it reaches BOTH
        # the interpreter (relative-time window math: "9 last night" → hours) and the
        # answer paths. ~50 tokens for permanent time-awareness.
        context = "--- MEMORY CONTEXT ---\n"
        context += self._now_line() + "\n"

        # Identity
        context += f"USER: {profile.get('name', 'Unknown')} | ROLE: {profile.get('role', 'User')}\n"
        context += f"TECH STACK: {', '.join(profile.get('preferences', {}).get('tools', []))}\n"
        context += f"CURRENT PHASE: {project.get('current_phase', 'Unknown')}\n"

        # Response style preference — injected only when non-default
        response_style = profile.get('preferences', {}).get('response_style', 'default')
        style_note = profile.get('preferences', {}).get('style_note', '')
        if response_style and response_style != 'default':
            context += f"RESPONSE STYLE: {response_style}"
            if style_note:
                context += f" ({style_note})"
            context += "\n"

        # Verbatim recent conversation window (Topic 4, Phase 1) — the working-memory
        # tier. Raw last-6 exchanges (user query + Clara's final answer ONLY, never the
        # ReAct loop) so implicit references resolve from what was actually said rather
        # than a lossy summary. Coexists with the summarized [RELEVANT PAST INTERACTIONS]
        # below — recency-verbatim on top, semantic/older summaries beneath.
        recent = self.memory.get("recent_exchanges", [])
        if recent:
            context += (
                "\n[RECENT CONVERSATION — your actual last exchanges with Alkama, "
                "verbatim, oldest first. Use this to resolve implicit references "
                "('it', 'that', 'the same', 'in india') and to hold the thread of "
                "what is being discussed]:\n"
            )
            for ex in recent[-6:]:
                ts = ex.get("timestamp", "")[:16]
                context += f"- [{ts}] Alkama: {ex.get('user', '')}\n"
                context += f"           Clara: {ex.get('clara', '')}\n"

        # Active-discourse state (Topic 4, Phase 2) — salient subjects of the current
        # conversation, most-recent first. Lets implicit references resolve against an
        # explicit list rather than a guess.
        discourse = self.memory.get("discourse_state", [])
        if discourse:
            context += (
                "\n[CURRENTLY DISCUSSING — the salient subjects of this conversation, "
                "most recent first. Resolve implicit references ('it', 'that one', 'the "
                "same') against these before asking]: "
                + " · ".join(discourse) + "\n"
            )

        # Known file system locations
        env = profile.get('environment', {})
        known_locations = env.get('known_locations', {})
        if known_locations:
            context += "\n[KNOWN LOCATIONS]:\n"
            for label, path in known_locations.items():
                context += f"- {label}: {path}\n"

        # Self knowledge — CLARA's operational learnings about her own architecture.
        # Interpreter is fed a context with include_self_knowledge=False (routing doesn't
        # need it); the LLM paths get it via the same block, appended on llm_context.
        if include_self_knowledge:
            context += self._self_knowledge_block()

        # Filesystem map — progressively discovered directory/file tree.
        # CAP the INJECTED serialization (2026-07-09 token-hygiene): the map grows UNBOUNDED as Clara
        # explores, and it's re-sent every DELIBERATE turn — it had crept to ~2.3k tokens/request. The
        # stored tree keeps growing (that's fine, it's her knowledge); only the injected view is bounded.
        fsmap = self.memory.get('filesystem_map', {})
        if fsmap:
            fs_text = self._serialize_filesystem_map(fsmap)
            _FS_MAP_CHAR_CAP = 4000   # ~1000 tokens ceiling for the injected block
            if len(fs_text) > _FS_MAP_CHAR_CAP:
                fs_text = (fs_text[:_FS_MAP_CHAR_CAP].rsplit('\n', 1)[0]
                           + f"\n  [... filesystem map truncated for context — {len(fs_text)} chars total]\n")
            context += "\n[FILE SYSTEM MAP]:\n" + fs_text

        # Vault
        if long_term:
            context += "\n[PERMANENT KNOWLEDGE VAULT]:\n"
            for fact in long_term:
                context += f"- {fact}\n"

        # Selected episodic entries (sorted chronologically)
        if selected_indices:
            context += "\n[RELEVANT PAST INTERACTIONS]:\n"
            for idx in sorted(selected_indices):
                ep = episodes[idx]
                context += f"- [{ep.get('timestamp', '')[:16]}] {ep.get('summary', '')}\n"

        context += "----------------------"

        # Log the full context being passed to Grok — file only, not console
        # Skipping logging for now for verboiseness
        # try:
        #     import logging
        #     flog = logging.getLogger("clara_session")
        #     # Only log to file handlers to keep terminal clean
        #     file_handlers = [h for h in flog.handlers
        #                      if isinstance(h, logging.FileHandler)]
        #     if file_handlers:
        #         record = logging.LogRecord(
        #             name="clara_session", level=logging.DEBUG,
        #             pathname="", lineno=0,
        #             msg=f">> [MEMORY_CONTEXT] Injecting into Grok:\n{context}",
        #             args=(), exc_info=None
        #         )
        #         for h in file_handlers:
        #             h.emit(record)
        # except Exception:
        #     pass

        return context

    @staticmethod
    def _now_line() -> str:
        """Compact one-line temporal grounding for context injection. Deliberately
        local (datetime only) — crud must not import the heavyweight tools module."""
        from datetime import timedelta
        now = datetime.now()
        hour = now.hour
        part = ("early morning" if hour < 6 else "morning" if hour < 12
                else "afternoon" if hour < 17 else "evening" if hour < 21 else "night")
        return (f"[NOW] {now.strftime('%A, %Y-%m-%d')} · {now.strftime('%H:%M')} IST "
                f"({now.strftime('%I:%M %p').lstrip('0')}) · {part} · "
                f"yesterday={(now - timedelta(days=1)).strftime('%a %Y-%m-%d')} · "
                f"tomorrow={(now + timedelta(days=1)).strftime('%a %Y-%m-%d')}")

    def _self_knowledge_block(self) -> str:
        """Serialize active self_knowledge as the [SELF KNOWLEDGE] context block (or '' if empty).
        Split out of get_smart_context so the LLM paths can receive it while the Interpreter does not."""
        sk = self.memory.get('self_knowledge', {})
        sk_lines = []
        # Defensive .get() on every field: this block runs on EVERY request's context, so a single
        # malformed self_knowledge entry (wrong/missing key) must NEVER crash the whole request path.
        # (2026-07-19: an entry with 'problem' instead of 'trigger' KeyError'd every request for a day.)
        for fact in sk.get('architecture_facts', []):
            if fact.get('status') == 'active':
                sk_lines.append(f"  [ARCH] {fact.get('summary','')} — {fact.get('detail','')} "
                                f"[conf:{fact.get('confidence','?')}]")
        for pat in sk.get('failure_patterns', []):
            if pat.get('status') == 'active':
                trig = pat.get('trigger') or pat.get('problem') or pat.get('summary') or ''
                fix = pat.get('correct_approach') or pat.get('method') or ''
                sk_lines.append(f"  [FAIL] Trigger: {trig} | Fix: {fix}")
        for rec in sk.get('recovery_methods', []):
            if rec.get('status') == 'active':
                sk_lines.append(f"  [RECV] {rec.get('problem') or rec.get('trigger') or ''} → "
                                f"{rec.get('method') or rec.get('correct_approach') or ''}")
        if not sk_lines:
            return ""
        return ("\n[SELF KNOWLEDGE — CLARA's operational learnings. CLAUDE.md takes precedence on all "
                "architectural matters]:\n" + "\n".join(sk_lines) + "\n")

    def update_response_style(self, style: str, note: str = "") -> None:
        """
        Update Alkama's response style preference.
        Called from memorize_episode when a style_update is extracted.
        style: e.g. "concise", "detailed", "default"
        note: brief reason e.g. "Alkama said responses were too verbose"
        """
        with self._lock:
            if "preferences" not in self.memory["user_profile"]:
                self.memory["user_profile"]["preferences"] = {}
            self.memory["user_profile"]["preferences"]["response_style"] = style
            self.memory["user_profile"]["preferences"]["style_note"] = note
            self._save_memory()

    def add_episodic_log(self, summary):
        """
        Always saves the summary of the last interaction.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "summary": summary
        }
        with self._lock:
            self.memory["episodic_log"].append(entry)
            self._save_memory()
        slog.info(f"   [Memory] Logged to Stream: {summary[:50]}...")

    def add_episodic_entry(self, summary: str, encode_callback=None):
        """
        Unified episodic write — always writes log entry.
        If encode_callback is provided, also encodes and returns the embedding
        so the caller can append it to episodic_embeddings atomically.
        encode_callback: callable(summary: str) → CPU tensor
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
        }
        with self._lock:
            self.memory["episodic_log"].append(entry)
            self._save_memory()

        if encode_callback is not None:
            try:
                return encode_callback(summary)
            except Exception as e:
                slog.error(f"   [Memory] Embedding encode failed: {e}")
        return None

    def append_recent_exchange(self, user_text: str, clara_text: str, cap: int = 10):
        """Verbatim short-term conversation buffer (Topic 4, Phase 1).

        Stores ONLY the raw user query + Clara's final answer — never the ReAct
        loop, thoughts, or Glints. This is the working-memory tier that lets
        get_smart_context inject the last few exchanges word-for-word, so Clara
        can resolve implicit references ("in india", "the same one") from what
        was actually said rather than from a lossy summary.

        Capped to the last `cap` exchanges (oldest drop off). Independent of
        episodic consolidation so a consolidation parse-failure never costs a turn.
        Each side is length-bounded to keep per-request context cost predictable.
        """
        if not user_text or not clara_text:
            return
        with self._lock:
            buf = self.memory.setdefault("recent_exchanges", [])
            buf.append({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "user": user_text.strip()[:600],
                "clara": clara_text.strip()[:900],
            })
            if len(buf) > cap:
                del buf[:-cap]
            self._save_memory()

    def update_discourse_state(self, entities, cap: int = 8):
        """Active-discourse state (Topic 4, Phase 2) — the salient concrete subjects/topics
        of the current conversation, so implicit references ('it', 'the same one') resolve
        against an explicit list rather than a guess.

        Rolling + most-recent-first: new entities are prepended, deduped case-insensitively,
        and the list is capped — so stale topics naturally fall off the end as the
        conversation moves on. Entities come from the consolidation LLM (memorize_episode).
        """
        new = [e.strip() for e in (entities or []) if isinstance(e, str) and e.strip()]
        if not new:
            return
        with self._lock:
            existing = self.memory.get("discourse_state", [])
            seen = set()
            merged = []
            for e in new + existing:           # new first (most recent), then prior
                k = e.lower()
                if k not in seen:
                    seen.add(k)
                    merged.append(e)
            self.memory["discourse_state"] = merged[:cap]
            self._save_memory()

    def reset_conversation_state(self):
        """Clear ONLY the short-term conversational substrate — recent_exchanges (Phase 1
        verbatim window) + discourse_state (Phase 2 active-discourse tags). Episodic memory,
        the vault, self_knowledge and the filesystem map are untouched. Used by the Coherence
        Drill to isolate scripted dialogues so a prior dialogue's tail cannot forge a referent
        for the next. One atomic save."""
        with self._lock:
            self.memory["recent_exchanges"] = []
            self.memory["discourse_state"] = []
            self._save_memory()
        return {"recent_exchanges": 0, "discourse_state": 0}

    def add_long_term_fact(self, fact):
        """
        Saves a permanent fact to the Vault. Exact string dedup guard.
        """
        with self._lock:
            if fact in self.memory["long_term"]:
                return
            self.memory["long_term"].append(fact)
            self._save_memory()
        slog.info(f"   [Memory] Locked to Vault: {fact}")

    def add_self_knowledge(self, category: str, entry: dict) -> bool:
        """
        Add a self_knowledge entry with dedup guard.
        category: 'architecture_facts' | 'failure_patterns' | 'recovery_methods'
        Returns True if added, False if duplicate.
        """
        with self._lock:
            if 'self_knowledge' not in self.memory:
                self.memory['self_knowledge'] = {
                    'architecture_facts': [], 'failure_patterns': [], 'recovery_methods': []
                }
            cat_list = self.memory['self_knowledge'].setdefault(category, [])
            dedup_key = {
                'architecture_facts': 'summary',
                'failure_patterns': 'trigger',
                'recovery_methods': 'problem'
            }.get(category, 'summary')
            new_val = entry.get(dedup_key, '').lower().strip()
            for existing in cat_list:
                if existing.get(dedup_key, '').lower().strip() == new_val:
                    return False
            cat_list.append(entry)
            self._save_memory()
        slog.info(f">> [Self-Knowledge] Added to {category}: {entry.get(dedup_key, '')[:80]}")
        return True

    def merge_filesystem_path(self, path_str: str, is_file: bool = False, save: bool = True) -> None:
        """
        Add a confirmed file or directory path into the filesystem_map tree.
        path_str: absolute Windows path e.g. 'E:\\ML PROJECTS\\AGENT_ZERO\\api.py'
        is_file: True for a file node (value=None), False for a directory node (value={}).
        Existing nodes are never overwritten — only new nodes are added.
        save=False lets a caller batch many merges (e.g. a parsed list_directory)
        into ONE _save_memory at the end — a full-file fsync per child path was the
        hottest write-amplification source (Brief 36 B-2).
        """
        with self._lock:
            if 'filesystem_map' not in self.memory:
                self.memory['filesystem_map'] = {}
            path_str = path_str.replace('/', '\\').rstrip('\\')
            parts = [p for p in path_str.split('\\') if p]
            if not parts:
                return
            drive = parts[0].rstrip(':')
            rest = parts[1:]
            if not drive or not rest:
                return
            node = self.memory['filesystem_map']
            if drive not in node:
                node[drive] = {}
            node = node[drive]
            for i, part in enumerate(rest):
                is_last = (i == len(rest) - 1)
                if is_last:
                    if part not in node:
                        node[part] = None if is_file else {}
                else:
                    if part not in node or node[part] is None:
                        node[part] = {}
                    node = node[part]
            if save:
                self._save_memory()

    def remove_filesystem_path(self, path_str: str) -> None:
        """
        Remove a stale entry from the filesystem_map when confirmed not found.
        """
        with self._lock:
            path_str = path_str.replace('/', '\\').rstrip('\\')
            parts = [p for p in path_str.split('\\') if p]
            if not parts:
                return
            drive = parts[0].rstrip(':')
            rest = parts[1:]
            fsmap = self.memory.get('filesystem_map', {})
            node = fsmap.get(drive)
            if node is None:
                return
            for part in rest[:-1]:
                if not isinstance(node, dict) or part not in node:
                    return
                node = node[part]
            if isinstance(node, dict) and rest and rest[-1] in node:
                del node[rest[-1]]
                self._save_memory()

    def _serialize_filesystem_map(self, fsmap: dict, indent: int = 0) -> str:
        """
        Compact human-readable serialization of the filesystem_map tree for context injection.
        Directories are shown with trailing backslash; unexplored dirs labeled [unexplored].
        Files in a directory are grouped inline, up to 8 per line with [+N more] overflow.
        """
        MAX_FILES_INLINE = 8
        lines = []
        prefix = '  ' * indent
        for key, val in sorted(fsmap.items()):
            if val is None:
                # file — collected by parent, not emitted here individually
                continue
            if isinstance(val, dict):
                # Drive letters (single char at top level) shown with colon
                display_key = f"{key}:" if (indent == 0 and len(key) == 1) else key
                files = sorted(k for k, v in val.items() if v is None)
                subdirs = {k: v for k, v in val.items() if isinstance(v, dict)}
                if not files and not subdirs:
                    lines.append(f"{prefix}{display_key}\\  [unexplored]")
                else:
                    lines.append(f"{prefix}{display_key}\\")
                    if files:
                        shown = files[:MAX_FILES_INLINE]
                        line = f"{prefix}  " + '  '.join(shown)
                        if len(files) > MAX_FILES_INLINE:
                            line += f"  [+{len(files) - MAX_FILES_INLINE} more]"
                        lines.append(line)
                    if subdirs:
                        lines.append(self._serialize_filesystem_map(subdirs, indent + 1).rstrip('\n'))
        return '\n'.join(lines) + '\n'