import { useState, useEffect, useRef, useCallback } from 'react';

export default function useClara() {
  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem('clara_messages');
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [queryCards, setQueryCards] = useState([]);
  const [systemLogs, setSystemLogs] = useState([]);
  const [tasks, setTasks]     = useState([]);
  const [input, setInput]     = useState("");
  const [status, setStatus]   = useState("disconnected");
  const [selectedImage, setSelectedImage] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);   // { name, data } — non-image document upload
  // Per-message streaming buffers: { [message_id]: text }. A single global buffer interleaved
  // CONCURRENT queries' tokens into one garbled bubble (observed 2026-07-02 while recording:
  // a FAST answer rendered glued to another task's stream). Keyed by message_id + batched via
  // requestAnimationFrame so a CHAT token flood costs one render per frame, not per token.
  const [streams, setStreams] = useState({});
  const streamBufRef  = useRef({});      // live buffer (mutated per WS message, flushed on rAF)
  const streamRafRef  = useRef(null);
  const completedRef  = useRef(new Set()); // message_ids already resolved — late tokens dropped
  // Routing mode — structured "mode" events from the backend (replaces thought-text sniffing).
  const [mode, setMode] = useState(null);  // { mode: "FAST"|"CHAT"|"DELIBERATE", escalatedFrom? }
  const [lastTokenUsage, setLastTokenUsage] = useState(null);
  // In-interface voice capture (F4 PTT) was removed — the F10 hotkey (own-mic, standalone)
  // is the voice path now. claraIsSpeaking is kept: TTS (including hotkey replies) drives the
  // "Clara is speaking" waveform via speaking_start/stop.
  const [claraIsSpeaking, setClaraIsSpeaking] = useState(false);
  const claraIsSpeakingRef  = useRef(false);
  const [ambientFeed, setAmbientFeed] = useState([]);   // A2 passive ambient nudges (Brief 40 Y1e)
  const socketRef           = useRef(null);
  const retryCountRef       = useRef(0);
  const retryTimerRef       = useRef(null);
  const isMountedRef        = useRef(true);
  const pendingRef          = useRef(new Map());
  const taskIdToMsgRef      = useRef(new Map()); // task_id → message_id

  useEffect(() => {
    // Persist a BOUNDED, image-stripped copy. Base64 images in localStorage blew past quota
    // silently (the catch ate it) and killed persistence entirely; images never survived the
    // /history reseed anyway, so stripping them here is consistent, not a regression.
    try {
      const slim = messages.slice(-200).map(m => (m.image ? { ...m, image: null } : m));
      localStorage.setItem('clara_messages', JSON.stringify(slim));
    } catch {}
  }, [messages]);

  const addMessage = (sender, text, image = null, messageId = null, source = "interface") => {
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sender === "User" && messageId) pendingRef.current.set(messageId, true);
    setMessages(prev => {
      // Dedupe belt: an identical (id, sender, text) arriving twice is a double-delivery
      // (stale socket / repeated broadcast), never a real second message.
      if (messageId) {
        const last = prev[prev.length - 1];
        if (last && last.messageId === messageId && last.sender === sender && last.text === text) return prev;
      }
      // live:true marks messages that arrived DURING this session (vs localStorage/history
      // seeds) — the /history merge may only append these, or stale entries that fell out of
      // the server's window would masquerade as "newer" and corrupt chronological order.
      return [...prev, { sender, text, image, time: timestamp, messageId, source, live: true }];
    });
  };

  const addSystemLog = (text) => {
    setSystemLogs(prev => [...prev.slice(-4), {
      text,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }]);
  };

  const clearHistory = () => {
    setMessages([]);
    localStorage.removeItem('clara_messages');
    // Remember WHEN we cleared, so the /history seed on next mount doesn't resurrect
    // everything the user explicitly cleared (it filters to entries newer than this).
    try { localStorage.setItem('clara_cleared_at', new Date().toISOString()); } catch {}
    streamBufRef.current = {};
    setStreams({});
  };

  // Create a fresh card object (module-level pure function)
  const makeCard = (messageId, query) => ({
    messageId,
    taskId: null,
    query,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    startedAt: Date.now(),          // stale-sweep anchor (12-min client-side ceiling)
    thoughts: [],
    isComplete: false,
    isCancelled: false,
    isFailed: false,
    isExpanded: true,
    manuallyExpanded: false,
  });

  // Collapse all non-pinned cards and prepend a new one.
  // Cap the log at 30 cards — an all-day session used to grow the panel's DOM unboundedly
  // (every old card + thoughts stayed mounted forever).
  const MAX_CARDS = 30;
  const openCard = (card) => {
    setQueryCards(prev => [
      card,
      ...prev.map(c => c.manuallyExpanded ? c : { ...c, isExpanded: false }),
    ].slice(0, MAX_CARDS));
  };

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;
    // Single-socket invariant: a racy reconnect (retry timer firing after a new socket already
    // opened — observed live 2026-07-02 via an HMR remount) left TWO sockets attached, so every
    // broadcast was handled twice → duplicate answer bubbles. Close any predecessor and make
    // every handler self-check that it still belongs to the CURRENT socket.
    if (socketRef.current && socketRef.current.readyState <= WebSocket.OPEN) {
      try { socketRef.current.onclose = null; socketRef.current.close(); } catch {}
    }
    const ws = new WebSocket("ws://localhost:8001/ws");
    socketRef.current = ws;

    ws.onopen = () => {
      if (!isMountedRef.current || socketRef.current !== ws) { try { ws.close(); } catch {} return; }
      clearTimeout(retryTimerRef.current);
      const wasReconnect = retryCountRef.current > 0;
      retryCountRef.current = 0;
      setStatus("connected");
      addSystemLog(wasReconnect ? "Neural Link Re-established." : "Neural Link Established.");
      if (wasReconnect) {
        // Stale-state hygiene: task events during the outage were missed, so the board may
        // show ghosts forever — clear it (live tasks re-announce on their next transition).
        // In-flight cards are kept (broadcasts are global, so answers can still arrive) but
        // get an honest note instead of silently spinning.
        setTasks([]);
        setQueryCards(prev => prev.map(c =>
          (!c.isComplete && !c.isCancelled && !c.isFailed)
            ? { ...c, thoughts: [...c.thoughts, { source: "System", text: "Connection dropped mid-task — the answer may still arrive.", time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }] }
            : c
        ));
      }
    };

    ws.onmessage = (event) => {
      if (!isMountedRef.current || socketRef.current !== ws) return;   // stale socket — drop
      let data;
      try { data = JSON.parse(event.data); } catch { return; }         // malformed frame — drop
      const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      // ── task_event ──────────────────────────────────────────────────────────
      if (data.type === "task_event") {
        const { task_id, goal, state, priority, source, message_id } = data;

        if (message_id && task_id) {
          taskIdToMsgRef.current.set(task_id, message_id);
          setQueryCards(prev => prev.map(c =>
            c.messageId === message_id && !c.taskId ? { ...c, taskId: task_id } : c
          ));
        }

        if (state === "failed") {
          const mid = message_id || taskIdToMsgRef.current.get(task_id);
          if (mid) {
            setQueryCards(prev => prev.map(c => c.messageId === mid ? { ...c, isFailed: true } : c));
            setTimeout(() => {
              setQueryCards(prev => prev.map(c =>
                c.messageId === mid && !c.manuallyExpanded ? { ...c, isExpanded: false } : c
              ));
            }, 2000);
          }
        }

        setTasks(prev => {
          const existing = prev.findIndex(t => t.task_id === task_id);
          const entry = { task_id, goal, state, priority, source };
          if (existing >= 0) {
            const updated = [...prev];
            updated[existing] = entry;
            if (state === "completed" || state === "failed") {
              setTimeout(() => setTasks(p => p.filter(t => t.task_id !== task_id)), 2000);
            }
            return updated;
          }
          return [...prev, entry];
        });
        return;
      }

      // ── task_cancelled ──────────────────────────────────────────────────────
      if (data.type === "task_cancelled") {
        if (data.success) {
          setTasks(p => p.filter(t => t.task_id !== data.task_id));
          const mid = taskIdToMsgRef.current.get(data.task_id);
          if (mid) {
            setQueryCards(prev => prev.map(c => c.messageId === mid ? { ...c, isCancelled: true } : c));
            setTimeout(() => {
              setQueryCards(prev => prev.map(c =>
                c.messageId === mid && !c.manuallyExpanded ? { ...c, isExpanded: false } : c
              ));
            }, 2000);
          }
        }
        return;
      }

      // ── thought ─────────────────────────────────────────────────────────────
      if (data.type === "thought") {
        if (data.message_id) {
          setQueryCards(prev => {
            const idx = prev.findIndex(c => c.messageId === data.message_id);
            if (idx < 0) return prev;
            const updated = [...prev];
            const card = updated[idx];
            const last = card.thoughts[card.thoughts.length - 1];
            let newThoughts;
            if (last && last.source === "Clara" && last.turn_id === data.turn_id) {
              newThoughts = [...card.thoughts.slice(0, -1), { ...last, text: data.content }];
            } else {
              newThoughts = [...card.thoughts, { source: "Clara", text: data.content, time: ts, turn_id: data.turn_id }];
            }
            updated[idx] = { ...card, thoughts: newThoughts };
            return updated;
          });
        }
        setStatus("thinking");
        return;
      }

      // ── status ──────────────────────────────────────────────────────────────
      if (data.type === "status") {
        if (data.message_id) {
          setQueryCards(prev => {
            const idx = prev.findIndex(c => c.messageId === data.message_id);
            if (idx < 0) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              thoughts: [...updated[idx].thoughts, { source: "System", text: data.content, time: ts }],
            };
            return updated;
          });
        }
        setStatus("thinking");
        return;
      }

      // ── stream ───────────────────────────────────────────────────────────────
      if (data.type === "stream") {
        const mid = data.message_id || "_untagged";
        if (completedRef.current.has(mid)) return;   // late token after final_answer — drop
        streamBufRef.current[mid] = (streamBufRef.current[mid] || "") + data.content;
        // rAF-batched flush: a CHAT answer arrives as hundreds of single-token WS messages;
        // rendering each one froze/jittered the tree. One state commit per animation frame.
        if (!streamRafRef.current) {
          streamRafRef.current = requestAnimationFrame(() => {
            streamRafRef.current = null;
            setStreams({ ...streamBufRef.current });
          });
        }
        setStatus("typing");
        return;
      }

      // ── mode — structured routing announcement (replaces thought-text sniffing) ──
      if (data.type === "mode") {
        const m = data.extra || {};
        if (m.mode) {
          setMode({ mode: m.mode, escalatedFrom: m.escalated_from || null });
          // Stamp the owning card too — the header chip is global (most-recent query wins),
          // but each card keeps ITS OWN routing permanently, so the log reads like history.
          if (data.message_id) {
            setQueryCards(prev => prev.map(c =>
              c.messageId === data.message_id
                ? { ...c, mode: m.mode, escalatedFrom: m.escalated_from || null }
                : c
            ));
          }
        }
        return;
      }

      // ── token_usage ──────────────────────────────────────────────────────────
      if (data.type === "token_usage") {
        setLastTokenUsage(data.extra);
        return;
      }

      // ── user_transcript (voice) ───────────────────────────────────────────────
      if (data.type === "user_transcript") {
        addMessage("User", data.content, null, data.message_id, data.source);
        pendingRef.current.set(data.message_id, true);
        openCard(makeCard(data.message_id, data.content));
        setStatus("thinking");
        return;
      }

      // ── speaking ─────────────────────────────────────────────────────────────
      if (data.type === "speaking_start") {
        claraIsSpeakingRef.current = true;
        setClaraIsSpeaking(true);
        return;
      }
      if (data.type === "speaking_stop") {
        claraIsSpeakingRef.current = false;
        setClaraIsSpeaking(false);
        return;
      }

      // ── final_answer ──────────────────────────────────────────────────────────
      if (data.type === "final_answer") {
        const msgId = data.message_id || null;
        addMessage("Clara", data.content, null, msgId, data.source);
        // Retire ONLY this message's stream buffer — a global clear used to kill a
        // concurrent query's in-flight stream the moment any other answer landed.
        const key = msgId || "_untagged";
        completedRef.current.add(key);
        if (completedRef.current.size > 500) {           // bounded — it's a session-lifetime set
          completedRef.current = new Set([...completedRef.current].slice(-250));
        }
        delete streamBufRef.current[key];
        setStreams({ ...streamBufRef.current });
        if (msgId) {
          pendingRef.current.delete(msgId);
          setQueryCards(prev => prev.map(c => c.messageId === msgId ? { ...c, isComplete: true } : c));
          setTimeout(() => {
            setQueryCards(prev => prev.map(c =>
              c.messageId === msgId && !c.manuallyExpanded ? { ...c, isExpanded: false } : c
            ));
          }, 1500);
        }
        if (pendingRef.current.size === 0) setStatus("idle");
        return;
      }

      // ── console_message — live cross-channel mirror (telegram / whatsapp-hold / voice) ──
      // Pushes the exchange into the master console the instant it happens, no /history refresh.
      if (data.type === "console_message") {
        const sender = data.role === "clara" ? "Clara" : "User";
        addMessage(sender, data.content, null, data.message_id || null, data.source || "interface");
        return;
      }

      // ── whatsapp_alert — a surfaced (priority) WhatsApp message. source="whatsapp" makes the
      // bubble render as an INCOMING message (left, amber, badged), never as Alkama's own. Held
      // (non-priority) messages do NOT arrive here — they're archived quietly server-side.
      if (data.type === "whatsapp_alert") {
        addMessage("User", `[${data.sender}] ${data.content}`, null, null, "whatsapp");
        return;
      }
      if (data.type === "ambient_nudge") {
        // Passive — no sound/poke; just prepend to the feed. Newest first, capped.
        setAmbientFeed(prev => [
          { id: data.id, remark: data.remark, category: data.category, ts: data.ts, feedback: null },
          ...prev.filter(n => n.id !== data.id),
        ].slice(0, 50));
        return;
      }
    };

    ws.onerror = () => {};

    ws.onclose = () => {
      if (!isMountedRef.current || socketRef.current !== ws) return;   // a superseded socket closing is not an outage
      setStatus("disconnected");
      const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 30000);
      retryCountRef.current += 1;
      addSystemLog(`Connection lost. Retrying in ${Math.round(delay / 1000)}s… (attempt ${retryCountRef.current})`);
      retryTimerRef.current = setTimeout(() => { if (isMountedRef.current) connect(); }, delay);
    };
  }, []);

  // Brief 43.3 — seed the master console from the server's cross-channel archive (/history):
  // one unified thread of interface + telegram + voice, source-badged. Harness/drill traffic is
  // excluded server-side. SAFE: only replaces the local list when the server actually has data, so
  // it never wipes existing localStorage history to empty (the store starts empty and accrues).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("http://localhost:8001/history?limit=200");
        if (!res.ok) return;
        const data = await res.json();
        // Respect an explicit CLEAR: only seed entries newer than the recorded clear time
        // (otherwise the archive resurrected everything the user just wiped).
        const clearedAt = localStorage.getItem('clara_cleared_at') || "";
        const msgs = (data.messages || [])
          .filter(m => !clearedAt || (m.ts || "") > clearedAt)
          .map(m => ({
            sender: m.role === "clara" ? "Clara" : "User",
            text: m.text,
            image: null,
            time: (m.ts || "").slice(11, 16),
            messageId: m.message_id || null,
            source: m.source || "interface",
          }));
        if (cancelled || msgs.length === 0) return;
        // MERGE instead of replace: a message sent in the seconds before this response landed
        // used to be wiped by the wholesale setMessages. Keep any local message whose
        // messageId the server list doesn't know yet (they're newer than the fetch).
        setMessages(prev => {
          const known = new Set(msgs.map(m => m.messageId).filter(Boolean));
          // Only LIVE messages (arrived this session, after the fetch started) may append —
          // localStorage-seeded entries missing from the server window are OLDER, not newer.
          const localTail = prev.filter(m => m.live && m.messageId && !known.has(m.messageId));
          return [...msgs, ...localTail];
        });
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  // A2 ambient feed (Brief 40 Y1e) — load recent passive nudges on connect, so the feed shows entries
  // surfaced while the UI was closed. Server returns oldest-last; we show newest first.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("http://localhost:8001/ambient_feed?limit=50");
        if (!res.ok) return;
        const data = await res.json();
        // Voted nudges are acknowledged — they never re-enter the feed on reload.
        if (!cancelled) setAmbientFeed((data.feed || []).filter(n => !n.feedback).slice().reverse());
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  // Persistent in-panel expiry (Alkama, 2026-07-08): the backend's /ambient_feed TTL only applies at
  // LOAD time — a session left open without a reconnect would keep stale cards forever. This sweep
  // ages unvoted nudges out of the open panel too. Mirrors AMBIENT_FEED_TTL_H (backend default 12h).
  useEffect(() => {
    const TTL_MS = 12 * 60 * 60 * 1000;
    const sweep = setInterval(() => {
      const cutoff = Date.now() - TTL_MS;
      setAmbientFeed(prev => {
        const kept = prev.filter(n => {
          const t = Date.parse(n.ts || "");
          return Number.isNaN(t) || t >= cutoff;   // unparseable ts: keep (never silently eat a nudge)
        });
        return kept.length === prev.length ? prev : kept;   // same-reference no-op when nothing aged out
      });
    }, 60 * 1000);
    return () => clearInterval(sweep);
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    connect();
    return () => {
      isMountedRef.current = false;
      clearTimeout(retryTimerRef.current);
      if (streamRafRef.current) cancelAnimationFrame(streamRafRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  // Stale sweep — the server guarantees resolution within 600s (Brief 37 timeout), so a card
  // still PROCESSING after 12 minutes will never resolve (backend died / socket black hole).
  // Mark it failed honestly instead of letting it spin forever; unstick the status pill too.
  useEffect(() => {
    const SWEEP_MS = 60_000, STALE_MS = 12 * 60_000;
    const id = setInterval(() => {
      const now = Date.now();
      setQueryCards(prev => {
        let changed = false;
        const next = prev.map(c => {
          if (c.isComplete || c.isCancelled || c.isFailed || !c.startedAt) return c;
          if (now - c.startedAt > STALE_MS) {
            changed = true;
            pendingRef.current.delete(c.messageId);
            return {
              ...c, isFailed: true,
              thoughts: [...c.thoughts, { source: "System", text: "No response within 12 minutes — marked stale.", time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }],
            };
          }
          return c;
        });
        return changed ? next : prev;
      });
      if (pendingRef.current.size === 0) {
        setStatus(s => (s === "thinking" || s === "typing") ? "idle" : s);
      }
    }, SWEEP_MS);
    return () => clearInterval(id);
  }, []);

  // 👍/👎 on an ambient nudge (Brief 40 §4 calibration) — a vote is an ACKNOWLEDGE: the mark
  // flashes on the card for a beat, then the card leaves the feed (2026-07-03, Alkama: "once I
  // give a thumbs up it should disappear"). The vote itself lives on in the ledger for tuning;
  // the feed only shows what's still awaiting his eyes.
  const sendAmbientFeedback = useCallback((id, vote) => {
    setAmbientFeed(prev => prev.map(n => n.id === id ? { ...n, feedback: vote } : n));
    fetch("http://localhost:8001/ambient_feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, vote }),
    }).catch(() => {});
    setTimeout(() => {
      setAmbientFeed(prev => prev.filter(n => n.id !== id));
    }, 450);
  }, []);

  const cancelTask = useCallback((taskId) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: "cancel_task", task_id: taskId }));
    }
  }, []);

  const toggleCard = useCallback((messageId) => {
    setQueryCards(prev => prev.map(c => {
      if (c.messageId !== messageId) return c;
      const newExpanded = !c.isExpanded;
      return { ...c, isExpanded: newExpanded, manuallyExpanded: newExpanded };
    }));
  }, []);

  const sendMessage = () => {
    if (!input.trim() && !selectedImage && !selectedFile) return;
    // Disconnected guard: the old code added the bubble + card + pending state and then
    // silently DROPPED the send — a message that looked sent but never was, spinning forever.
    // Keep the user's draft in the box and say so instead.
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      addSystemLog("Offline — message not sent. It stays in the box; reconnecting…");
      return;
    }
    const messageId = crypto.randomUUID();
    const bubbleText = selectedFile && !input.trim() ? `📎 ${selectedFile.name}` : input;
    addMessage("User", bubbleText, selectedImage, messageId);
    openCard(makeCard(messageId, bubbleText));
    socketRef.current.send(JSON.stringify({
      text: input, image: selectedImage, file: selectedFile, message_id: messageId,
    }));
    setInput("");
    setSelectedImage(null);
    setSelectedFile(null);
    setStatus("thinking");
  };

  // One picker for both: images go to the vision path, everything else (PDF/DOCX/
  // XLSX/PPTX/…) goes to the document path (convert_to_markdown) as { name, data }.
  // 8MB ceiling: base64 inflates ~1.37×, and the WS transport tops out around 16MB —
  // a huge file used to silently kill the connection instead of failing politely.
  const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
  const [uploadError, setUploadError] = useState(null);
  const uploadErrTimerRef = useRef(null);
  const rejectUpload = useCallback((msg) => {
    setUploadError(msg);
    clearTimeout(uploadErrTimerRef.current);
    uploadErrTimerRef.current = setTimeout(() => setUploadError(null), 5000);
  }, []);

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      rejectUpload(`"${file.name}" is ${(file.size / 1048576).toFixed(1)}MB — the limit is 8MB.`);
      e.target.value = "";
      return;
    }
    const reader = new FileReader();
    if (file.type.startsWith("image/")) {
      reader.onloadend = () => setSelectedImage(reader.result);
    } else {
      reader.onloadend = () => setSelectedFile({ name: file.name, data: reader.result });
    }
    reader.readAsDataURL(file);
    e.target.value = "";   // allow re-selecting the same file
  };

  return {
    messages, queryCards, systemLogs, tasks,
    input, setInput, sendMessage, cancelTask, toggleCard, status,
    selectedImage, setSelectedImage, selectedFile, setSelectedFile, handleImageUpload,
    streams, mode, clearHistory, lastTokenUsage,
    claraIsSpeaking,
    ambientFeed, sendAmbientFeedback,
    uploadError, rejectUpload, maxUploadBytes: MAX_UPLOAD_BYTES,
  };
}
