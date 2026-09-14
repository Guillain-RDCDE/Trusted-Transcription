"""Tests for the per-chunk deficit against a reference transcript."""

from __future__ import annotations

import pytest

from trusted_transcription.detectors.reference_deficit import (
    ReferenceDeficitDetector,
    strip_tags,
    word_count,
    words_per_chunk,
)
from trusted_transcription.models import Segment, TranscriptResult

SENTENCE = "le mur nord présente des traces d'humidité au niveau de la plinthe"  # 12 words


def make(words_per_segment: list[int], seg_s: float = 60.0, tags: int = 0) -> TranscriptResult:
    segments = []
    for i, n in enumerate(words_per_segment):
        text = " ".join(["mot"] * n) + " <photo 12:34>" * tags
        segments.append(Segment(start=i * seg_s, end=(i + 1) * seg_s, text=text))
    return TranscriptResult(segments=segments)


class TestCounting:
    def test_strip_tags(self):
        assert strip_tags("a <photo 1:02> b <video3:44> c").split() == ["a", "b", "c"]

    def test_word_count_ignores_tags_and_punctuation(self):
        assert word_count("Bonjour, madame. <photo 0:01>") == 2

    def test_words_per_chunk_buckets_by_segment_start(self):
        t = make([10, 20, 30], seg_s=100.0)
        assert words_per_chunk(t, chunk_s=150.0) == {0: 30, 1: 30}


class TestDetector:
    def test_healthy_chunks_are_silent(self):
        reference = make([100] * 9)
        got = make([90, 110, 95, 100, 80, 105, 100, 97, 99])
        assert ReferenceDeficitDetector(reference).detect(got) == []

    def test_a_chunk_that_lost_most_of_its_words_is_flagged(self):
        # Nine one-minute segments per chunk of 540 s: chunk 1 = segments 9..17.
        reference = make([100] * 27)
        counts = [100] * 27
        for i in range(9, 18):
            counts[i] = 8  # the middle chunk came back as a prompt echo
        got = make(counts)
        (flag,) = ReferenceDeficitDetector(reference).detect(got)
        assert flag.evidence["chunk"] == 1
        assert flag.segment_index == 9
        assert flag.evidence["ratio"] < 0.1

    def test_tags_in_the_reference_do_not_fake_a_hole(self):
        # A photo-heavy reference: dozens of anchors, same words.
        reference = make([40] * 9, tags=25)
        got = make([40] * 9)
        assert ReferenceDeficitDetector(reference).detect(got) == []

    def test_reference_chunk_too_small_to_judge_is_skipped(self):
        reference = make([3] * 9)
        got = make([0] * 9)
        assert ReferenceDeficitDetector(reference).detect(got) == []

    def test_missing_chunk_entirely(self):
        reference = make([100] * 18)
        got = make([100] * 9)
        (flag,) = ReferenceDeficitDetector(reference).detect(got)
        assert flag.evidence == {
            "chunk": 1,
            "chunk_start_s": 540.0,
            "chunk_end_s": 1080.0,
            "words": 0,
            "reference_words": 900,
            "ratio": 0.0,
        }

    def test_threshold_is_configurable(self):
        reference = make([100] * 9)
        got = make([60] * 9)
        assert ReferenceDeficitDetector(reference, min_ratio=0.55).detect(got) == []
        assert len(ReferenceDeficitDetector(reference, min_ratio=0.7).detect(got)) == 1

    def test_invalid_chunk_size(self):
        with pytest.raises(ValueError):
            ReferenceDeficitDetector(make([1]), chunk_s=0)
