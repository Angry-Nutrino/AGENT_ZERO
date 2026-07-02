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
  const [streamingContent, setStreamingContent] = useState("");
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
    try { localStorage.setItem('clara_messages', JSON.stringify(messages)); } catch {}
  }, [messages]);

  const addMessage = (sender, text, image = null, messageId = null, source = "interface") => {
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sender === "User" && messageId) pendingRef.current.set(messageId, true);
    setMessages(prev => [...prev, { sender, text, image, time: timestamp, messageId, source }]);
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
  };

  // Create a fresh card object (module-level pure function)
  const makeCard = (messageId, query) => ({
    messageId,
    taskId: null,
    query,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    thoughts: [],
    isComplete: false,
    isCancelled: false,
    isFailed: false,
    isExpanded: true,
    manuallyExpanded: false,
  });

  // Collapse all non-pinned cards and prepend a new one
  const openCard = (card) => {
    setQueryCards(prev => [
      card,
      ...prev.map(c => c.manuallyExpanded ? c : { ...c, isExpanded: false }),
    ]);
  };

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;
    const ws = new WebSocket("ws://localhost:8001/ws");
    socketRef.current = ws;

    ws.onopen = () => {
      if (!isMountedRef.current) return;
      retryCountRef.current = 0;
      setStatus("connected");
      addSystemLog("Neural Link Established.");
    };

    ws.onmessage = (event) => {
      if (!isMountedRef.current) return;
      const data = JSON.parse(event.data);
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
        setStreamingContent(prev => prev + data.content);
        setStatus("typing");
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
        setQueryCards(prev => [
          makeCard(data.message_id, data.content),
          ...prev.map(c => c.manuallyExpanded ? c : { ...c, isExpanded: false }),
        ]);
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
        if (msgId) {
          pendingRef.current.delete(msgId);
          setQueryCards(prev => prev.map(c => c.messageId === msgId ? { ...c, isComplete: true } : c));
          setTimeout(() => {
            setQueryCards(prev => prev.map(c =>
              c.messageId === msgId && !c.manuallyExpanded ? { ...c, isExpanded: false } : c
            ));
          }, 1500);
        }
        setStreamingContent("");
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
      if (!isMountedRef.current) return;
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
        const msgs = (data.messages || []).map(m => ({
          sender: m.role === "clara" ? "Clara" : "User",
          text: m.text,
          image: null,
          time: (m.ts || "").slice(11, 16),
          messageId: m.message_id || null,
          source: m.source || "interface",
        }));
        if (!cancelled && msgs.length > 0) setMessages(msgs);
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
        if (!cancelled) setAmbientFeed((data.feed || []).slice().reverse());
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    connect();
    return () => {
      isMountedRef.current = false;
      clearTimeout(retryTimerRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  // 👍/👎 on an ambient nudge (Brief 40 §4 calibration) — optimistic UI + POST. Tapping the same vote
  // again clears it (toggle).
  const sendAmbientFeedback = useCallback((id, vote) => {
    setAmbientFeed(prev => prev.map(n => n.id === id ? { ...n, feedback: n.feedback === vote ? null : vote } : n));
    fetch("http://localhost:8001/ambient_feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, vote }),
    }).catch(() => {});
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
    const messageId = crypto.randomUUID();
    const bubbleText = selectedFile && !input.trim() ? `📎 ${selectedFile.name}` : input;
    addMessage("User", bubbleText, selectedImage, messageId);
    openCard(makeCard(messageId, bubbleText));
    socketRef.current?.readyState === WebSocket.OPEN &&
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
  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
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
    streamingContent, clearHistory, lastTokenUsage,
    claraIsSpeaking,
    ambientFeed, sendAmbientFeedback,
  };
}
