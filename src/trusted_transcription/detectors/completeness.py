"""Detect completeness failures — the transcript is shorter than the audio.

The most dangerous failure mode in production: the model silently
drops entire sections of audio. The transcript looks fine — it's
well-formed, coherent, correctly punctuated — but 30% of the
dictation is missing. No error, no flag, no empty segment. The
content was never produced.

This is catastrophic in legal transcription: a missing paragraph
in a sworn statement is not a quality issue, it's a liability.

Detection: compare total transcribed duration against audio duration.
If the ratio falls below a threshold, something was dropped. Also
check for suspiciously long gaps between segments that don't
correspond to silence.
"""

from __future__ import annotations

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)


class CompletenessDetector:
    name = "completeness"

    def __init__(
        self,
        min_coverage_ratio: float = 0.7,
        min_words_per_minute: float = 40.0,
        max_words_per_minute: float = 250.0,
    ):
        self.min_coverage_ratio = min_coverage_ratio
        self.min_wpm = min_words_per_minute
        self.max_wpm = max_words_per_minute

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []
        segments = transcript.segments

        if not segments:
            return flags

        audio_duration = transcript.metadata.get("audio_duration_sec")
        if audio_duration and audio_duration > 0:
            transcribed_duration = sum(
                max(0, seg.end - seg.start) for seg in segments
            )
            coverage = transcribed_duration / audio_duration

            if coverage < self.min_coverage_ratio:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.CRITICAL,
                        segment_index=0,
                        reason=(
                            f"Only {coverage:.0%} of audio duration is covered by "
                            f"segments ({transcribed_duration:.0f}s / {audio_duration:.0f}s) "
                            f"— content may have been silently dropped"
                        ),
                        evidence={
                            "type": "low_coverage",
                            "coverage_ratio": round(coverage, 3),
                            "audio_sec": audio_duration,
                            "transcribed_sec": round(transcribed_duration, 1),
                        },
                    )
                )

            total_words = sum(len(seg.text.split()) for seg in segments)
            audio_minutes = audio_duration / 60
            if audio_minutes > 0.5:
                wpm = total_words / audio_minutes
                if wpm < self.min_wpm:
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.WARNING,
                            segment_index=0,
                            reason=(
                                f"Suspiciously low word rate: {wpm:.0f} words/min "
                                f"(expected {self.min_wpm:.0f}+) — may indicate dropped content"
                            ),
                            evidence={
                                "type": "low_wpm",
                                "wpm": round(wpm, 1),
                                "total_words": total_words,
                                "audio_minutes": round(audio_minutes, 1),
                            },
                        )
                    )
                elif wpm > self.max_wpm:
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.WARNING,
                            segment_index=0,
                            reason=(
                                f"Suspiciously high word rate: {wpm:.0f} words/min "
                                f"(expected <{self.max_wpm:.0f}) — may indicate fabricated text"
                            ),
                            evidence={
                                "type": "high_wpm",
                                "wpm": round(wpm, 1),
                                "total_words": total_words,
                                "audio_minutes": round(audio_minutes, 1),
                            },
                        )
                    )

        return flags
