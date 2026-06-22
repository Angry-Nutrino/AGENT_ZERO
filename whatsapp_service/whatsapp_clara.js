// whatsapp_clara.js — READ-ONLY WhatsApp watcher for CLARA (Brief 45, Phase 1).
//
// Holds a logged-in WhatsApp Web session (whatsapp-web.js / Puppeteer) and PUSHES each INCOMING
// message to CLARA's backend at /whatsapp_incoming the instant it arrives (event-driven, not polling).
// READ-ONLY: it never sends, replies, or marks-read. The priority/batching/notify logic all lives in
// CLARA (salience.py + whatsapp_gate.py); this is just the eyes.
//
// SETUP (run once, in this folder):
//   npm install
//   node whatsapp_clara.js        // a QR code prints — scan it from WhatsApp > Linked Devices (once).
// The session persists in ./.wwebjs_auth, so future runs skip the QR. Stop with Ctrl+C.
// Then set WHATSAPP_ENABLED=1 in core_logic/.env and restart the CLARA backend to turn the poller on.
//
// Ban-risk note (Alkama accepted): reading is low-risk; this service never sends, so the risky surface
// (automated outbound) is absent in Phase 1.

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');

const BACKEND = process.env.CLARA_BACKEND || 'http://localhost:8001/whatsapp_incoming';

const client = new Client({
  authStrategy: new LocalAuth(),            // persists the session in ./.wwebjs_auth
  puppeteer: { headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] },
});

client.on('qr', (qr) => {
  console.log('Scan this QR from WhatsApp > Settings > Linked Devices (one time):');
  qrcode.generate(qr, { small: true });
});

client.on('ready', () => console.log('CLARA WhatsApp watcher ready (READ-ONLY). Forwarding incoming → ' + BACKEND));
client.on('auth_failure', (m) => console.error('auth failure:', m));
client.on('disconnected', (r) => console.warn('disconnected:', r, '— restart the service to re-link.'));

client.on('message', async (msg) => {
  try {
    // Only genuine incoming chats — skip status broadcasts and your own messages.
    if (msg.from === 'status@broadcast' || msg.fromMe) return;
    let sender = msg.from;
    try {
      const c = await msg.getContact();
      sender = c.pushname || c.name || c.number || msg.from;
    } catch (_) {}
    await axios.post(BACKEND, { sender: String(sender), text: String(msg.body || '') }, { timeout: 8000 });
  } catch (e) {
    // CLARA backend may be down — drop quietly; this service must never crash on a forward failure.
    console.warn('forward failed (backend up on :8001?):', e.message);
  }
});

client.initialize();
