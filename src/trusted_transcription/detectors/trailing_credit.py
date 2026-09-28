"""Detect a trailing credit — a short last segment after a long silence.

The phrase lists catch the credits they know. This catches the shape
of the event, whatever the words: a recording ends, several seconds of
nothing follow, and the engine returns one short segment at the very
end. On the public corpus the reader's closing words are followed by
ten seconds of silence, then "Sous-titres réalisés par la communauté
d'Amara.org" — while the three chapters that end on the reader's own
"Fin de …" have gaps of one or two seconds.

Only the last segment is considered: a long pause in the middle of a
dictation is a pause, not a credit.
"""

from __future__ import annotations

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

MIN_GAP_S = 5.0
"""Silence before the last segment. Closing words follow the previous
sentence within a breath or two; a credit comes after the reader stops."""

MAX_WORDS = 8
"""A credit is a line, not a paragraph."""


class TrailingCreditDetector:
    name = "trailing_credit"

    def __init__(self, min_gap_s: float = MIN_GAP_S, max_words: int = MAX_WORDS):
        self.min_gap_s = min_gap_s
        self.max_words = max_words

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        segments = transcript.segments
        if len(segments) < 2:
            return []
        last, before = segments[-1], segments[-2]
        gap = last.start - before.end
        words = len(last.text.split())
        if gap < self.min_gap_s or words == 0 or words > self.max_words:
            return []
        return [
            HallucinationFlag(
                detector=self.name,
                severity=Severity.WARNING,
                segment_index=len(segments) - 1,
                reason=(
                    f"Short last segment after {gap:.1f}s of silence — "
                    "the shape of a subtitle credit on the trailing silence"
                ),
                evidence={"gap_s": round(gap, 2), "words": words, "text": last.text[:200]},
            )
        ]
