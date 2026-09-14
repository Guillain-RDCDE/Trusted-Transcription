"""Targeted re-transcription — fix the broken chunk, never the whole file.

When a chunk came back as a prompt echo, a loop or a hole, the
tempting fix is to fall back to a cheaper or older engine for the
entire file. That throws away every good chunk to repair one bad one.
Production rule: **re-transcribe only the broken chunk**, with a
ladder of attempts, and refuse any attempt that is itself broken.

The ladder, in order:

1. **Without the prompt.** The vocabulary prompt is the cause of the
   echo; removing it restores the chunk in the common case.
2. **With the prompt again.** Some failures are transient.
3. **Split into shorter pieces, without the prompt.** A long difficult
   chunk sometimes transcribes fine in halves or thirds.

Every attempt is checked with ``accept`` — by default: not empty, not
degenerate, not an echo of the prompt, and at least a share of the
expected word count when one is known. The first accepted attempt
wins. If all fail, the caller gets ``None`` and decides (keep the
broken chunk visible, or fill from a reference).

Engine-agnostic: the caller passes ``transcribe_fn(start, end, prompt)``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from trusted_transcription.detectors.loop_guard import is_degenerate
from trusted_transcription.detectors.prompt_echo import (
    ECHO_RATIO,
    MIN_CONTENT_WORDS,
    content_words,
    echo_ratio,
)
from trusted_transcription.detectors.reference_deficit import word_count

TranscribeChunkFn = Callable[[float, float, "str | None"], str]
"""``transcribe_fn(start, end, prompt) -> text``. ``prompt`` is None when
the attempt runs without the vocabulary prompt."""

SPLIT_S = 180.0
MIN_EXPECTED_SHARE = 0.55


@dataclass
class Attempt:
    label: str
    prompt_used: bool
    pieces: int
    text: str
    accepted: bool
    reason: str = ""


@dataclass
class RetranscribeResult:
    text: str | None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def repaired(self) -> bool:
        return self.text is not None


def default_accept(
    text: str,
    prompt: str | None,
    expected_words: int | None,
    min_expected_share: float = MIN_EXPECTED_SHARE,
) -> tuple[bool, str]:
    """Is this attempt good enough to replace the broken chunk?"""
    if not text.strip():
        return False, "empty"

    degenerate, why = is_degenerate(text)
    if degenerate:
        return False, f"degenerate: {why}"

    if prompt:
        ratio, count = echo_ratio(text, set(content_words(prompt)))
        if count >= MIN_CONTENT_WORDS and ratio >= ECHO_RATIO:
            return False, f"still an echo of the prompt ({ratio:.0%})"

    if expected_words:
        words = word_count(text)
        if words < expected_words * min_expected_share:
            return False, f"too short: {words} words for {expected_words} expected"

    return True, "accepted"


def retranscribe_chunk(
    start: float,
    end: float,
    transcribe_fn: TranscribeChunkFn,
    prompt: str | None,
    expected_words: int | None = None,
    split_s: float = SPLIT_S,
    accept: Callable[[str, str | None, int | None], tuple[bool, str]] = default_accept,
) -> RetranscribeResult:
    """Run the ladder on one chunk and return the first accepted text."""
    result = RetranscribeResult(text=None)

    ladder: list[tuple[str, str | None, list[tuple[float, float]]]] = [
        ("without_prompt", None, [(start, end)]),
    ]
    if prompt:
        ladder.append(("with_prompt", prompt, [(start, end)]))
    pieces = _split(start, end, split_s)
    if len(pieces) > 1:
        ladder.append(("split_without_prompt", None, pieces))

    for label, used_prompt, spans in ladder:
        text = " ".join(transcribe_fn(a, b, used_prompt).strip() for a, b in spans).strip()
        # Echo is judged against the vocabulary prompt whether or not
        # this attempt used it: an echo without the prompt means the
        # engine memorised it, and the text is still not a transcription.
        accepted, reason = accept(text, prompt, expected_words)
        result.attempts.append(
            Attempt(
                label=label,
                prompt_used=used_prompt is not None,
                pieces=len(spans),
                text=text,
                accepted=accepted,
                reason=reason,
            )
        )
        if accepted:
            result.text = text
            return result

    return result


def _split(start: float, end: float, split_s: float) -> list[tuple[float, float]]:
    if split_s <= 0 or end - start <= split_s:
        return [(start, end)]
    spans: list[tuple[float, float]] = []
    t = start
    while t < end:
        spans.append((t, min(t + split_s, end)))
        t += split_s
    return spans
