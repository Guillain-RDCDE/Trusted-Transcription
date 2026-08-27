"""Detect unexpected language switches.

Whisper supports multilingual transcription, but in production the
expected language is usually known. An unexpected switch to another
language mid-transcript is almost always a hallucination — typically
Whisper falling back to English (its dominant training language) when
it can't decode a French/German/etc. segment.

Detection: if the pipeline specifies an expected language, flag any
segment tagged with a different one. Also flag segments where the
text contains a high ratio of words from a foreign vocabulary.
"""

from __future__ import annotations

import re

from trusted_transcription.models import (
    HallucinationFlag,
    Severity,
    TranscriptResult,
)

ENGLISH_MARKERS = re.compile(
    r"\b(the|and|is|are|was|were|have|has|been|this|that|with|from|they|their|which|would|could|should)\b",
    re.IGNORECASE,
)

FRENCH_MARKERS = re.compile(
    r"\b(les|des|une|est|sont|dans|avec|pour|qui|que|sur|par|cette|nous|vous|leur|mais|donc|puis)\b",
    re.IGNORECASE,
)


class LanguageSwitchDetector:
    name = "language_switch"

    def __init__(self, expected_language: str = "fr", marker_threshold: float = 0.3):
        self.expected_language = expected_language
        self.marker_threshold = marker_threshold

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        flags: list[HallucinationFlag] = []

        for i, seg in enumerate(transcript.segments):
            if seg.language and seg.language != self.expected_language:
                flags.append(
                    HallucinationFlag(
                        detector=self.name,
                        severity=Severity.WARNING,
                        segment_index=i,
                        reason=(
                            f"Language switch: expected '{self.expected_language}', "
                            f"got '{seg.language}'"
                        ),
                        evidence={
                            "expected": self.expected_language,
                            "detected": seg.language,
                            "text": seg.text[:200],
                        },
                    )
                )
                continue

            words = seg.text.split()
            if len(words) < 5:
                continue

            if self.expected_language == "fr":
                en_count = len(ENGLISH_MARKERS.findall(seg.text))
                fr_count = len(FRENCH_MARKERS.findall(seg.text))
                total_markers = en_count + fr_count
                if total_markers > 0 and en_count / total_markers > (1 - self.marker_threshold):
                    flags.append(
                        HallucinationFlag(
                            detector=self.name,
                            severity=Severity.WARNING,
                            segment_index=i,
                            reason=(
                                f"Segment appears to be English in a French transcript "
                                f"({en_count} EN markers vs {fr_count} FR markers)"
                            ),
                            evidence={
                                "en_markers": en_count,
                                "fr_markers": fr_count,
                                "text": seg.text[:200],
                            },
                        )
                    )

        return flags
