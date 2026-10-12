"""Main pipeline: audio -> transcribe -> detect -> repair -> score.

This is the entry point. Each stage is independent and testable.
The pipeline itself is a thin orchestrator that chains them.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from trusted_transcription.detectors import ALL_DETECTORS, Detector
from trusted_transcription.models import (
    HallucinationFlag,
    PipelineReport,
    RepairResult,
    Segment,
    TranscriptResult,
)
from trusted_transcription.repair.completeness_guard import overproduces
from trusted_transcription.repair.llm_repair import LLMRepairer
from trusted_transcription.scoring import compute_scores


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from an API response item, whether it is a dict or an object.

    The openai SDK returns pydantic models (``TranscriptionVerbose`` whose
    ``segments`` are ``TranscriptionSegment`` objects, not subscriptable);
    older clients and raw JSON give plain dicts. Both are accepted.
    """
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


class Pipeline:
    def __init__(
        self,
        detectors: list[Detector] | None = None,
        repairer: LLMRepairer | None = None,
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
        reference_text: str | None = None,
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
        for seg in _field(response, "segments") or []:
            segments.append(
                Segment(
                    start=_field(seg, "start"),
                    end=_field(seg, "end"),
                    text=_field(seg, "text"),
                    confidence=1.0 - (_field(seg, "no_speech_prob") or 0.0),
                )
            )

        return TranscriptResult(
            segments=segments,
            metadata={
                "audio_path": str(audio_path),
                "audio_duration_sec": _field(response, "duration"),
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
        repair_result: RepairResult,
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
                # ADR 0004, made measurable by ADR 0007: a replacement
                # never has more words than the source can justify.
                if overproduces(segments[idx].text, action.repaired_text):
                    continue
                segments[idx] = segments[idx].model_copy(update={"text": action.repaired_text})

        if delete_indices:
            segments = [s for i, s in enumerate(segments) if i not in delete_indices]

        return transcript.model_copy(update={"segments": segments})
