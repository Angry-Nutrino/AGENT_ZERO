"""Single source of truth for the DeepSeek model name (G24, 2026-08-01).

The model-name string was hardcoded in 7 call sites (agent.py, interpreter.py, ambient_loop.py) and this
exact class broke every LLM call TWICE — the Grok->DeepSeek migration and the 2026-07-25
`deepseek-chat`->`deepseek-v4-flash` rename — each silently dropping CLARA onto the fallback path for hours.
Centralizing it here makes the next rename a one-line change (set the env var, or change this default).

Override at runtime with the `DEEPSEEK_MODEL` env var (read once at import — entrypoints load .env first).
The default tracks CLARA's current tier (V4-Flash per CLAUDE.md). Behavior-preserving: with no env var set,
this resolves to exactly the string every site used before.
"""
import os

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
