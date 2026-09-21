"""Detect hallucinations on silence or near-silence.

Whisper is trained on captioned audio. When fed silence, white noise,
or very low-level background sound, it does NOT output nothing — it
confidently produces text inherited from its training data. Common
outputs include: "Thank you for watching", "Subscribe to my channel",
"Sous-titres par la communauté d'Amara.org", music lyrics, or
apparently coherent but fabricated sentences.

Detection: a segment is suspicious if it produces text but the audio
energy (if available) is below the silence threshold, or if the
segment duration is disproportionately long relative to its word count
(Whisper stretches timestamps to fill silence).
"""

from __future__ import annotations

from trusted_transcription.detectors.phantom_phrases import match_phantom, patterns_for
from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

# Kept for callers that imported the flat list; see phantom_phrases.py
# for the per-language lists.
KNOWN_PHANTOM_PATTERNS = patterns_for(None)

MIN_WORDS_PER_SECOND = 0.3


class SilenceHallucinationDetector:
    name = "silence_hallucination"

    def __init__(
        self,
        energy_threshold: float = 0.01,
        min_wps: float = MIN_WORDS_PER_SECOND,
        languages: list[str] | None = None,
    ):
        self.energy_threshold = energy_threshold
        self.min_wps = min_wps
        # None checks every known language: phantom phrases follow the
        # decoded language, which is not always the expected one.
        self.languages = languages

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []

        for i, seg in enumerate(transcript.segments):
            duration = seg.end - seg.start
            if duration <= 0:
                continue

            text = seg.text.strip()
            if not text:
                continue

            pattern = match_phantom(text, self.languages)
            if pattern is not None:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.CRITICAL,
                        segment_index=i,
                        reason=f"Known phantom phrase: '{text}'",
                        evidence={"pattern": pattern.pattern, "text": text},
                    )
                )

            word_count = len(text.split())
            wps = word_count / duration
            if wps < self.min_wps and word_count <= 3:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.WARNING,
                        segment_index=i,
                        reason=(
                            f"Sparse text over long segment: {word_count} words "
                            f"in {duration:.1f}s ({wps:.2f} words/sec)"
                        ),
                        evidence={
                            "word_count": word_count,
                            "duration": duration,
                            "wps": round(wps, 3),
                        },
                    )
                )

            energy = seg.confidence
            if energy is not None and energy < self.energy_threshold and word_count > 0:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.CRITICAL,
                        segment_index=i,
                        reason=(
                            f"Text produced on near-silent audio "
                            f"(energy={energy:.4f} < {self.energy_threshold})"
                        ),
                        evidence={"energy": energy, "text": text},
                    )
                )

        return flags
