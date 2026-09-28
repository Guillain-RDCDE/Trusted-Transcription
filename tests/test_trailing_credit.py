"""Tests for the trailing-credit detector, shaped by the public corpus."""

from __future__ import annotations

from trusted_transcription.detectors.trailing_credit import TrailingCreditDetector
from trusted_transcription.models import Segment, TranscriptResult


def transcript(*spans):
    return TranscriptResult(
        segments=[Segment(start=a, end=b, text=t) for a, b, t in spans],
        metadata={"audio_duration_sec": spans[-1][1] + 0.1},
    )


def test_credit_after_ten_seconds_of_silence():
    t = transcript(
        (300.0, 322.8, "Voici quelques-uns de ces récits."),
        (333.3, 334.7, "Sous-titres réalisés par la communauté d'Amara.org"),
    )
    (flag,) = TrailingCreditDetector().detect(t)
    assert flag.segment_index == 1
    assert flag.evidence["gap_s"] == 10.5


def test_readers_closing_words_after_a_breath_are_fine():
    t = transcript((440.0, 463.5, "5 décembre 1882."), (466.0, 467.3, "Fin de la folle."))
    assert TrailingCreditDetector().detect(t) == []


def test_a_long_last_segment_is_not_a_credit():
    t = transcript((0.0, 10.0, "Début."), (20.0, 40.0, " ".join(["mot"] * 30)))
    assert TrailingCreditDetector().detect(t) == []


def test_a_long_pause_in_the_middle_is_a_pause():
    t = transcript(
        (0.0, 10.0, "Début."), (25.0, 26.0, "Chambre."), (26.5, 40.0, "La suite du constat.")
    )
    assert TrailingCreditDetector().detect(t) == []


def test_single_segment_has_no_gap():
    assert TrailingCreditDetector().detect(transcript((0.0, 5.0, "Merci."))) == []


def test_thresholds_are_configurable():
    t = transcript((0.0, 10.0, "Début."), (13.0, 14.0, "Fin."))
    assert TrailingCreditDetector().detect(t) == []
    assert len(TrailingCreditDetector(min_gap_s=2.0).detect(t)) == 1
