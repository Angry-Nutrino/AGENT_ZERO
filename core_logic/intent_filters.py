"""
intent_filters.py — cheap DETERMINISTIC pre-LLM gates on voice/text input (Brief 43.4, Wave 1).

Philosophy (same as Brief 42 / the priority gate): resolve the obvious cases for FREE before any LLM
call. The first gate here is the "leave it" cancel-filter — Alkama's omnipresence requirement that a
summoned query ending in a cancellation ("you know what, never mind") is REJECTED before process_request,
so it never hits the LLM and Clara just acks ("Got it.").

Pure functions, no I/O, no deps — trivially unit-testable (run `python core_logic/intent_filters.py`).
"""

# Standalone cancellation phrases (whole-utterance) and trailing-cancel phrases.
_CANCEL_PHRASES = (
    "never mind", "nevermind", "leave it", "forget it", "forget about it", "forget that",
    "ignore that", "ignore it", "cancel that", "scratch that", "drop it", "skip it",
    "let it go", "don't worry about it", "dont worry about it", "no never mind", "nothing",
)

# Cues that, just before a trailing cancel phrase, confirm it's a cancellation and not part of a real
# instruction (so "don't leave it open" is NOT cancelled, but "..., actually leave it" IS).
_CANCEL_BOUNDARIES = ("actually", "you know what", "you know, what", "wait", "hmm", "nah", "uh", "um", "on second thought")

_STRIP = " \t\n.!?,;:\"'"


def is_false_request(transcript: str) -> bool:
    """True if the utterance is a cancellation that must be REJECTED before process_request.

    Fires when: (a) the whole utterance IS a cancel phrase ("never mind"), or (b) the utterance ENDS
    with a cancel phrase that is preceded by a cancellation boundary/comma ("search for— you know what,
    leave it"). Deliberately conservative on (b) so a genuine instruction that merely contains the words
    ("remind me not to leave it open") is not falsely cancelled — the boundary requirement guards that.
    """
    if not transcript:
        return False
    t = transcript.strip().lower().strip(_STRIP)
    if not t:
        return False

    # (a) whole utterance is a cancellation
    if t in _CANCEL_PHRASES:
        return True

    # (b) trailing cancellation after a boundary (comma or a cancellation cue word)
    for phrase in _CANCEL_PHRASES:
        if t.endswith(phrase):
            head_raw = t[: len(t) - len(phrase)]      # keep punctuation to detect a comma boundary
            head = head_raw.rstrip(_STRIP + " ")
            if not head:
                return True  # phrase is effectively the whole thing
            # require a cancellation boundary right before the phrase: a comma, or a cue word
            if head_raw.rstrip(" ").endswith(",") or any(head.endswith(b) for b in _CANCEL_BOUNDARIES):
                return True
    return False


if __name__ == "__main__":
    # ── self-test (no backend, no deps) ───────────────────────────────────────
    SHOULD_CANCEL = [
        "never mind",
        "Never mind.",
        "leave it",
        "you know what, leave it",
        "search the codebase for the lock... actually, forget it",
        "umm, never mind",
        "nothing",
        "cancel that",
        "find the file and— on second thought, leave it",
    ]
    SHOULD_NOT_CANCEL = [
        "what's the time right now?",
        "save the file and don't leave it open",          # 'leave it' present, but a real instruction
        "remind me to never give up",
        "search core_logic for asyncio.to_thread",
        "read tests/probe_f.txt and tell me what it says",
        "",
    ]
    fails = []
    for s in SHOULD_CANCEL:
        if not is_false_request(s):
            fails.append(f"  MISSED cancel: {s!r}")
    for s in SHOULD_NOT_CANCEL:
        if is_false_request(s):
            fails.append(f"  FALSE cancel: {s!r}")
    if fails:
        print("intent_filters self-test FAILED:")
        print("\n".join(fails))
        raise SystemExit(1)
    print(f"intent_filters self-test: {len(SHOULD_CANCEL)+len(SHOULD_NOT_CANCEL)} cases passed.")
