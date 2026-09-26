"""Tests for the detector bench, and the regression gate on the samples."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trusted_transcription.detectors import ALL_DETECTORS
from trusted_transcription.eval.detector_bench import (
    BenchReport,
    DetectorScore,
    load_labels,
    render,
    run_detector_bench,
)
from trusted_transcription.models import HallucinationFlag, Severity, TranscriptResult

SAMPLES = Path(__file__).resolve().parent.parent / "corpus" / "sample"


class Fires:
    """A fake detector that fires on files whose text mentions its name."""

    def __init__(self, name: str):
        self.name = name

    def detect(self, transcript: TranscriptResult) -> list[HallucinationFlag]:
        text = " ".join(s.text for s in transcript.segments)
        if self.name in text:
            return [HallucinationFlag(detector=self.name, severity=Severity.CRITICAL,
                                      segment_index=0, reason="fake")]
        return []


def write(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(
        json.dumps({"segments": [{"start": 0, "end": 1, "text": text}]}), encoding="utf-8"
    )


class TestScoring:
    def test_true_false_positives_and_negatives(self, tmp_path):
        write(tmp_path, "a.json", "alpha here")
        write(tmp_path, "b.json", "nothing")
        write(tmp_path, "c.json", "alpha again")
        labels = {"a.json": {"alpha"}, "b.json": {"alpha"}, "c.json": set()}
        report = run_detector_bench(tmp_path, labels, [Fires("alpha")])
        score = report.scores["alpha"]
        assert score.true_positives == ["a.json"]
        assert score.false_negatives == ["b.json"]
        assert score.false_positives == ["c.json"]
        assert score.precision == 0.5 and score.recall == 0.5
        assert not report.clean

    def test_detector_never_expected_never_fired_has_no_ratio(self, tmp_path):
        write(tmp_path, "a.json", "quiet")
        report = run_detector_bench(tmp_path, {"a.json": set()}, [Fires("alpha")])
        score = report.scores["alpha"]
        assert score.precision is None and score.recall is None
        assert report.clean

    def test_missing_file_is_a_broken_expectation(self, tmp_path):
        report = run_detector_bench(tmp_path, {"ghost.json": set()}, [Fires("alpha")])
        assert report.missing_files == ["ghost.json"]
        assert not report.clean
        assert "missing file: ghost.json" in report.broken()

    def test_unknown_detector_in_labels_is_a_false_negative(self, tmp_path):
        write(tmp_path, "a.json", "x")
        report = run_detector_bench(tmp_path, {"a.json": {"nonexistent"}}, [Fires("alpha")])
        assert report.scores["nonexistent"].false_negatives == ["a.json"]


class TestRender:
    def test_table_and_verdict(self):
        report = BenchReport(
            files=2,
            scores={"alpha": DetectorScore("alpha", ["a.json"], [], ["b.json"])},
        )
        text = render(report)
        assert "alpha" in text and "50%" in text and "100%" in text
        assert "broken expectations" in text
        assert "expected but did not fire on b.json" in text

    def test_clean_verdict(self):
        report = BenchReport(files=1, scores={"alpha": DetectorScore("alpha", ["a.json"])})
        assert "every expectation met" in render(report)


class TestLabels:
    def test_load(self, tmp_path):
        p = tmp_path / "labels.json"
        p.write_text('{"a.json": ["x", "y"], "b.json": []}', encoding="utf-8")
        assert load_labels(p) == {"a.json": {"x", "y"}, "b.json": set()}

    def test_rejects_non_object(self, tmp_path):
        p = tmp_path / "labels.json"
        p.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError):
            load_labels(p)


def test_every_committed_sample_meets_its_expectations():
    """The regression gate: the samples say what the detectors must do."""
    labels = load_labels(SAMPLES / "labels.json")
    report = run_detector_bench(SAMPLES, labels, list(ALL_DETECTORS))
    assert report.clean, "\n".join(report.broken())
    assert report.files == len(labels)
