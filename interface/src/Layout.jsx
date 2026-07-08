import React, { useState, useEffect, useRef, useCallback, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Terminal, Cpu, Send, Paperclip, X, Zap, Activity,
  Shield, User, Copy, Check, ChevronRight, Radio,
  Layers, Clock, AlertCircle, Smartphone, ThumbsUp, ThumbsDown
} from "lucide-react";
import useClara from "./hooks/useClara";

// ─── tiny hook: copy to clipboard ───────────────────────────────────────────
function useCopy(timeout = 1500) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback((text) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), timeout);
    });
  }, [timeout]);
  return [copied, copy];
}

// ─── Lazy syntax highlighter — react-syntax-highlighter (prism + refractor) was ~70% of the
// 1.03MB main bundle, paid on every load before a single code block existed. Split into its
// own chunk, fetched on the first code block; the fallback renders the code as a plain <pre>
// for the (local, instant) load beat, so nothing ever flashes empty.
const LazyHighlighter = React.lazy(async () => {
  const [{ Prism }, { oneDark }] = await Promise.all([
    import("react-syntax-highlighter"),
    import("react-syntax-highlighter/dist/esm/styles/prism"),
  ]);
  return { default: (props) => <Prism style={oneDark} {...props} /> };
});

const codeBlockStyle = {
  background: "rgba(0,0,0,0.72)",
  border: "1px solid rgba(16,185,129,0.12)",
  borderRadius: "10px",
  fontSize: "12px",
  margin: 0,
  padding: "14px 16px",
  fontFamily: "'JetBrains Mono','Cascadia Code','Fira Code',monospace",
};

// ─── Syntax-highlighted code block with copy button ─────────────────────────
function CodeBlock({ language, children }) {
  const [copied, copy] = useCopy(1500);
  const label = language ? language.toUpperCase() : "CODE";
  return (
    <div className="relative group/code my-2">
      <div className="absolute right-2 top-2 flex items-center gap-2 z-10
        opacity-0 group-hover/code:opacity-100 transition-opacity duration-150">
        <span className="text-[9px] font-mono text-white/20 tracking-widest">{label}</span>
        <button
          onClick={() => copy(children)}
          className="text-[9px] font-mono px-2 py-0.5 rounded
            bg-black/60 border border-white/10
            text-white/30 hover:text-emerald-400 hover:border-emerald-500/30
            transition-colors duration-150"
        >
          {copied ? "COPIED" : "COPY"}
        </button>
      </div>
      <Suspense fallback={
        <pre style={{ ...codeBlockStyle, overflowX: "auto", whiteSpace: "pre",
                      color: "#d4d4d8", fontSize: "12px" }}>{children}</pre>
      }>
        <LazyHighlighter
          language={language || "text"}
          PreTag="div"
          customStyle={codeBlockStyle}
        >
          {children}
        </LazyHighlighter>
      </Suspense>
    </div>
  );
}

// ─── Streaming-markdown guard: a dangling ``` fence mid-stream swallows everything
// after it into one giant code block (layout blowout until the closing fence arrives).
// Close it virtually for the in-flight render only — the final message re-renders clean.
const closeDanglingFence = (text) => {
  const fences = (text.match(/```/g) || []).length;
  return fences % 2 === 1 ? text + "\n```" : text;
};

// ─── Bare-number answers ("479001600.") are valid Markdown for an EMPTY ordered-list item —
// the number becomes a list MARKER rendered outside the content box, i.e. hanging half out of
// the bubble (the recording bug, reproduced live 2026-07-02). Escape the dot so it renders as
// the plain sentence it is. Every FAST numeric compute ends exactly like this.
const sanitizeMarkdown = (t) =>
  /^\s*[\d,]+\.\s*$/.test(t || "") ? t.replace(".", "\\.") : t;

// ─── Shared markdown component overrides ─────────────────────────────────────
const markdownComponents = {
  // passthrough — CodeBlock renders the outer container
  pre: ({ children }) => <>{children}</>,

  // external links must not navigate the SPA away
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
  ),

  code({ className, children }) {
    const match = /language-(\w+)/.exec(className || "");
    const content = String(children);
    // block: has language annotation OR multiple lines (unannotated fenced block)
    if (match || content.includes("\n")) {
      return (
        <CodeBlock language={match?.[1]}>
          {content.replace(/\n$/, "")}
        </CodeBlock>
      );
    }
    // inline code
    return (
      <code className="bg-black/50 text-emerald-300 px-1.5 py-0.5 rounded text-[11px] font-mono">
        {children}
      </code>
    );
  },

  // wrap tables for horizontal scroll on narrow chat panel
  table: ({ children }) => (
    <div className="prose-table-wrap overflow-x-auto my-3 rounded-lg border border-white/6">
      <table>{children}</table>
    </div>
  ),
};

// ─── Ambient timestamp: bare "22:02" made a nudge from LAST WEEK look like it fired two
// minutes ago (the twin-nudge confusion, 2026-07-03) — show the day when it isn't today.
const ambientWhen = (ts) => {
  const s = String(ts);
  const time = s.slice(11, 16);
  const today = new Date().toISOString().slice(0, 10);
  if (s.slice(0, 10) === today) return time;
  const d = new Date(s);
  return isNaN(d) ? time
    : `${d.toLocaleDateString([], { month: "short", day: "numeric" })} · ${time}`;
};

// ─── Mode palette (header chip + per-card badges share it) ───────────────────
const MODE_STYLES = {
  FAST:       { color: "text-amber-400 border-amber-500/30 bg-amber-500/10",      pulse: false },
  CHAT:       { color: "text-blue-400 border-blue-500/30 bg-blue-500/10",         pulse: false },
  DELIBERATE: { color: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10", pulse: true  },
};

// ─── Per-query thought card ───────────────────────────────────────────────────
// Memoized: during token streaming the whole tree re-renders per frame — cards whose
// props didn't change must not pay for it (this was half of the observed panel jitter).
const QueryCard = React.memo(function QueryCard({ card, onToggle }) {
  const isActive = !card.isComplete && !card.isCancelled && !card.isFailed;
  const bodyRef = React.useRef(null);

  // New thoughts land at the bottom of the card's OWN scroll area — follow them there
  // (only while active + only if the reader isn't hovering inside the card body).
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !isActive) return;
    if (el.matches(":hover")) return;
    el.scrollTop = el.scrollHeight;
  }, [card.thoughts.length, isActive]);

  const stateLabel = card.isCancelled ? "CANCELLED"
    : card.isFailed   ? "FAILED"
    : card.isComplete ? "DONE"
    : "PROCESSING";

  const dotColor = isActive
    ? "bg-emerald-400 animate-pulse"
    : (card.isCancelled || card.isFailed) ? "bg-red-400"
    : "bg-emerald-500/40";

  const borderColor = isActive
    ? "border-emerald-500/30 shadow-[0_0_10px_rgba(16,185,129,0.07)]"
    : (card.isCancelled || card.isFailed) ? "border-red-500/20"
    : "border-white/5";

  const stateColor = isActive ? "text-emerald-400/60"
    : (card.isCancelled || card.isFailed) ? "text-red-400/50"
    : "text-white/20";

  return (
    <div className={`
      rounded-xl border mb-2 overflow-hidden transition-all duration-300 bg-black/30
      ${borderColor} ${!isActive ? "opacity-55 hover:opacity-80 transition-opacity" : ""}
    `}>
      {/* header — always visible */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-white/2 transition-colors select-none"
        onClick={() => onToggle(card.messageId)}
      >
        <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${dotColor}`} />
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-mono text-white/55 truncate leading-snug">
            {card.query.slice(0, 50)}{card.query.length > 50 ? "…" : ""}
          </p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[8px] font-mono text-white/20">{card.time}</span>
            <span className={`text-[8px] font-bold font-mono tracking-widest ${stateColor}`}>
              {stateLabel}
            </span>
            {/* per-card routing badge — this card's OWN mode, kept as history */}
            {card.mode && (
              <span className={`text-[8px] font-bold font-mono tracking-wider px-1 py-px rounded border
                ${MODE_STYLES[card.mode]?.color || "text-white/30 border-white/10"}`}>
                {card.escalatedFrom ? `${card.escalatedFrom}→${card.mode}` : card.mode}
              </span>
            )}
            {card.thoughts.length > 0 && (
              <span className="text-[8px] font-mono text-white/15">
                {card.thoughts.length} step{card.thoughts.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
        <ChevronRight
          size={10}
          className={`shrink-0 text-white/20 transition-transform duration-200 ${card.isExpanded ? "rotate-90" : ""}`}
        />
      </div>

      {/* body — expandable. Readability redesign (2026-07-03): the old rows were 10px text at
          ~40% opacity with no hover response — unreadable for anyone actually studying the
          stream. Now: numbered steps, System-vs-Clara distinction, real base contrast, a
          per-row hover that genuinely lights up (CSS-only — memo/jitter safe), roomier rhythm. */}
      {card.isExpanded && (
        <div ref={bodyRef} className="border-t border-white/5 px-2.5 pt-2 pb-2.5 space-y-1 max-h-72 overflow-y-auto scrollbar-thin">
          {card.thoughts.length === 0 ? (
            <p className="text-[10px] text-white/25 font-mono italic py-1">
              {isActive ? "Awaiting thoughts…" : "No thoughts recorded."}
            </p>
          ) : (
            card.thoughts.map((t, i) => {
              const isLast = i === card.thoughts.length - 1;
              const isSystem = t.source === "System";
              const live = isLast && isActive;
              return (
                <div
                  key={i}
                  className={`group/th rounded-md border-l-2 pl-2.5 pr-2 py-1.5 transition-colors duration-150
                    hover:bg-white/4
                    ${live ? "border-emerald-400/70 bg-emerald-500/4"
                           : "border-white/10 hover:border-emerald-500/40"}`}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={`text-[8px] font-bold font-mono tabular-nums ${
                      live ? "text-emerald-400/80" : "text-white/30 group-hover/th:text-emerald-400/60"
                    } transition-colors duration-150`}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-[8px] font-mono text-white/25">{t.time}</span>
                    {isSystem && (
                      <span className="text-[7px] font-mono uppercase tracking-widest px-1 rounded
                        bg-white/5 text-white/35 border border-white/8">sys</span>
                    )}
                    {live && (
                      <span className="text-[7px] font-mono uppercase tracking-widest text-emerald-400/70 animate-pulse">
                        live
                      </span>
                    )}
                  </div>
                  <span className={`block text-[11px] font-mono leading-relaxed whitespace-pre-wrap wrap-break-word
                    transition-colors duration-150
                    ${isSystem
                      ? "text-white/45 italic group-hover/th:text-white/70"
                      : live
                      ? "text-emerald-50/95"
                      : "text-gray-300/80 group-hover/th:text-gray-100"}`}>
                    {t.text}
                  </span>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
});

// ─── Task board card ─────────────────────────────────────────────────────────
const TaskCard = React.memo(function TaskCard({ task, exiting, onCancel }) {
  const isBackground = task.goal.startsWith("[BACKGROUND]") || task.goal.startsWith("[ENVIRONMENT]");
  const cleanGoal = task.goal
    .replace(/^\[BACKGROUND\]\s*/, "")
    .replace(/^\[ENVIRONMENT\]\s*/, "")
    .replace(/^\[AUTONOMOUS\]\s*/, "");

  const stateConfig = {
    pending:   { dot: "bg-amber-400",   border: "border-amber-500/20",   label: "QUEUED"  },
    active:    { dot: "bg-blue-400 animate-pulse", border: "border-blue-500/30", label: "ACTIVE"  },
    running:   { dot: "bg-emerald-400 animate-pulse", border: "border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.15)]", label: "RUNNING" },
    completed: { dot: "bg-emerald-500", border: "border-emerald-500/10", label: "DONE"    },
    failed:    { dot: "bg-red-500",     border: "border-red-500/30",     label: "FAILED"  },
    paused:    { dot: "bg-yellow-400",  border: "border-yellow-500/20",  label: "PAUSED"  },
  };

  const cfg = stateConfig[task.state] || stateConfig.pending;
  const priorityPct = Math.round((task.priority || 0.5) * 100);
  const priorityColor = task.priority >= 0.9 ? "bg-red-500" : task.priority >= 0.5 ? "bg-amber-400" : "bg-blue-400";

  return (
    <div className={`
      task-card relative rounded-lg border p-3 mb-2 overflow-hidden
      ${cfg.border}
      ${isBackground ? "opacity-60" : ""}
      ${exiting ? "task-card-exit" : "task-card-enter"}
      ${task.state === "failed" ? "task-card-shake" : ""}
      bg-black/30 backdrop-blur-sm transition-all duration-300
    `}>
      {/* priority bar */}
      <div className="absolute bottom-0 left-0 h-0.5 w-full bg-white/5">
        <div
          className={`h-full ${priorityColor} transition-all duration-700`}
          style={{ width: `${priorityPct}%` }}
        />
      </div>

      <div className="flex items-start gap-2">
        <span className={`mt-1 shrink-0 w-2 h-2 rounded-full ${cfg.dot}`} />
        <div className="flex-1 min-w-0">
          <p className="text-[11px] text-gray-200 font-mono leading-snug truncate">{cleanGoal}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-[9px] font-bold tracking-widest ${
              task.state === "running" ? "text-emerald-400" :
              task.state === "failed"  ? "text-red-400" :
              task.state === "completed" ? "text-emerald-500/60" : "text-white/30"
            }`}>{cfg.label}</span>
            {task.source === "user" && (
              <span className="text-[9px] text-purple-400/70 font-mono">USER</span>
            )}
          </div>
        </div>
        {onCancel && task.source === "user"
          && (task.state === "running" || task.state === "active" || task.state === "pending") && (
          <button
            onClick={(e) => { e.stopPropagation(); onCancel(task.task_id); }}
            className="shrink-0 mt-0.5 p-0.5 rounded text-white/20
              hover:text-red-400 hover:bg-red-500/10 transition-colors duration-150"
            title="Cancel task"
          >
            <X size={10} />
          </button>
        )}
      </div>
    </div>
  );
});

// ─── Message bubble ──────────────────────────────────────────────────────────
// Memoized; receives replyText (a string) instead of the whole messages array so a token
// flush or hover elsewhere never re-renders settled bubbles (markdown re-parse is the
// expensive part). The old onQuote prop was dead code — quoting works via global mouseup.
const MessageBubble = React.memo(function MessageBubble({ msg, replyText }) {
  const [hovered, setHovered] = useState(false);
  const [copied, copy] = useCopy();
  const isClara = msg.sender === "Clara";
  // Incoming external message (read-only WhatsApp from a third party) — NOT Alkama, NOT Clara.
  // Render distinct + on the left so it can never masquerade as Alkama's own bubble.
  const isIncoming = msg.source === "whatsapp";
  const onLeft = isClara || isIncoming;

  // "[Sender] text" → sender in the header line, clean text in the body.
  let bodyText = msg.text, incomingSender = null;
  if (isIncoming) {
    const m = /^\[([^\]]{1,40})\]\s*/.exec(msg.text || "");
    if (m) { incomingSender = m[1]; bodyText = msg.text.slice(m[0].length); }
  }

  return (
    <div
      className={`flex msg-enter ${onLeft ? "justify-start" : "justify-end"}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className={`relative max-w-[80%] min-w-0 group`}>
        {/* hover actions */}
        <div className={`
          absolute -top-7 ${onLeft ? "left-0" : "right-0"}
          flex items-center gap-1 transition-all duration-150
          ${hovered ? "opacity-100 translate-y-0" : "opacity-0 translate-y-1 pointer-events-none"}
        `}>
          <span className="text-[9px] font-mono text-white/30 px-2">{msg.time}</span>
          {/* Brief 43.3 — source stamp for the unified master console (interface = home, no badge). */}
          {msg.source && msg.source !== "interface" && (
            <span className="text-[8px] font-mono uppercase tracking-wide px-1.5 py-0.5 rounded
              bg-emerald-500/10 border border-emerald-500/25 text-emerald-300/70">
              {msg.source}
            </span>
          )}
          {isClara && (
            <button
              onClick={() => copy(msg.text)}
              className="p-1 rounded bg-black/60 border border-white/10 hover:border-emerald-500/40 transition-colors"
            >
              {copied ? <Check size={10} className="text-emerald-400" /> : <Copy size={10} className="text-white/40" />}
            </button>
          )}
        </div>

        {/* bubble */}
        <div className={`
          p-4 rounded-2xl flex flex-col gap-2 transition-all duration-150
          ${isClara
            ? "bg-linear-to-br from-emerald-950/60 to-black/60 border border-emerald-500/20 text-emerald-50 shadow-[0_0_20px_rgba(16,185,129,0.08)] hover:shadow-[0_0_25px_rgba(16,185,129,0.12)]"
            : isIncoming
            ? "bg-linear-to-br from-amber-950/40 to-black/60 border border-amber-500/30 text-amber-50/90 shadow-[0_0_18px_rgba(245,158,11,0.08)]"
            : "bg-linear-to-br from-[#1c1c1c] to-[#141414] border border-white/8 text-gray-200 hover:border-white/12"
          }
        `}>
          {/* incoming-channel header — makes a third-party WhatsApp message unmistakable */}
          {isIncoming && (
            <div className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-wide text-amber-400/80 -mb-1">
              <Smartphone size={11} /> Incoming · WhatsApp{incomingSender ? ` · ${incomingSender}` : ""}
            </div>
          )}

          {/* image */}
          {msg.image && (
            <img
              src={msg.image}
              alt="Upload"
              className="w-full h-auto max-h-56 object-cover rounded-xl border border-white/10 cursor-zoom-in hover:brightness-110 transition-all"
            />
          )}

          {/* reply attribution */}
          {replyText && (
            <div className="flex items-start gap-2 pb-2 mb-1 border-b border-emerald-500/10">
              <div className="w-0.5 h-full bg-emerald-500/40 rounded-full shrink-0 self-stretch min-h-3" />
              <span className="text-[10px] text-emerald-400/50 font-mono leading-relaxed italic truncate">
                {replyText.slice(0, 60)}{replyText.length > 60 ? "…" : ""}
              </span>
            </div>
          )}

          {/* content — wrap-anywhere so an unbroken path/URL/hash can never punch out of the bubble */}
          {isClara ? (
            <div className="prose prose-invert prose-sm max-w-none leading-relaxed min-w-0 wrap-break-word
              prose-a:text-emerald-400 prose-strong:text-emerald-100 prose-headings:text-white
              prose-p:text-emerald-50/90 prose-li:text-emerald-50/80
              prose-hr:border-white/8 prose-blockquote:not-italic">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {sanitizeMarkdown(bodyText)}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="whitespace-pre-wrap leading-relaxed text-sm min-w-0 wrap-break-word">{bodyText}</p>
          )}
        </div>
      </div>
    </div>
  );
});

// ─── Vitals bar ──────────────────────────────────────────────────────────────
function VitalBar({ label, value, icon: Icon, color = "emerald", warn = 85 }) {
  const pct = parseFloat(value) || 0;
  const isWarn = pct >= warn;
  const barColor = isWarn
    ? "bg-amber-400"
    : color === "blue" ? "bg-blue-400"
    : color === "yellow" ? "bg-yellow-400"
    : "bg-emerald-400";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-white/40">
          <Icon size={10} className={isWarn ? "text-amber-400" : "text-white/30"} />
          <span>{label}</span>
        </div>
        <span className={`text-[10px] font-mono ${isWarn ? "text-amber-400" : "text-white/30"}`}>
          {value}
        </span>
      </div>
      <div className="h-0.75 bg-white/5 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-700 ease-out vital-bar-fill`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

// ─── Main Layout ─────────────────────────────────────────────────────────────
export default function Layout() {
  const [isSidebarOpen, setIsSidebarOpen]     = useState(true);
  const [isNeuralOpen, setIsNeuralOpen]       = useState(true);
  const [viewImage, setViewImage]             = useState(null);
  const [isFocused, setIsFocused]             = useState(false);
  const [soul, setSoul]                       = useState(null);
  const [quotePopup, setQuotePopup]           = useState(null);

  const {
    messages, queryCards, systemLogs, tasks, input, setInput,
    sendMessage, cancelTask, toggleCard, status, selectedImage, setSelectedImage,
    selectedFile, setSelectedFile,
    handleImageUpload, streams, mode, clearHistory, lastTokenUsage,
    claraIsSpeaking,
    ambientFeed, sendAmbientFeedback,
    uploadError, rejectUpload, maxUploadBytes,
  } = useClara();

  const chatEndRef    = useRef(null);
  const chatScrollRef = useRef(null);
  const chatStickRef  = useRef(true);   // stick-to-bottom unless the reader scrolled up
  const neuralListRef = useRef(null);
  const neuralHovRef  = useRef(false);  // never yank the panel while the reader's pointer is in it
  const textareaRef   = useRef(null);
  const streamKeys    = Object.keys(streams).filter(k => streams[k]);

  // soul vitals polling
  useEffect(() => {
    const fetchSoul = () =>
      fetch("http://localhost:8001/soul")
        .then(r => r.json())
        .then(setSoul)
        .catch(() => {});
    fetchSoul();
    const id = setInterval(fetchSoul, 5000);
    return () => clearInterval(id);
  }, []);

  // Smart chat auto-scroll — the old unconditional scrollIntoView fired on EVERY token flush
  // and fought the reader (the observed streaming jitter). Follow the bottom only when the
  // reader is already there; discrete messages get a smooth glide, stream flushes an instant snap.
  useEffect(() => {
    if (chatStickRef.current) chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);
  useEffect(() => {
    if (streamKeys.length && chatStickRef.current) {
      const el = chatScrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;   // rAF-paced already; no smooth-scroll pileup
    }
  }, [streams]);

  // Neural panel: new cards PREPEND (newest on top) — the old code scrolled to the BOTTOM on
  // every thought, dragging the reader away from the live card. Scroll to top on a NEW card
  // only, and never while the pointer is inside the panel.
  useEffect(() => {
    if (!neuralHovRef.current && neuralListRef.current) neuralListRef.current.scrollTop = 0;
  }, [queryCards.length]);

  // auto-expand textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [input]);

  // (Mode now arrives as a structured "mode" WS event from the router — the old effect here
  // text-sniffed thought prose for the words FAST/DELIBERATE, which no emission contained.)

  const handleKeyDown = (e) => {
    // isComposing guard: Enter during IME composition (Hindi/Japanese/…) must commit the
    // composition, not fire the send.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleQuote = (text, sender) => {
    const label = sender === "Clara" ? "[Clara]" : "[Alkama]";
    setInput(prev => `> ${label}: ${text}\n\n${prev}`);
    setQuotePopup(null);
    window.getSelection()?.removeAllRanges();
    textareaRef.current?.focus();
  };

  const modeChip = MODE_STYLES;

  // parse vitals percentages
  const ramPct  = soul ? parseFloat(soul.vitals?.memory_usage)  || 0 : 0;
  const vramPct = soul ? (() => {
    const s = soul.vitals?.gpu || "";
    const m = s.match(/(\d+\.?\d*)GB\s*\/\s*(\d+\.?\d*)GB/);
    return m ? Math.round((parseFloat(m[1]) / parseFloat(m[2])) * 100) : 0;
  })() : 0;
  const cpuPct  = soul ? parseFloat(soul.vitals?.cpu) || 0 : 0;

  return (
    <div className="flex h-screen w-full bg-[#050505] text-gray-200 overflow-hidden"
      onMouseUp={() => {
        const sel = window.getSelection();
        const text = sel?.toString().trim();
        if (!text) { setQuotePopup(null); return; }
        let node = sel.anchorNode;
        while (node && !node.dataset?.msgIndex) node = node.parentElement;
        const sender = node ? messages[parseInt(node.dataset.msgIndex)]?.sender : null;
        const range = sel.getRangeAt(0);
        const rect = range.getBoundingClientRect();
        setQuotePopup({ x: rect.left + rect.width / 2, y: rect.top - 10, text, sender });
      }}
      onClick={(e) => {
        if (!window.getSelection()?.toString().trim()) setQuotePopup(null);
      }}
    >

      {/* ── ZONE A: SIDEBAR ──────────────────────────────────────────────── */}
      <aside className={`
        relative flex-col bg-black/50 border-r border-white/5
        backdrop-blur-xl overflow-hidden transition-all duration-300 ease-in-out hidden md:flex
        ${isSidebarOpen ? "w-72" : "w-0 border-none"}
      `}>
        {/* subtle scanline texture */}
        <div className="absolute inset-0 pointer-events-none opacity-[0.03]"
          style={{ backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.5) 2px, rgba(255,255,255,0.5) 3px)" }}
        />

        {/* header */}
        <div className="p-5 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="relative">
              <Terminal size={18} className="text-emerald-400" />
              <span className="absolute -bottom-0.5 -right-0.5 w-1.5 h-1.5 bg-emerald-500 rounded-full shadow-[0_0_6px_2px_rgba(16,185,129,0.6)] animate-[breathe_2.5s_ease-in-out_infinite]" />
            </div>
            <h1 className="text-sm font-bold text-white tracking-[0.15em] font-mono">C.L.A.R.A.</h1>
          </div>
          <p className="text-[9px] text-emerald-400/40 font-mono tracking-[0.25em] mt-1.5 ml-6.5">
            SYSTEM ONLINE · {soul?.version || "v2.6"}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6 scrollbar-thin">

          {/* identity */}
          {soul && (
            <div className="space-y-2">
              <p className="text-[9px] uppercase tracking-[0.2em] text-white/20 font-mono flex items-center gap-1.5">
                <User size={9} /> Operator
              </p>
              <div className="rounded-xl bg-white/3 border border-white/5 p-3.5 relative overflow-hidden group">
                <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-30 transition-opacity">
                  <Shield size={20} />
                </div>
                <p className="text-base font-semibold text-white font-mono">{soul.identity.name}</p>
                <p className="text-[11px] text-emerald-400/80 mt-0.5">{soul.identity.role}</p>
                <div className="flex items-center gap-2 mt-3 pt-2.5 border-t border-white/5">
                  <span className="text-[9px] text-white/30 font-mono">{soul.identity.location}</span>
                  <span className="w-0.5 h-2.5 bg-white/10 rounded-full" />
                  <span className="text-[9px] text-white/30 font-mono">{soul.identity.clearance}</span>
                </div>
              </div>
            </div>
          )}

          {/* active context — derived from recent thoughts/tasks */}
          <div className="space-y-2">
            <p className="text-[9px] uppercase tracking-[0.2em] text-white/20 font-mono flex items-center gap-1.5">
              <Radio size={9} /> Active Context
            </p>
            <div className="rounded-xl bg-linear-to-br from-emerald-950/20 to-transparent border border-emerald-500/10 p-3 border-l-2 border-l-emerald-500/40">
              {tasks.filter(t => t.state === "running" || t.state === "active").length > 0 ? (
                tasks.filter(t => t.state === "running" || t.state === "active").slice(0, 2).map((t, i) => (
                  <p key={i} className="text-[11px] text-emerald-100/70 font-mono leading-relaxed truncate">
                    {t.goal.replace(/^\[.*?\]\s*/, "").slice(0, 55)}
                    {t.goal.length > 55 ? "…" : ""}
                  </p>
                ))
              ) : (
                <p className="text-[11px] text-white/20 font-mono italic">Standing by</p>
              )}
              {soul?.mission?.phase && (
                <p className="text-[9px] text-white/20 font-mono mt-1.5">{soul.mission.phase}</p>
              )}
            </div>
          </div>

          {/* skills */}
          {soul?.skills?.length > 0 && (
            <div className="space-y-2">
              <p className="text-[9px] uppercase tracking-[0.2em] text-white/20 font-mono flex items-center gap-1.5">
                <Zap size={9} /> Competency Matrix
              </p>
              <div className="flex flex-wrap gap-1.5">
                {soul.skills.map((skill, i) => (
                  <span key={i} className="text-[9px] px-2 py-1 rounded-lg bg-white/4 border border-white/8
                    text-white/40 hover:text-emerald-300 hover:border-emerald-500/30 hover:bg-emerald-500/5
                    transition-all duration-200 cursor-default font-mono">
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          )}

        </div>

        {/* vitals footer */}
        {soul && (
          <div className="p-4 border-t border-white/5 bg-black/30 space-y-3 shrink-0">
            <VitalBar label="CPU" value={`${cpuPct}%`} icon={Cpu} color="emerald" warn={80} />
            <VitalBar label="RAM" value={`${ramPct}%`} icon={Activity} color="blue" warn={90} />
            <VitalBar label="VRAM" value={`${vramPct}%`} icon={Zap} color="yellow" warn={80} />
          </div>
        )}
      </aside>

      {/* ── ZONE B: CHAT ─────────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col relative h-screen overflow-hidden bg-[#080808]">

        {/* header */}
        <header className="h-13 border-b border-white/5 flex items-center justify-between px-4
          bg-[#080808]/90 backdrop-blur-md sticky top-0 z-10 shrink-0">
          <button onClick={() => setIsSidebarOpen(p => !p)}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-white/40 hover:text-white/70">
            <Layers size={18} />
          </button>

          <div className="flex items-center gap-2">
            {/* mode chip — structured router events; an escalation renders its whole arc.
                Visible only while work is actually in flight. */}
            {mode?.mode && (status === "thinking" || status === "typing") && (
              <span className={`text-[9px] font-bold font-mono px-2 py-0.5 rounded border tracking-widest
                ${modeChip[mode.mode]?.color || "text-white/30 border-white/10"}
                ${(modeChip[mode.mode]?.pulse || mode.escalatedFrom) ? "animate-pulse" : ""}
              `}>
                {mode.escalatedFrom ? `${mode.escalatedFrom} → ${mode.mode}` : mode.mode}
              </span>
            )}

            {/* status pill */}
            <span className={`text-[10px] font-bold px-3 py-1 rounded-full border transition-all
              ${status === "thinking" || status === "typing"
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30 animate-pulse"
                : status === "disconnected"
                ? "bg-red-500/10 text-red-400 border-red-500/30"
                : "opacity-0 border-transparent"}`
            }>
              {status === "thinking" ? "PROCESSING" : status === "typing" ? "RESPONDING" :
               status === "disconnected" ? "OFFLINE" : "ONLINE"}
            </span>
          </div>

          <div className="flex items-center gap-1">
            <button onClick={clearHistory}
              className="text-[9px] font-mono px-2 py-1 rounded-lg border border-white/8
              text-white/20 hover:text-red-400 hover:border-red-500/30 transition-all">
              CLEAR
            </button>
            <button onClick={() => setIsNeuralOpen(p => !p)}
              className="p-2 hover:bg-white/5 rounded-lg transition-colors text-purple-400/60 hover:text-purple-400">
              <Cpu size={18} />
            </button>
          </div>
        </header>

        {/* persistent CLARA watermark — fixed behind all content */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-0 select-none">
          <h1 className="text-[11rem] font-black text-white/[0.018] tracking-[0.4em] font-mono">CLARA</h1>
        </div>

        {/* Voice waveform — appears when CLARA is speaking (TTS, incl. F10 hotkey replies) */}
        {claraIsSpeaking && (
          <div className="voice-waveform">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="voice-bar" style={{ animationDelay: `${i * 0.1}s` }} />
            ))}
          </div>
        )}

        {/* messages */}
        <div
          ref={chatScrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            chatStickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
          }}
          className="chat-scroll relative z-10 flex-1 overflow-y-auto px-5 py-6 space-y-5 pb-44 scrollbar-thin"
        >
          {messages.length === 0 && streamKeys.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 select-none">
              <div className="relative flex items-center justify-center">
                {/* outer slow pulse ring */}
                <div className="absolute w-28 h-28 rounded-full border border-emerald-500/8 animate-[breathe_4s_ease-in-out_infinite]" />
                {/* mid ring */}
                <div className="absolute w-20 h-20 rounded-full border border-emerald-500/12 animate-[breathe_4s_ease-in-out_infinite_0.6s]" />
                {/* inner ring */}
                <div className="absolute w-12 h-12 rounded-full border border-emerald-500/20 animate-[breathe_4s_ease-in-out_infinite_1.2s]" />
                {/* name */}
                <h1 className="text-3xl font-black text-white/8 tracking-[0.3em] font-mono z-10">CLARA</h1>
              </div>
              <p className="text-[9px] text-white/12 font-mono tracking-[0.4em] mt-1">READY</p>
            </div>
          ) : (
            messages.map((msg, i) => (
              // messageId alone is NOT unique in the archive (mirrors/tests can share one) —
              // suffix the index; the list is append-only after mount so this stays stable.
              <div key={`${msg.messageId || "m"}-${i}`} data-msg-index={i}>
                <MessageBubble
                  msg={msg}
                  replyText={
                    msg.sender === "Clara" && msg.messageId
                      ? (messages.find(m => m.sender === "User" && m.messageId === msg.messageId)?.text || null)
                      : null
                  }
                />
              </div>
            ))
          )}

          {/* pre-stream breathing — a query is processing but no tokens have arrived yet */}
          {status === "thinking" && streamKeys.length === 0 && (
            <div className="flex justify-start msg-enter">
              <div className="p-4 rounded-2xl bg-linear-to-br from-emerald-950/60 to-black/60
                border border-emerald-500/20 shadow-[0_0_20px_rgba(16,185,129,0.08)]">
                <div className="flex gap-1 items-center py-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-[breathe_1.2s_ease-in-out_infinite]" />
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-[breathe_1.2s_ease-in-out_infinite_0.2s]" />
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-[breathe_1.2s_ease-in-out_infinite_0.4s]" />
                </div>
              </div>
            </div>
          )}

          {/* live streams — ONE bubble per in-flight message (concurrent queries no longer share) */}
          {streamKeys.map(mid => (
            <div key={mid} className="flex justify-start msg-enter">
              <div className="max-w-[80%] min-w-0 p-4 rounded-2xl bg-linear-to-br from-emerald-950/60
                to-black/60 border border-emerald-500/20 shadow-[0_0_20px_rgba(16,185,129,0.08)]">
                <div className="prose prose-invert prose-sm max-w-none leading-relaxed min-w-0 wrap-break-word
                  prose-a:text-emerald-400 prose-strong:text-emerald-100 prose-p:text-emerald-50/90
                  prose-headings:text-white prose-li:text-emerald-50/80">
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                    {sanitizeMarkdown(closeDanglingFence(streams[mid]))}
                  </ReactMarkdown>
                </div>
                <span className="inline-block w-1.5 h-3.5 bg-emerald-400 animate-pulse ml-0.5 align-middle" />
              </div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        {/* input capsule */}
        <div className="absolute bottom-0 left-0 w-full px-5 pb-5 pt-8 z-40
          bg-linear-to-t from-[#080808] via-[#080808]/95 to-transparent">

          {/* active query chips — shows in-flight user tasks with cancel */}
          {tasks.filter(t => t.source === "user" && (t.state === "running" || t.state === "active" || t.state === "pending")).length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {tasks
                .filter(t => t.source === "user" && (t.state === "running" || t.state === "active" || t.state === "pending"))
                .map(t => (
                  <div key={t.task_id} className="flex items-center gap-1.5 px-2.5 py-1
                    rounded-full border border-emerald-500/20 bg-emerald-950/30
                    text-[10px] font-mono text-emerald-300/70 max-w-70">
                    <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                      t.state === "running" ? "bg-emerald-400 animate-pulse" :
                      t.state === "active"  ? "bg-blue-400 animate-pulse" : "bg-amber-400"
                    }`} />
                    <span className="truncate">{t.goal.replace(/^\[.*?\]\s*/, "").slice(0, 40)}{t.goal.length > 40 ? "…" : ""}</span>
                    <button
                      onClick={() => cancelTask(t.task_id)}
                      className="shrink-0 ml-0.5 text-white/25 hover:text-red-400 transition-colors"
                      title="Cancel"
                    >
                      <X size={9} />
                    </button>
                  </div>
                ))
              }
            </div>
          )}

          {/* upload rejection notice (auto-clears) */}
          {uploadError && (
            <div className="mb-2 ml-1 flex items-center gap-2 bg-red-950/60 border border-red-500/30
              rounded-xl px-2.5 py-1.5 w-fit max-w-md msg-enter">
              <AlertCircle size={12} className="text-red-400 shrink-0" />
              <span className="text-[10px] text-red-300/90 font-mono">{uploadError}</span>
            </div>
          )}

          {/* image preview */}
          {selectedImage && (
            <div className="mb-2 ml-1 flex items-center gap-2 bg-black/80 border border-emerald-500/20
              rounded-xl px-2.5 py-1.5 w-fit">
              <img src={selectedImage} alt="Preview" onClick={() => setViewImage(selectedImage)}
                className="h-8 w-8 object-cover rounded-lg border border-white/10 cursor-zoom-in" />
              <span className="text-[10px] text-emerald-400/70 font-mono">Image attached</span>
              <button onClick={() => setSelectedImage(null)}
                className="ml-1 text-white/25 hover:text-white/60 transition-colors">
                <X size={12} />
              </button>
            </div>
          )}

          {/* document preview (PDF/DOCX/XLSX/…) */}
          {selectedFile && (
            <div className="mb-2 ml-1 flex items-center gap-2 bg-black/80 border border-emerald-500/20
              rounded-xl px-2.5 py-1.5 w-fit max-w-xs">
              <Paperclip size={13} className="text-emerald-400/70 shrink-0" />
              <span className="text-[10px] text-emerald-400/70 font-mono truncate">{selectedFile.name}</span>
              <button onClick={() => setSelectedFile(null)}
                className="ml-1 text-white/25 hover:text-white/60 transition-colors shrink-0">
                <X size={12} />
              </button>
            </div>
          )}

          <div className={`
            relative flex items-end gap-2 px-3 py-2.5 rounded-2xl border transition-all duration-300
            ${status === "thinking" || status === "typing"
              ? "bg-emerald-950/20 border-emerald-500/30 shadow-[0_0_40px_-8px_rgba(16,185,129,0.15)]"
              : isFocused
              ? "bg-[#0f0f0f] border-white/12 shadow-[0_0_60px_-15px_rgba(16,185,129,0.08)]"
              : "bg-[#0d0d0d] border-white/6"
            }
          `}>
            <button onClick={() => document.getElementById("file-upload").click()}
              className={`p-2.5 rounded-xl transition-colors shrink-0
                ${selectedImage || selectedFile ? "text-emerald-400 bg-emerald-900/20" : "text-white/30 hover:text-white/60 hover:bg-white/5"}`}>
              <Paperclip size={18} />
            </button>
            <input type="file" id="file-upload" className="hidden"
              accept="image/*,.pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.csv,.txt,.md,.epub,.html,.json,.xml"
              onChange={handleImageUpload} />

            <textarea
              ref={textareaRef}
              name="message"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={e => {
                const items = e.clipboardData?.items;
                if (!items) return;
                for (const item of items) {
                  if (item.type.startsWith("image/")) {
                    e.preventDefault();
                    const file = item.getAsFile();
                    if (file && file.size > maxUploadBytes) {
                      rejectUpload(`Pasted image is ${(file.size / 1048576).toFixed(1)}MB — the limit is 8MB.`);
                      break;
                    }
                    const reader = new FileReader();
                    reader.onload = ev => setSelectedImage(ev.target.result);
                    reader.readAsDataURL(file);
                    break;
                  }
                }
              }}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              placeholder="Message Clara…"
              className="flex-1 bg-transparent text-gray-200 placeholder-white/15 focus:outline-none
                resize-none py-2.5 text-sm leading-relaxed max-h-36 font-[inherit]"
              rows={1}
              style={{ minHeight: "40px" }}
            />

            <button onClick={sendMessage}
              disabled={!input.trim() && !selectedImage && !selectedFile}
              className={`p-2.5 rounded-xl transition-all duration-200 shrink-0
                ${input.trim() || selectedImage || selectedFile
                  ? "bg-emerald-600 text-white shadow-[0_0_20px_rgba(16,185,129,0.35)] hover:bg-emerald-500 hover:shadow-[0_0_30px_rgba(16,185,129,0.5)] active:scale-95"
                  : "bg-white/5 text-white/20 cursor-not-allowed"
                }`}>
              <Send size={18} />
            </button>
          </div>
        </div>
      </main>

      {/* ── ZONE C: NEURAL STREAM ────────────────────────────────────────── */}
      <aside className={`
        flex flex-col border-l border-white/5 bg-[#060606] transition-all duration-300
        ${isNeuralOpen ? "w-80" : "w-0 border-none overflow-hidden"}
      `}>
        <div className="p-4 border-b border-white/5 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 text-purple-400/70">
            <Cpu size={16} className={status === "thinking" ? "animate-[spin_3s_linear_infinite]" : ""} />
            <span className="text-xs font-bold font-mono tracking-widest">NEURAL STREAM</span>
          </div>
        </div>

        <div className="flex-1 overflow-hidden flex flex-col min-h-0">

          {/* ── TOP: TASK BOARD ── */}
          <div className="shrink-0 border-b border-emerald-500/10 px-3 pt-3 pb-2">
            <p className="text-[9px] uppercase tracking-[0.2em] text-white/20 font-mono mb-2 flex items-center gap-1.5">
              <Clock size={9} /> Task Board
            </p>
            <div className="space-y-0 max-h-52 overflow-y-auto scrollbar-thin">
              {tasks.length === 0 ? (
                <p className="text-[10px] text-white/15 font-mono italic py-2">No active tasks</p>
              ) : (
                tasks.slice(-12).map(t => (
                  <TaskCard key={t.task_id} task={t} onCancel={cancelTask} />
                ))
              )}
            </div>
          </div>

          {/* ── AMBIENT FEED (A2, Brief 40 Y1e) — passive novelty nudges + 👍/👎 calibration ── */}
          <div className="shrink-0 border-b border-purple-500/10 px-3 pt-3 pb-2">
            <p className="text-[9px] uppercase tracking-[0.2em] text-white/20 font-mono mb-2 flex items-center gap-1.5">
              <Radio size={9} /> Ambient
            </p>
            <div className="space-y-1.5 max-h-44 overflow-y-auto scrollbar-thin">
              {ambientFeed.length === 0 ? (
                <p className="text-[10px] text-white/15 font-mono italic py-1">Nothing noticed yet</p>
              ) : (
                ambientFeed.map(n => (
                  <div key={n.id} className="rounded-md bg-white/2 border border-white/5 px-2.5 py-2">
                    <p className="text-[11px] text-white/70 leading-snug">{n.remark}</p>
                    <div className="flex items-center justify-between mt-1.5">
                      <span className="text-[8px] uppercase tracking-wider text-purple-400/40 font-mono">
                        {(n.category || "").replace(/_/g, " ")}{n.ts ? " · " + ambientWhen(n.ts) : ""}
                      </span>
                      <div className="flex items-center gap-0.5">
                        <button onClick={() => sendAmbientFeedback(n.id, "up")} title="Useful"
                          className={`p-1 rounded transition-colors ${n.feedback === "up" ? "text-emerald-400" : "text-white/25 hover:text-emerald-400/70"}`}>
                          <ThumbsUp size={11} />
                        </button>
                        <button onClick={() => sendAmbientFeedback(n.id, "down")} title="Not useful"
                          className={`p-1 rounded transition-colors ${n.feedback === "down" ? "text-rose-400" : "text-white/25 hover:text-rose-400/70"}`}>
                          <ThumbsDown size={11} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ── BOTTOM: QUERY CARDS ── */}
          <div
            ref={neuralListRef}
            onMouseEnter={() => { neuralHovRef.current = true; }}
            onMouseLeave={() => { neuralHovRef.current = false; }}
            className="flex-1 overflow-y-auto px-3 py-3 scrollbar-thin min-h-0"
          >
            <p className="text-[9px] uppercase tracking-[0.2em] text-white/20 font-mono mb-2 flex items-center gap-1.5 sticky top-0 bg-[#060606] py-1">
              <AlertCircle size={9} /> Query Log
            </p>

            {queryCards.length === 0 ? (
              <p className="text-[10px] text-white/15 font-mono italic">Idle</p>
            ) : (
              queryCards.map(card => (
                <QueryCard key={card.messageId} card={card} onToggle={toggleCard} />
              ))
            )}

            {/* system connection logs */}
            {systemLogs.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/5 space-y-1">
                {systemLogs.map((log, i) => (
                  <p key={i} className="text-[9px] font-mono text-white/15 pl-2 border-l border-white/8 leading-relaxed">
                    {log.text}
                  </p>
                ))}
              </div>
            )}

            {lastTokenUsage && (
              <div className="token-usage-pill">
                <span className="token-label">Last query</span>
                <span className="token-stat">
                  {lastTokenUsage.total_tokens.toLocaleString()} tokens
                </span>
                <span className="token-divider">·</span>
                <span className="token-stat">
                  {lastTokenUsage.prompt_tokens.toLocaleString()} in
                </span>
                <span className="token-divider">·</span>
                <span className="token-stat">
                  {lastTokenUsage.completion_tokens.toLocaleString()} out
                </span>
                {lastTokenUsage.cached_tokens > 0 && (
                  <>
                    <span className="token-divider">·</span>
                    <span className="token-cached">
                      {lastTokenUsage.cached_tokens.toLocaleString()} cached
                    </span>
                  </>
                )}
              </div>
            )}
            <div className="h-2" />
          </div>
        </div>
      </aside>

      {/* ── QUOTE POPUP ──────────────────────────────────────────────────── */}
      {quotePopup && (
        <button
          className="fixed z-50 text-[10px] font-mono font-bold px-3 py-1.5 rounded-full shadow-xl
            -translate-x-1/2 -translate-y-full
            bg-emerald-600/95 text-white border border-emerald-400/40
            hover:bg-emerald-500 hover:shadow-[0_0_16px_rgba(16,185,129,0.5)]
            transition-all duration-150"
          style={{
            // clamp inside the viewport — a selection at the very top used to push it offscreen
            left: Math.min(Math.max(quotePopup.x, 60), window.innerWidth - 60),
            top: Math.max(quotePopup.y, 34),
          }}
          onMouseDown={e => {
            e.preventDefault();
            handleQuote(quotePopup.text, quotePopup.sender);
          }}
        >
          QUOTE
        </button>
      )}

      {/* ── LIGHTBOX ─────────────────────────────────────────────────────── */}
      {viewImage && (
        <div
          className="fixed inset-0 z-50 bg-black/95 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={() => setViewImage(null)}
        >
          <img src={viewImage} alt="Full"
            className="max-w-full max-h-full rounded-2xl shadow-2xl border border-white/10" />
          <button className="absolute top-5 right-5 text-white/40 hover:text-white transition-colors">
            <X size={28} />
          </button>
        </div>
      )}

    </div>
  );
}
