# CLARA WhatsApp Watcher — read-only (Brief 45, Phase 1)

The eyes for proactive WhatsApp awareness. Holds a logged-in WhatsApp Web session and **pushes every
incoming message** to the CLARA backend (`/whatsapp_incoming`) the instant it arrives. **Read-only —
it never sends, replies, or marks anything read.** All the judgment (priority, 15s batching, notify
vs hold) lives in CLARA (`core_logic/salience.py` + `core_logic/whatsapp_gate.py`).

## One-time setup (needs you — the QR scan)
```
cd whatsapp_service
npm install                 # downloads whatsapp-web.js + a headless Chromium (a few hundred MB, one time)
node whatsapp_clara.js      # a QR code prints in the terminal
```
Scan the QR from **WhatsApp → Settings → Linked Devices → Link a Device** (exactly like WhatsApp Web).
The session is saved in `./.wwebjs_auth`, so future runs skip the QR.

## Turning it on in CLARA
1. Confirm the watcher prints `... ready (READ-ONLY). Forwarding incoming → ...`.
2. Add to `core_logic/.env`:  `WHATSAPP_ENABLED=1`
3. Restart the CLARA backend. On startup it logs `WhatsApp read-only poller started`.

## What happens to a message (the flow)
```
message arrives → on('message') fires (~instant) → POST /whatsapp_incoming
→ 15s per-sender debounce (rapid-fire one-liners compile into one)
→ MessageGate:  Shobha → SURFACE (alert you now)   |   everyone else → HOLD (archived, no interrupt)
```
- **Shobha** (the only drop-everything sender for the testing phase) → a `whatsapp_alert` over the UI
  WebSocket + a Telegram ping (when Telegram is back) + into the chat feed as a distinct **left-side,
  amber, "Incoming · WhatsApp"** bubble (never your own side).
- **Everyone else (incl. spam)** → **HELD QUIETLY**: written to a SEPARATE archive
  (`conversations/whatsapp_held.jsonl`, capped at 500), **never shown in the chat, never broadcast,
  no interrupt**. Review them on demand by asking Clara **"what did I miss on WhatsApp?"** (the
  `whatsapp_missed` tool reads the held archive, grouped by sender). This is the faithful version of
  "only Shobha breaks through" — held messages stay out of the chat even on reload.
- Roundtrip for a surfaced message: **seconds**, well under a minute.

## Editing the roster / windows
In `core_logic/whatsapp_gate.py`:
- `PERSON_MAP` — who breaks through (`{"shobha": 1.0}`). Substring-matched, so a saved contact name or
  `+91…(Shobha)` resolves.
- `BATCH_WINDOW_S` (15s) and `PER_SENDER_WINDOWS` (e.g. a snappier window for Shobha).

## Risk / kill switch
- Read-only = no outbound, so no ban-risk from sending and no leakage of *your* data to anyone.
- The one external egress is CLARA's own LLM judgment (DeepSeek) on the ambiguous slice — same trust as
  any Clara query (accepted).
- **Kill switch:** stop this `node` process, or unset `WHATSAPP_ENABLED` and restart the backend.

## Status (2026-06-19)
Code complete; **not yet live** — needs the `npm install` + your QR scan above (couldn't be done from
the agent). The CLARA-side (endpoint, gate, batcher, poller) is built and unit-tested; the poller is
dormant until `WHATSAPP_ENABLED` is set.
