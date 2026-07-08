# Interface audit — 2026-07-02

Full emission→render pipeline audit (agent.py `on_step_update` → api.py WS bridge → useClara.js →
Layout.jsx → index.css), triggered by two bugs Alkama observed while recording. Every case below was
considered against the real code; status tags: **FIXED** (changed today), **HANDLED** (already
correct — verified), **MITIGATED** (risk reduced, residual noted), **DEFERRED** (real, queued),
**ACCEPTED** (known, deliberately not addressed).

The two observed bugs, root-caused:
- **"Answer half outside the bubble"** → a bare numeric answer ending in a period (`479001600.`)
  is valid Markdown for an *empty ordered-list item* — the number becomes a list MARKER, and prose
  markers render outside the content box. Every FAST compute answer has this shape. **FIXED** twice
  over: a bare-number sanitizer escapes the dot (renders as the sentence it is), and
  `list-style-position: inside` guarantees no marker of any real list can ever hang out of a bubble.
  Reproduced live before the fix, verified gone after.
- **"Thought stream jitters while streaming / moving the cursor"** → three compounding causes, all
  **FIXED**: (1) `scrollIntoView` fired on every token/thought and fought the reader's scroll
  position; (2) every CHAT token was its own state update → full-tree re-render per token;
  (3) the neural panel auto-scrolled to the *bottom* on every thought even though new cards prepend
  at the *top*.

---

## A. Streaming & concurrency

1. **Global stream buffer interleaved concurrent queries' tokens into one garbled bubble** — the
   second recording bug's sibling; reproduced in the concurrent validation test. FIXED: per-message
   buffers keyed by `message_id` (`streams` map), one bubble per in-flight stream.
2. **Any `final_answer` cleared every stream** (killing a concurrent query's in-flight text).
   FIXED: only the resolved message's buffer is retired.
3. **Token flood → render thrash** (CHAT = hundreds of single-token WS messages). FIXED:
   requestAnimationFrame-batched flush — one commit per frame regardless of token rate.
4. **Late tokens after `final_answer`** resurrecting a ghost stream bubble. FIXED: `completedRef`
   set drops them (bounded at 500 ids).
5. **Unclosed ``` fence mid-stream** swallows all subsequent text into a giant code block
   (layout blowout until the closing fence arrives). FIXED: `closeDanglingFence` virtually closes
   an odd fence count for the in-flight render only.
6. **Bare-number-as-ordered-list** (see header). FIXED (sanitizer + CSS).
7. **Partial table/emphasis mid-stream re-parsing** (table flickers while rows stream). MITIGATED
   by rAF batching; brief re-layout is inherent to progressive markdown. ACCEPTED residual.
8. **Two answers for one query rendered simultaneously** (stream bubble + final bubble in the same
   frame). HANDLED: final_answer appends the message and retires the stream in one state pass.
9. **`stream` without `message_id`** (defensive). HANDLED: falls into an `_untagged` bucket rather
   than being lost or crashing.
10. **Concurrent DELIBERATE + FAST both streaming** — each now gets its own bubble in arrival
    order. FIXED (validated live with the factorial-during-search test).

## B. WebSocket lifecycle & reconnect

11. **Double-socket after racy reconnect → every broadcast handled twice (duplicate bubbles).**
    Observed LIVE during validation (HMR remount left the old retry timer alive; a production
    backend restart can do the same). FIXED: single-socket invariant — `connect()` closes any
    predecessor, and `onopen`/`onmessage`/`onclose` all self-check `socketRef.current === ws`
    before acting.
12. **Duplicate delivery belt-and-braces**: identical (id, sender, text) arriving consecutively is
    dropped in `addMessage`. FIXED.
13. **Malformed WS frame** crashing the handler (`JSON.parse` unguarded). FIXED: try/catch, drop.
14. **Ghost task cards after an outage** (missed transition events → stuck RUNNING forever).
    FIXED: task board cleared on reconnect; live tasks re-announce on their next transition.
15. **Cards stuck PROCESSING forever after a dead backend.** FIXED: 12-minute client-side stale
    sweep (server guarantees resolution in 600s) marks them failed with an honest note and
    unsticks the status pill.
16. **In-flight card across a reconnect** — broadcasts are global, so the answer may still arrive.
    HANDLED: cards annotated "connection dropped mid-task — the answer may still arrive" instead
    of being killed prematurely.
17. **Retry backoff** 1s→30s cap with attempt counter in system log. HANDLED (pre-existing).
18. **Send while disconnected silently dropped the message** while still rendering the bubble +
    card + pending state (looked sent, never was — spun forever). FIXED: blocked with a visible
    "Offline — message not sent" note; the draft stays in the box.
19. **Retry timer surviving into a healthy connection.** FIXED: cleared in `onopen`.
20. **Unmount during streaming** leaking the rAF. FIXED: `cancelAnimationFrame` in cleanup.

## C. History, persistence & seeding

21. **/history wholesale-replaced local state after mount** — a message sent in the fetch window
    was wiped. FIXED: merge — server list is the base; only `live` (this-session) messages append.
22. **Merge-order corruption**: localStorage entries that fell out of the server's 200-window
    masqueraded as "newer" and appended at the bottom (observed live: ancient messages below
    today's). FIXED: the `live` flag — seeded entries never re-append.
23. **CLEAR resurrection**: the archive reseeded everything the user explicitly cleared on next
    load. FIXED: `clara_cleared_at` timestamp; the seed filters to entries newer than it.
24. **localStorage quota death**: base64 images persisted per message until quota errors silently
    killed ALL persistence. FIXED: persist last 200 messages, images stripped (consistent — the
    /history reseed never restored images anyway).
25. **Corrupt localStorage JSON** on load. HANDLED (pre-existing try/catch → empty).
26. **Duplicate React keys from archive rows sharing a message_id** (old mirror/test traffic) —
    console error, potential wrong-bubble reuse. Observed live in console. FIXED: index-suffixed
    keys (list is append-only after mount, so stable).
27. **whatsapp_alert bubbles have no message_id** — dedupe/key safety. HANDLED via index-suffix
    keys + reload reseeds from the archive.
28. **History fetch failing entirely** (backend down at mount). HANDLED: silent catch, localStorage
    view stands.

## D. Rendering & layout

29. **Unbroken long strings (paths/URLs/hashes) punching out of bubbles.** FIXED: `wrap-break-word`
    + `min-w-0` on bubble content (Clara prose, user text, thought text).
30. **List markers outside the bubble** (any real ordered/unordered list). FIXED (CSS inside
    positioning + inline `li > p`).
31. **Wide tables** — HANDLED (pre-existing `.prose-table-wrap` horizontal scroll), verified the
    streaming bubble uses the same components.
32. **Wide code blocks** — HANDLED (`.prose pre` overflow-x) + bubble `min-w-0` added so the flex
    chain can actually shrink.
33. **Raw HTML in answers** — HANDLED: ReactMarkdown escapes by default (no rehype-raw); renders as
    text, no injection.
34. **Markdown links navigated the SPA away in-tab.** FIXED: `target="_blank" rel="noopener"`.
35. **Content hidden behind the input capsule** when textarea grows + task chips + file previews
    stack. MITIGATED: `pb-36 → pb-44`; extreme stacking may still overlap. ACCEPTED residual.
36. **Browser native scroll-anchoring fighting managed scrolling** (micro-jumps during streaming).
    FIXED: `overflow-anchor: none` on the chat region.
37. **Scrollbar appearing/disappearing shifting layout.** FIXED: `scrollbar-gutter: stable`.
38. **`scroll-smooth` on the container made every programmatic + content scroll animate** (queued
    smooth scrolls = jitter). FIXED: removed; smooth applied per-call for discrete messages only.
39. **JetBrains Mono referenced but never loaded** — silent fallback to arbitrary local fonts.
    FIXED: deterministic local-first stack (Cascadia ships with Win11; no network font dependency).
40. **Page title "interface".** FIXED: "C.L.A.R.A.".
41. **Empty-state condition** referenced the old global stream. FIXED for the streams map.
42. **Images use `object-cover`** (tall screenshots crop in-bubble). ACCEPTED: lightbox shows full;
    cover keeps the feed tidy.
43. **WhatsApp `[Sender]` prefix rendered as raw text in the bubble.** FIXED (polish): sender moves
    into the "Incoming · WhatsApp · <name>" header; body renders clean.
44. **Reply-attribution truncation** at 60 chars. HANDLED (pre-existing, verified).
45. **Very long single answers** (10k+ chars) — single markdown parse, no virtualization. ACCEPTED
    at current scale (parse is one-off per message; memoization prevents re-parse).

## E. Performance

46. **Full-tree re-render per token** — FIXED: rAF batching (A3) + `React.memo` on MessageBubble,
    QueryCard, TaskCard.
47. **MessageBubble memo was defeated by an inline `onQuote` arrow + the whole `messages` array as
    props** — and `onQuote` was DEAD CODE (quoting works via global mouseup). FIXED: prop removed;
    bubbles receive `replyText` (a string) instead of the array.
48. **Markdown re-parse of every settled bubble on every render.** FIXED by the memoization above.
49. **Hover state re-rendering the world** — hover lives inside the memoized bubble now. FIXED.
50. **Unbounded queryCards DOM growth.** FIXED (2026-07-03): capped at 30 cards, voice path
    unified through the same `openCard`.
51. **Bundle size 1.03MB** (syntax-highlighter dominates). FIXED (2026-07-03): `React.lazy`
    split — initial load 1,030KB → 392KB (−62%); highlighter chunk fetched on first code block
    with a styled `<pre>` fallback.
52. **Soul polling every 5s** — HANDLED (cheap endpoint, silent failure tolerated).

## F. Auto-scroll behavior (the jitter cluster)

53. **Chat scrollIntoView on every token** — FIXED: stick-to-bottom tracking (within 120px) +
    instant `scrollTop` snaps during streaming, smooth glide only for discrete messages.
54. **Reader scrolled up gets yanked to bottom by new content.** FIXED: stickiness respected.
55. **Neural panel scrolled to BOTTOM on every thought while new cards prepend at TOP.** FIXED:
    scrolls to top on new-card only.
56. **Panel yanking while the pointer is inside it** (the recorded jitter moment). FIXED: hover
    guard — never auto-scrolls under the reader's cursor.
57. **New thoughts landing below the fold of a card's own scroll area.** FIXED: cards follow their
    newest thought within themselves, paused while hovered.

## G. Input & interaction

58. **Enter during IME composition** (Hindi/Japanese) fired the send instead of committing the
    composition. FIXED: `isComposing` guard.
59. **Send button disabled state** vs whitespace-only input. HANDLED (pre-existing `.trim()`).
60. **Same-file re-selection** in the picker. HANDLED (pre-existing `e.target.value = ""`).
61. **Paste-image capture.** HANDLED (pre-existing), verified it coexists with document files.
62. **Textarea auto-grow ceiling** (max-h-36 then scrolls). HANDLED.
63. **Rapid double-Enter double-send** — input clears synchronously after the first send; the
    second finds it empty. HANDLED.
64. **Form-field a11y warning** (no name/id — flagged by devtools). FIXED: `name="message"`.
65. **Quote popup pushed offscreen** for selections at the viewport's very top/edges. FIXED:
    clamped into the viewport.
66. **Quote across two bubbles** — attribution follows the anchor node's bubble. ACCEPTED quirk.
67. **File size ceiling for uploads** (multi-MB base64 through WS). FIXED (2026-07-03): 8MB
    client ceiling (picker + paste) with an auto-clearing rejection chip, plus an ~11MB-base64
    server-side belt in `api.py` returning an honest final_answer instead of a transport stall.

## H. Mode chip & status truthfulness

68. **The chip was driven by TEXT-SNIFFING thought prose for the words FAST/DELIBERATE — which no
    emission contained.** It only ever moved when a thought happened to mention a mode word.
    FIXED end-to-end: structured `mode` WS events from the router (agent.py), consumed as state.
69. **FAST→DELIBERATE escalation was invisible** ("Thinking more carefully…" only). FIXED: an
    escalation `mode` event renders the full arc — `FAST → DELIBERATE`, pulsing.
70. **Chip lingering while merely connected** (not working). FIXED: visible only during
    thinking/typing.
71. **Multi-query chip ambiguity** (global chip, concurrent queries flip it). FIXED (2026-07-03):
    per-card mode badges — every query card carries its own FAST/CHAT/DELIBERATE (with escalation
    arrow) permanently; the header chip stays as the global most-recent indicator.
72. **Status pill stuck on "PROCESSING" after orphaned queries.** FIXED via the stale sweep (B15).

## I. Backend emission contracts (verified while auditing)

73. **`send_update` payload shape** ({type, content, turn_id, message_id, extra?}) — consistent
    across all 9 emission sites. HANDLED.
74. **token_usage only for user-origin requests.** HANDLED (pre-existing).
75. **final_answer always broadcast even on timeout/error paths** (600s ceiling produces an honest
    message). HANDLED (Brief 37).
76. **Thought merge by turn_id** (same-turn thoughts replace, not append). HANDLED, verified the
    interleaving with System status entries doesn't corrupt the chain.
77. **mode events wrapped in try/except** — a UI-event failure can never break request processing.
    FIXED (design of the new emission).
78. **user_transcript (voice) creates a card + pending entry** like a typed message. HANDLED.

## J. Trust & edge data

79. **WhatsApp incoming can never masquerade as Alkama's own bubble** (left side, amber, badged).
    HANDLED (pre-existing, verified + sender-header polish added).
80. **Console mirror messages (telegram/voice) with sources badge correctly.** HANDLED, verified
    live with real archive data.
81. **Empty final_answer** ("...") renders a minimal bubble. ACCEPTED.
82. **Ambient feed dedupe by id + cap 50.** HANDLED (pre-existing).
83. **Ambient nudges with missing category/ts.** HANDLED (defensive rendering pre-existing).
84. **Task goals with `[BACKGROUND]`/`[ENVIRONMENT]` prefixes** cleaned + dimmed. HANDLED.
85. **Cancel button only for user-source, live-state tasks.** HANDLED.

## Validation performed (2026-07-02, live)

- `npm run build` green (before and after the full change set).
- Backend booted with the new mode events; `agent.py` parse-checked.
- Live UI session (Chrome DevTools MCP): CHAT round-trip (streaming, reply-attribution, card
  lifecycle, token pill), DELIBERATE round-trip, FAST numeric answer.
- **Both observed bugs reproduced live BEFORE their fixes and verified gone AFTER**: the bare-number
  list-marker overflow (screenshot before/after) and the duplicate-delivery double-socket (console
  errors before, single bubbles after).
- Console check surfaced two additional real defects (duplicate keys, missing field name) — both
  fixed and re-verified.

## Files changed

- `core_logic/agent.py` — mode + escalation events (2 contained emissions).
- `interface/src/hooks/useClara.js` — per-message streams, rAF batching, single-socket invariant,
  dedupe, reconnect hygiene, stale sweep, history merge, cleared_at, bounded persistence,
  disconnected-send guard, mode state.
- `interface/src/Layout.jsx` — memoized components, smart auto-scroll (both panels), per-stream
  bubbles, sanitizers, mode chip, overflow hardening, quote clamp, WhatsApp header polish, IME
  guard, a11y name.
- `interface/src/index.css` — chat-scroll anchoring/gutter, list-inside markers, deterministic
  font stack.
- `interface/index.html` — title.

---

# Round 2 — 2026-07-03 (deferred items closed + readability + ambient truth)

All four DEFERRED items above are now FIXED (statuses flipped in place: #50, #51, #67, #71).
Additional cases found and fixed this round:

86. **Thought-stream unreadable at rest / dead hover** (Alkama: rows highlighted "very low or not
    at all"). FIXED: full redesign — numbered steps (01/02…), System-vs-Clara distinction (`sys`
    tag + italic vs reasoning text), base contrast raised ~40%→80% opacity at 11px (was 10px),
    a per-row hover that genuinely lights up (CSS-only, so memo/jitter-safe), a pulsing `live`
    tag on the active step, roomier row rhythm, card body max-h 52→72.
87. **Ambient twin-nudge illusion** — two identical "brave.exe at 22:00" nudges looked like a
    2-minute duplicate; the ledger proved Jun 25 vs Jun 27 (two days apart) rendered with
    time-only labels. FIXED: `ambientWhen()` shows the day when a nudge isn't from today
    ("Jun 27 · 22:02"), verified on screen.
88. **Identical-remark repetition across days** — the per-session cooldown legitimately re-allows
    a class on later days, but the exact same sentence twice in 3 days is repetition, not
    information. FIXED at the source: `ambient_loop._recent_duplicate()` suppresses an identical
    (class, remark) within 72h pre-emit (validated against the real ledger, both directions).
89. **Ambient category never reached the seeded feed** — entries recorded `class` but the UI (and
    `/ambient_feed`'s raw rows) read `category` → blank labels. FIXED: entries carry both; rows
    recorded before 2026-07-03 remain label-less (dates carry the context).

Validation round 2: builds green ×2; live Chrome session — DELIBERATE round-trip with the new
per-card badge, expanded card showing the numbered/contrast-fixed thought stream, ambient dates
on screen; `ambient_loop` module runs clean with the dedup helper validated in three directions.
