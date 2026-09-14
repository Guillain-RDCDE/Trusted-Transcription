"""Detect degenerate output — the engine got stuck.

On difficult audio (noise, a conversation in the background, a long
silence) a transcription model can lock into repetition: one word
thousands of times ("console console console…"), or a short sentence
hundreds of times ("il n'est pas venu"). The output is not empty, it
parses, and every downstream stage faithfully preserves it.

This is different from ``repetition_loop``, which looks for an n-gram
repeated a few times inside a sliding window of segments. That catches
a local stutter. The guard here looks at the **whole text** and asks
whether it is degenerate as a whole:

* one word accounts for more than ``max_word_share`` of all words, or
* a block of ``block_words`` consecutive words repeats identically at
  least ``min_block_repeats`` times.

The thresholds are deliberately high. Formal dictation legitimately
repeats ritual formulas many times ("I state my name, first name and
capacity", "he has no access to") — once per room, per occupant, per
exhibit. A guard tuned to catch three repeats would flag those. The
production calibration that separates a loop from a formula is roughly
an order of magnitude: formulas come back a handful of times, loops a
dozen or hundreds.

``is_degenerate`` is also what the targeted re-transcription uses to
refuse an attempt that came back just as broken.
"""

from __future__ import annotations

import re
from collections import Counter

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

MAX_WORD_SHARE = 0.20
BLOCK_WORDS = 15
MIN_BLOCK_REPEATS = 12
MIN_WORDS = 40
"""Below this many words the shares are meaningless; a two-word
segment is not a loop."""

_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lower-cased alphabetic tokens, apostrophes kept inside a word."""
    return [t.lower() for t in _TOKEN.findall(text)]


def dominant_word(tokens: list[str]) -> tuple[str, float]:
    """The most frequent token and its share of all tokens."""
    if not tokens:
        return "", 0.0
    word, count = Counter(tokens).most_common(1)[0]
    return word, count / len(tokens)


def repeated_block(tokens: list[str], block_words: int = BLOCK_WORDS) -> tuple[str, int]:
    """The most repeated block of ``block_words`` consecutive tokens.

    Blocks are counted at every offset, so a loop that is not aligned
    on a block boundary is still found. Overlapping matches of one
    long loop inflate the count, which is fine: a loop is a loop.
    """
    if len(tokens) < block_words:
        return "", 0
    counts: Counter[tuple[str, ...]] = Counter()
    for i in range(len(tokens) - block_words + 1):
        counts[tuple(tokens[i : i + block_words])] += 1
    block, count = counts.most_common(1)[0]
    return " ".join(block), count


def is_degenerate(
    text: str,
    max_word_share: float = MAX_WORD_SHARE,
    block_words: int = BLOCK_WORDS,
    min_block_repeats: int = MIN_BLOCK_REPEATS,
    min_words: int = MIN_WORDS,
    allowed_phrases: list[str] | None = None,
) -> tuple[bool, str]:
    """Return ``(degenerate, reason)`` for a whole text.

    ``allowed_phrases`` lists ritual formulas that may legitimately
    come back many times; a repeated block is ignored when it is
    contained in one of them.
    """
    tokens = tokenize(text)
    if len(tokens) < min_words:
        return False, ""

    word, share = dominant_word(tokens)
    if share > max_word_share:
        return True, f"one word dominates: '{word}' is {share:.0%} of all words"

    block, count = repeated_block(tokens, block_words)
    if count >= min_block_repeats and not _is_allowed(block, allowed_phrases):
        return True, f"block of {block_words} words repeated {count} times: '{block[:60]}…'"

    return False, ""


def _is_allowed(block: str, allowed_phrases: list[str] | None) -> bool:
    """Is the block part of an allowed refrain?

    A refrain repeated back to back makes blocks that wrap around its
    end ("…of my mission I state my name…"), so the block is searched
    in the phrase doubled, not in the phrase alone.
    """
    if not allowed_phrases:
        return False
    for phrase in allowed_phrases:
        cycle = " ".join(tokenize(phrase))
        if cycle and block in f"{cycle} {cycle}":
            return True
    return False


class DegenerateOutputDetector:
    """Flag a transcript whose text as a whole is a loop."""

    name = "degenerate_output"

    def __init__(
        self,
        max_word_share: float = MAX_WORD_SHARE,
        block_words: int = BLOCK_WORDS,
        min_block_repeats: int = MIN_BLOCK_REPEATS,
        min_words: int = MIN_WORDS,
        allowed_phrases: list[str] | None = None,
    ):
        self.max_word_share = max_word_share
        self.block_words = block_words
        self.min_block_repeats = min_block_repeats
        self.min_words = min_words
        self.allowed_phrases = allowed_phrases or []

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        text = " ".join(seg.text for seg in transcript.segments)
        degenerate, reason = is_degenerate(
            text,
            self.max_word_share,
            self.block_words,
            self.min_block_repeats,
            self.min_words,
            self.allowed_phrases,
        )
        if not degenerate:
            return []
        tokens = tokenize(text)
        word, share = dominant_word(tokens)
        block, count = repeated_block(tokens, self.block_words)
        return [
            HallucinationFlag(
                detector=self.name,
                severity=Severity.CRITICAL,
                segment_index=0,
                reason=f"Degenerate output — {reason}",
                evidence={
                    "dominant_word": word,
                    "dominant_share": round(share, 3),
                    "repeated_block": block,
                    "block_repeats": count,
                    "total_words": len(tokens),
                },
            )
        ]
