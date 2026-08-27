"""Main pipeline: audio -> transcribe -> detect -> repair -> score.

This is the entry point. Each stage is independent and testable.
The pipeline itself is a thin orchestrator that chains them.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from trusted_transcription.detectors import ALL_DETECTORS, Detector
from trusted_transcription.models import (
    HallucinationFlag,
    PipelineReport,
    Segment,
    TranscriptResult,
)
from trusted_transcription.repair.llm_repair import LLMRepairer
from trusted_transcription.scoring import compute_scores


class Pipeline:
    def __init__(
        self,
        detectors: Optional[list[Detector]] = None,
        repairer: Optional[LLMRepairer] = None,
        whisper_model: str = "whisper-1",
        language: str = "fr",
        repair_enabled: bool = True,
    ):
        self.detectors = detectors or list(ALL_DETECTORS)
        self.repairer = repairer or LLMRepairer()
        self.whisper_model = whisper_model
        self.language = language
        self.repair_enabled = repair_enabled

    def run(
        self,
        audio_path: str | Path,
        reference_text: Optional[str] = None,
    ) -> PipelineReport:
        start = time.monotonic()
        total_cost = 0.0

        transcript = self.transcribe(audio_path)

        all_flags: list[HallucinationFlag] = []
        for detector in self.detectors:
            flags = detector.detect(transcript)
            all_flags.extend(flags)
        transcript.flags = all_flags

        repair_result = None
        if self.repair_enabled and all_flags:
            repair_result = self.repairer.repair(transcript, all_flags)
            total_cost += repair_result.cost_usd

            if not repair_result.declined:
                transcript = self._apply_repairs(transcript, repair_result)

        scores = compute_scores(transcript, reference_text)

        elapsed = time.monotonic() - start

        return PipelineReport(
            transcript=transcript,
            repairs=repair_result,
            scores=scores,
            cost_usd=total_cost,
            duration_sec=round(elapsed, 2),
        )

    def transcribe(self, audio_path: str | Path) -> TranscriptResult:
        from openai import OpenAI

        client = OpenAI()
        audio_path = Path(audio_path)

        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model=self.whisper_model,
                file=f,
                language=self.language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        segments = []
        for seg in response.segments or []:
            segments.append(
                Segment(
                    start=seg["start"],
                    end=seg["end"],
                    text=seg["text"],
                    confidence=1.0 - seg.get("no_speech_prob", 0.0),
                )
            )

        return TranscriptResult(
            segments=segments,
            metadata={
                "audio_path": str(audio_path),
                "audio_duration_sec": response.duration,
                "model": self.whisper_model,
                "language": self.language,
            },
        )

    def detect_only(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        all_flags: list[HallucinationFlag] = []
        for detector in self.detectors:
            flags = detector.detect(transcript)
            all_flags.extend(flags)
        return all_flags

    @staticmethod
    def _apply_repairs(
        transcript: TranscriptResult,
        repair_result,
    ) -> TranscriptResult:
        segments = list(transcript.segments)

        delete_indices = set()
        for action in repair_result.actions:
            idx = action.segment_index
            if idx >= len(segments):
                continue
            if action.action == "delete":
                delete_indices.add(idx)
            elif action.action == "replace" and action.confidence >= 0.7:
                segments[idx] = segments[idx].model_copy(
                    update={"text": action.repaired_text}
                )

        if delete_indices:
            segments = [s for i, s in enumerate(segments) if i not in delete_indices]

        return transcript.model_copy(update={"segments": segments})
