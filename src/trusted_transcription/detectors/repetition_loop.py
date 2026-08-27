"""Detect repetition loops — the most common Whisper hallucination.

Whisper sometimes gets stuck in a loop, repeating the same phrase or
n-gram dozens of times. The output looks confident (high probability
per token) but is pure fabrication. This happens most often on long
audio with background noise or music.

Detection: sliding window over segments. If an n-gram (3+ words)
repeats more than `max_repeats` times within `window_segments`
consecutive segments, flag the entire run.
"""

from __future__ import annotations

from collections import Counter

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)


class RepetitionLoopDetector:
    name = "repetition_loop"

    def __init__(
        self,
        ngram_size: int = 3,
        max_repeats: int = 3,
        window_segments: int = 10,
    ):
        self.ngram_size = ngram_size
        self.max_repeats = max_repeats
        self.window_segments = window_segments

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []
        segments = transcript.segments

        for win_start in range(0, len(segments), self.window_segments // 2):
            win_end = min(win_start + self.window_segments, len(segments))
            window = segments[win_start:win_end]

            ngram_counts: Counter[tuple[str, ...]] = Counter()
            ngram_first_seg: dict[tuple[str, ...], int] = {}

            for seg_offset, seg in enumerate(window):
                words = seg.text.lower().split()
                for i in range(len(words) - self.ngram_size + 1):
                    gram = tuple(words[i : i + self.ngram_size])
                    ngram_counts[gram] += 1
                    if gram not in ngram_first_seg:
                        ngram_first_seg[gram] = win_start + seg_offset

            for gram, count in ngram_counts.items():
                if count >= self.max_repeats:
                    first_seg_idx = ngram_first_seg[gram]
                    if not any(
                        f.detector == self.name and f.segment_index == first_seg_idx
                        for f in flags
                    ):
                        flags.append(
                            HallucinationFlag(
                                detector=self.name,
                                severity=Severity.CRITICAL,
                                segment_index=first_seg_idx,
                                reason=(
                                    f"N-gram '{' '.join(gram)}' repeated {count} times "
                                    f"within {win_end - win_start} segments"
                                ),
                                evidence={
                                    "ngram": list(gram),
                                    "count": count,
                                    "window": [win_start, win_end],
                                },
                            )
                        )

        return flags
