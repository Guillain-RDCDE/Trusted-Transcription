"""Detect a silent hole by comparing word counts per time chunk.

When two transcriptions of the same audio exist — a second engine, an
earlier pass, a cheaper model kept as a witness — a chunk that came
back with far fewer words than the reference for the **same minutes of
audio** is a hole, whatever its text looks like. The prompt echo of
``prompt_echo.py`` is the usual cause; a dropped API call or a
truncated upload look the same from here.

Two details that came out of the production calibration:

* **Strip inline tags from the reference.** A reference that carries
  ``<photo 12:34>``-style anchors (dozens in a row on a report heavy
  with photos) makes a healthy chunk look like a hole. Tags are not
  words.
* **The ratio is per chunk, not per file.** A lost chunk in the middle
  of a long dictation is invisible in the file-level word rate.

With the tags stripped, healthy chunks sat comfortably above the
threshold and real holes well below it, with no overlap.
"""

from __future__ import annotations

import re

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

CHUNK_S = 540.0
"""Default chunk length — the slice size a production pipeline sends
to an API in one call."""

MIN_RATIO = 0.55
"""Below this share of the reference's words, the chunk is a hole."""

MIN_REFERENCE_WORDS = 30
"""A reference chunk with fewer words than this (silence, tail of the
file) cannot support a ratio."""

_TAG = re.compile(r"<[^<>]{1,40}>")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def strip_tags(text: str) -> str:
    return _TAG.sub(" ", text)


def word_count(text: str) -> int:
    return len(_WORD.findall(strip_tags(text)))


def words_per_chunk(transcript: TranscriptResult, chunk_s: float) -> dict[int, int]:
    """Word count per chunk index, a segment counting where it starts."""
    counts: dict[int, int] = {}
    for seg in transcript.segments:
        index = int(seg.start // chunk_s)
        counts[index] = counts.get(index, 0) + word_count(seg.text)
    return counts


class ReferenceDeficitDetector:
    """Flag chunks whose word count falls short of a reference transcript."""

    name = "reference_deficit"

    def __init__(
        self,
        reference: TranscriptResult,
        chunk_s: float = CHUNK_S,
        min_ratio: float = MIN_RATIO,
        min_reference_words: int = MIN_REFERENCE_WORDS,
    ):
        if chunk_s <= 0:
            raise ValueError("chunk_s must be > 0")
        self.reference = reference
        self.chunk_s = chunk_s
        self.min_ratio = min_ratio
        self.min_reference_words = min_reference_words

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        got = words_per_chunk(transcript, self.chunk_s)
        expected = words_per_chunk(self.reference, self.chunk_s)
        flags: list[HallucinationFlag] = []

        for index in sorted(expected):
            reference_words = expected[index]
            if reference_words < self.min_reference_words:
                continue
            words = got.get(index, 0)
            ratio = words / reference_words
            if ratio >= self.min_ratio:
                continue
            start = index * self.chunk_s
            first_segment = next(
                (i for i, s in enumerate(transcript.segments) if s.start >= start), 0
            )
            flags.append(
                HallucinationFlag(
                    detector=self.name,
                    severity=Severity.CRITICAL,
                    segment_index=first_segment,
                    reason=(
                        f"Chunk {index} ({start:.0f}-{start + self.chunk_s:.0f}s) has "
                        f"{ratio:.0%} of the reference's words — content silently lost"
                    ),
                    evidence={
                        "chunk": index,
                        "chunk_start_s": start,
                        "chunk_end_s": start + self.chunk_s,
                        "words": words,
                        "reference_words": reference_words,
                        "ratio": round(ratio, 3),
                    },
                )
            )
        return flags
