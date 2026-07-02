"""
Telegram bot integration for CLARA.

Uses long-polling (not webhooks) — no public URL or tunnel required.
Processes messages as user_input events through the same pipeline as the web UI.

TelegramNotifier is a standalone utility for proactive messaging.
Any CLARA component can import and call it to push messages to Alkama.
"""

import asyncio
import re
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from .session_logger import slog


# ── Markdown → Telegram MarkdownV2 converter ─────────────────────────────────

def _to_telegram_md(text: str) -> str:
    """
    Convert CLARA's markdown output to Telegram MarkdownV2 format.
    Escapes all special chars, then re-applies bold/italic/code patterns.
    """
    ESCAPE_CHARS = r'_*[]()~`>#+=|{}.!-'

    def escape_plain(s: str) -> str:
        for ch in ESCAPE_CHARS:
            s = s.replace(ch, f'\\{ch}')
        return s

    # Split on code blocks first — preserve them, escape everything else
    parts = re.split(r'(```[\s\S]*?```|`[^`]+`)', text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # Code block or inline code — pass through
            if part.startswith('```'):
                inner = part[3:-3]
                lang_end = inner.find('\n')
                if lang_end > 0:
                    inner = inner[lang_end + 1:]
                result.append(f'```\n{inner}```')
            else:
                inner = part[1:-1].replace('`', '\\`')
                result.append(f'`{inner}`')
        else:
            escaped = escape_plain(part)
            # Re-apply bold (**text** → *text*)
            escaped = re.sub(r'\\\*\\\*(.*?)\\\*\\\*', r'*\1*', escaped)
            # Re-apply italic (*text* → _text_)
            escaped = re.sub(r'\\\*(.*?)\\\*', r'_\1_', escaped)
            result.append(escaped)

    return ''.join(result)


def _split_message(text: str, max_len: int = 4096) -> list:
    """Split a long message into chunks ≤ max_len, breaking at paragraph boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind('\n\n', 0, max_len)
        if split_at == -1:
            split_at = text.rfind('\n', 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return chunks


# ── TelegramNotifier ──────────────────────────────────────────────────────────

class TelegramNotifier:
    """
    Standalone utility for proactive outbound messaging to Alkama.

    Usage from anywhere in the codebase:
        from .telegram_bot import notifier
        await notifier.send("Memory maintenance complete.")

    Configured at bot startup. No-ops gracefully if Telegram is not configured.
    """

    def __init__(self):
        self._bot = None
        self._chat_id: str | None = None

    def configure(self, bot, chat_id: str) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, text: str, parse_markdown: bool = False) -> bool:
        """
        Send a proactive message to Alkama.
        Returns True on success, False on failure (never raises).
        """
        if self._bot is None or self._chat_id is None:
            return False
        try:
            content = _to_telegram_md(text) if parse_markdown else text
            for chunk in _split_message(content):
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2 if parse_markdown else None,
                )
            return True
        except Exception as e:
            slog.warning(f"   [Telegram] Notification send failed ({e}) — retrying plain.")
            # Never lose a message to a formatting error (Brief 36 D-22): retry the
            # ORIGINAL text with no parse_mode.
            try:
                for chunk in _split_message(text):
                    await self._bot.send_message(chat_id=self._chat_id, text=chunk)
                return True
            except Exception as e2:
                slog.warning(f"   [Telegram] Plain retry also failed: {e2}")
                return False


# Module-level singleton — import this from anywhere in the codebase
notifier = TelegramNotifier()


# ── TelegramBot ───────────────────────────────────────────────────────────────

class TelegramBot:
    """
    Manages the Telegram long-polling loop and message handling.

    Receives messages from Alkama's personal chat, routes them through
    CLARA's orchestrator pipeline (identical to the web UI), and sends
    back the final answer.

    Takes orchestrator (not agent) — calls submit_user_event() exactly
    like the WebSocket handler does.
    """

    def __init__(self, orchestrator, token: str, allowed_chat_id: str):
        self._orchestrator = orchestrator
        self._token = token
        self._allowed_chat_id = str(allowed_chat_id)
        self._app: Application | None = None
        # Optional live-console mirror, injected by api.py: on_console(role, text, source).
        # Lets Telegram exchanges appear in the master console WITHOUT a /history refresh.
        self.on_console = None

    async def _mirror(self, role: str, text: str) -> None:
        if self.on_console:
            try:
                await self.on_console(role, text, "telegram")
            except Exception:
                pass

    async def start(self) -> None:
        """Build the Application and start long-polling in the background."""
        self._app = Application.builder().token(self._token).build()

        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        # Voice notes (2026-07-02, Alkama greenlit): registered ONLY when TELEGRAM_VOICE is armed —
        # off = today's behavior (voice notes silently ignored). Transcription is LOCAL (the loaded
        # faster-whisper via voice.transcribe_file; PyAV decodes Telegram's OGG/Opus natively — no
        # ffmpeg binary, and the audio never leaves the machine).
        if os.getenv("TELEGRAM_VOICE", "").strip().lower() in ("on", "1", "true", "yes"):
            self._app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
            slog.info("[Telegram] Voice-note handler ARMED (TELEGRAM_VOICE=on).")

        # Wire the notifier singleton to this bot instance
        notifier.configure(self._app.bot, self._allowed_chat_id)

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(
            poll_interval=1.0,
            timeout=10,
            drop_pending_updates=True,  # discard messages sent while CLARA was offline
        )
        slog.info("[Telegram] Bot started. Polling for messages.")

    async def stop(self) -> None:
        """Gracefully stop polling and shut down."""
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                slog.info("[Telegram] Bot stopped.")
            except Exception as e:
                slog.warning(f"[Telegram] Shutdown warning: {e}")

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Process an incoming Telegram message.

        Security: rejected immediately if sender is not the allowed chat ID.
        Routing: submit_user_event with source="user" — full pipeline, full memory.
        """
        chat_id = str(update.effective_chat.id)

        if chat_id != self._allowed_chat_id:
            slog.warning(f"   [Telegram] Rejected message from unauthorized chat: {chat_id}")
            return

        user_text = update.message.text.strip()
        if not user_text:
            return

        slog.info(f"   [Telegram] Received: {user_text[:80]}")
        await self._process_text(update, context, chat_id, user_text)

    async def _handle_voice(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Voice note → local Whisper STT → the SAME text pipeline (2026-07-02).
        Downloads the OGG/Opus to a temp file, transcribes with the already-loaded model
        (faster-whisper decodes ogg via PyAV — no ffmpeg), echoes the transcript back for
        STT-verification, then routes it exactly like a typed message. Audio never leaves
        the machine; the temp file is deleted in finally."""
        chat_id = str(update.effective_chat.id)
        if chat_id != self._allowed_chat_id:
            slog.warning(f"   [Telegram] Rejected voice note from unauthorized chat: {chat_id}")
            return

        from .voice import get_voice
        v = get_voice()
        if v is None or getattr(v, "_whisper", None) is None:
            await update.message.reply_text(
                "Voice transcription isn't available right now (voice system not loaded).")
            return

        import tempfile
        tmp_path = None
        try:
            tg_file = await context.bot.get_file(update.message.voice.file_id)
            fd, tmp_path = tempfile.mkstemp(prefix="tg_voice_", suffix=".oga")
            os.close(fd)
            await tg_file.download_to_drive(tmp_path)
            slog.info(f"   [Telegram] Voice note received ({update.message.voice.duration}s) — transcribing locally.")
            text = await asyncio.to_thread(v.transcribe_file, tmp_path)
        except Exception as e:
            slog.error(f"   [Telegram] Voice download/STT error: {e}")
            await update.message.reply_text("Couldn't process that voice note. Try again?")
            return
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if not text:
            await update.message.reply_text(
                "I couldn't make out any speech in that voice note.")
            return

        # Echo the transcript so Alkama can verify the STT before trusting the answer.
        try:
            await update.message.reply_text(f'\U0001F3A4 "{text}"')
        except Exception:
            pass
        await self._mirror("user", f"\U0001F3A4 {text}")
        await self._process_text(update, context, chat_id, text, mirrored=True)

    async def _process_text(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
        chat_id: str, user_text: str, mirrored: bool = False
    ) -> None:
        """Shared tail of text + voice handling: mirror, typing indicator, full pipeline, reply."""
        if not mirrored:
            await self._mirror("user", user_text)   # live console mirror (source='telegram')

        # Telegram's "typing" indicator expires after ~5s; refresh it while a long
        # DELIBERATE run is in flight so the phone doesn't look dead (Brief 36 D-21).
        async def _keep_typing():
            try:
                while True:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        typing_task = asyncio.create_task(_keep_typing())

        try:
            # Route through the full orchestrator pipeline — identical to web UI.
            # submit_user_event returns the final answer string directly.
            final_answer = await self._orchestrator.submit_user_event(text=user_text, channel="telegram")

            if not final_answer or not final_answer.strip():
                final_answer = "..."

            typing_task.cancel()
            await self._mirror("clara", final_answer)   # live console mirror (source='telegram')

            # MarkdownV2 first; on a parse failure fall back to PLAIN text so a valid
            # answer is never lost to a formatting error (Brief 36 D-22).
            try:
                tg_text = _to_telegram_md(final_answer)
                for chunk in _split_message(tg_text):
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as fmt_err:
                slog.warning(f"   [Telegram] MarkdownV2 send failed ({fmt_err}) — sending plain.")
                for chunk in _split_message(final_answer):
                    await update.message.reply_text(chunk)

            slog.info(f"   [Telegram] Responded ({len(final_answer)} chars)")

        except Exception as e:
            slog.error(f"   [Telegram] Error processing message: {e}")
            await update.message.reply_text("Something went wrong on my end. Try again.")
        finally:
            typing_task.cancel()
