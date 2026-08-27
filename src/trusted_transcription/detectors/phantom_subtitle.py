"""Detect phantom subtitles — training data leaking through.

Whisper was trained partly on subtitle corpora. When it encounters
audio that doesn't match its learned patterns well (noise, music,
non-speech), it falls back to producing fragments from its training
data. These are often well-formed sentences that parse correctly,
carry high confidence, and have nothing to do with the audio.

Unlike silence hallucinations (which happen on quiet audio), phantom
subtitles can appear mid-speech when the model briefly loses track
and fills the gap with memorized text.

Detection: statistical anomaly — a segment whose vocabulary, register,
or topic is sharply different from its neighbors. We measure this
with a simple bag-of-words Jaccard distance.
"""

from __future__ import annotations

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)


def _words(text: str) -> set[str]:
    return {w.lower().strip(".,;:!?\"'()") for w in text.split() if len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class PhantomSubtitleDetector:
    name = "phantom_subtitle"

    def __init__(
        self,
        context_window: int = 5,
        similarity_threshold: float = 0.02,
        min_segment_words: int = 4,
    ):
        self.context_window = context_window
        self.similarity_threshold = similarity_threshold
        self.min_segment_words = min_segment_words

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []
        segments = transcript.segments

        if len(segments) < self.context_window * 2 + 1:
            return flags

        for i in range(self.context_window, len(segments) - self.context_window):
            seg_words = _words(segments[i].text)
            if len(seg_words) < self.min_segment_words:
                continue

            context_words: set[str] = set()
            for j in range(i - self.context_window, i + self.context_window + 1):
                if j != i:
                    context_words |= _words(segments[j].text)

            similarity = _jaccard(seg_words, context_words)

            if similarity < self.similarity_threshold:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.WARNING,
                        segment_index=i,
                        reason=(
                            f"Segment vocabulary is disconnected from context "
                            f"(Jaccard={similarity:.3f}, threshold={self.similarity_threshold})"
                        ),
                        evidence={
                            "jaccard": round(similarity, 4),
                            "segment_words": sorted(seg_words)[:10],
                            "text": segments[i].text[:200],
                        },
                    )
                )

        return flags
