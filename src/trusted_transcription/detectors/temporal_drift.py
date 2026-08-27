"""Detect temporal drift — timestamps that stop making sense.

Whisper assigns timestamps to each segment. In normal operation these
advance monotonically and roughly match real-time speech rate. When
the model hallucinates, timestamps exhibit specific pathologies:

1. OVERLAP: segment N+1 starts before segment N ends (impossible in
   single-speaker audio)
2. GAP: a large unexplained gap between segments (the model skipped
   audio — content silently dropped)
3. STALL: multiple segments share the exact same start/end times
   (the model looped without advancing)
4. BACKWARDS: timestamps go backwards (catastrophic — usually means
   the model reset its internal position)

These are cheap to detect and almost always signal a deeper problem.
"""

from __future__ import annotations

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)


class TemporalDriftDetector:
    name = "temporal_drift"

    def __init__(
        self,
        max_overlap_sec: float = 0.1,
        max_gap_sec: float = 30.0,
        stall_tolerance_sec: float = 0.05,
    ):
        self.max_overlap_sec = max_overlap_sec
        self.max_gap_sec = max_gap_sec
        self.stall_tolerance_sec = stall_tolerance_sec

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []
        segments = transcript.segments

        for i in range(1, len(segments)):
            prev = segments[i - 1]
            curr = segments[i]

            if curr.start < prev.start - self.stall_tolerance_sec:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.CRITICAL,
                        segment_index=i,
                        reason=(
                            f"Timestamps go backwards: segment {i} starts at "
                            f"{curr.start:.2f}s but previous ended at {prev.end:.2f}s"
                        ),
                        evidence={
                            "type": "backwards",
                            "prev_end": prev.end,
                            "curr_start": curr.start,
                        },
                    )
                )

            overlap = prev.end - curr.start
            if overlap > self.max_overlap_sec:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.WARNING,
                        segment_index=i,
                        reason=(
                            f"Segments overlap by {overlap:.2f}s "
                            f"(prev ends {prev.end:.2f}, curr starts {curr.start:.2f})"
                        ),
                        evidence={
                            "type": "overlap",
                            "overlap_sec": round(overlap, 3),
                        },
                    )
                )

            gap = curr.start - prev.end
            if gap > self.max_gap_sec:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.WARNING,
                        segment_index=i,
                        reason=(
                            f"Unexplained gap of {gap:.1f}s between segments "
                            f"(content may have been silently dropped)"
                        ),
                        evidence={
                            "type": "gap",
                            "gap_sec": round(gap, 2),
                            "prev_end": prev.end,
                            "curr_start": curr.start,
                        },
                    )
                )

            if (
                abs(curr.start - prev.start) < self.stall_tolerance_sec
                and abs(curr.end - prev.end) < self.stall_tolerance_sec
            ):
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.CRITICAL,
                        segment_index=i,
                        reason=(
                            f"Timestamp stall: segments {i-1} and {i} share "
                            f"the same time range [{curr.start:.2f}-{curr.end:.2f}]"
                        ),
                        evidence={
                            "type": "stall",
                            "start": curr.start,
                            "end": curr.end,
                        },
                    )
                )

        return flags
