"""Hallucination detectors — one file per failure mode."""

from __future__ import annotations

from typing import Protocol

from trusted_transcription.models import HallucinationFlag, TranscriptResult


class Detector(Protocol):
    name: str

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]: ...


from trusted_transcription.detectors.repetition_loop import RepetitionLoopDetector
from trusted_transcription.detectors.silence_hallucination import SilenceHallucinationDetector
from trusted_transcription.detectors.prompt_echo import PromptEchoDetector
from trusted_transcription.detectors.temporal_drift import TemporalDriftDetector
from trusted_transcription.detectors.phantom_subtitle import PhantomSubtitleDetector
from trusted_transcription.detectors.language_switch import LanguageSwitchDetector
from trusted_transcription.detectors.completeness import CompletenessDetector

ALL_DETECTORS: list[Detector] = [
    RepetitionLoopDetector(),
    SilenceHallucinationDetector(),
    PromptEchoDetector(),
    TemporalDriftDetector(),
    PhantomSubtitleDetector(),
    LanguageSwitchDetector(),
    CompletenessDetector(),
]
