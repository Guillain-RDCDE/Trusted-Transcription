"""The pipeline applies repairs under the over-production bound."""

from __future__ import annotations

from trusted_transcription.models import (
    RepairAction,
    RepairResult,
    Segment,
    TranscriptResult,
)
from trusted_transcription.pipeline import Pipeline


def transcript() -> TranscriptResult:
    return TranscriptResult(
        segments=[
            Segment(start=0, end=5, text="La porte d'entrée est fermée à clé."),
            Segment(start=5, end=10, text="Thank you for watching."),
            Segment(start=10, end=15, text="Les volets sont clos."),
        ]
    )


def action(idx: int, kind: str, text: str, confidence: float = 0.9) -> RepairAction:
    return RepairAction(
        segment_index=idx,
        original_text="",
        repaired_text=text,
        action=kind,
        confidence=confidence,
        reasoning="test",
    )


class TestApplyRepairs:
    def test_delete_and_confident_replace(self):
        result = RepairResult(
            actions=[
                action(1, "delete", ""),
                action(2, "replace", "Les volets sont clos et verrouillés."),
            ]
        )
        out = Pipeline._apply_repairs(transcript(), result)
        assert [s.text for s in out.segments] == [
            "La porte d'entrée est fermée à clé.",
            "Les volets sont clos et verrouillés.",
        ]

    def test_low_confidence_replace_is_kept(self):
        result = RepairResult(actions=[action(2, "replace", "Autre chose.", confidence=0.5)])
        out = Pipeline._apply_repairs(transcript(), result)
        assert out.segments[2].text == "Les volets sont clos."

    def test_overproducing_replace_is_refused(self):
        invented = "Les volets sont clos. " + " ".join(["mot"] * 40)
        result = RepairResult(actions=[action(2, "replace", invented)])
        out = Pipeline._apply_repairs(transcript(), result)
        assert out.segments[2].text == "Les volets sont clos."

    def test_out_of_range_index_is_ignored(self):
        result = RepairResult(actions=[action(9, "delete", "")])
        out = Pipeline._apply_repairs(transcript(), result)
        assert len(out.segments) == 3
