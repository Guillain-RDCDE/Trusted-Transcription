"""Tests for the context window (prevention of starved segments).

No audio, no engine: a fake ``transcribe_fn`` reads words from a
ground-truth timeline, so every assertion is about the arithmetic the
module promises — boundaries never move, every word is kept exactly
once, fallbacks are counted.
"""

from __future__ import annotations

import pytest

from trusted_transcription.prevention.context_window import (
    ContextWindowPolicy,
    ContextWindowReport,
    Window,
    Word,
    decoding_overrides,
    join_words,
    keep_words_in_segment,
    transcribe_with_context,
)

# --- A ground-truth timeline --------------------------------------------
#
# Words are spoken one every second, each lasting 0.6 s, from t=0 to
# t=120. A word spoken at t=k is " w<k>". Timestamps are absolute.

TIMELINE_S = 120.0


def truth_words(t0: float, t1: float) -> list[Word]:
    """All ground-truth words whose span intersects [t0, t1], relative to t0."""
    words = []
    for k in range(int(TIMELINE_S)):
        start, end = float(k), k + 0.6
        if end > t0 and start < t1:
            words.append(Word(start=start - t0, end=end - t0, text=f" w{k}"))
    return words


def fake_engine(calls: list[tuple[float, float]]):
    """A transcribe_fn that logs its calls and answers from the timeline."""

    def transcribe(t0: float, t1: float) -> list[Word]:
        calls.append((t0, t1))
        return truth_words(t0, t1)

    return transcribe


# --- Planning -------------------------------------------------------------


class TestPlan:
    def test_long_segment_is_not_padded(self):
        (w,) = ContextWindowPolicy().plan([(20.0, 45.0)], 120.0)
        assert not w.padded
        assert (w.padded_start, w.padded_end) == (20.0, 45.0)

    def test_short_segment_gets_context_on_both_sides(self):
        (w,) = ContextWindowPolicy(context_s=10.0).plan([(30.0, 32.0)], 120.0)
        assert w.padded
        assert (w.padded_start, w.padded_end) == (20.0, 42.0)
        assert w.offset == 10.0

    def test_boundaries_never_move(self):
        boundaries = [(0.0, 3.0), (3.0, 4.5), (4.5, 30.0), (30.0, 31.0)]
        windows = ContextWindowPolicy().plan(boundaries, 120.0)
        assert [(w.start, w.end) for w in windows] == boundaries
        assert [w.segment_index for w in windows] == [0, 1, 2, 3]

    def test_padding_is_clamped_to_the_file(self):
        first, last = ContextWindowPolicy().plan([(0.0, 2.0), (118.0, 120.0)], 120.0)
        assert first.padded_start == 0.0
        assert first.padded_end == 12.0
        assert last.padded_start == 108.0
        assert last.padded_end == 120.0

    def test_unknown_duration_clamps_only_at_zero(self):
        (w,) = ContextWindowPolicy().plan([(1.0, 2.0)], None)
        assert (w.padded_start, w.padded_end) == (0.0, 12.0)

    def test_segment_ending_past_rounded_duration_is_not_shrunk(self):
        (w,) = ContextWindowPolicy().plan([(119.0, 120.4)], 120.0)
        assert w.padded_end == 120.4
        assert w.end == 120.4

    def test_threshold_is_strict(self):
        policy = ContextWindowPolicy(short_threshold_s=10.0)
        exact, under = policy.plan([(0.0, 10.0), (20.0, 29.99)], 120.0)
        assert not exact.padded
        assert under.padded

    def test_zero_context_disables_padding(self):
        (w,) = ContextWindowPolicy(context_s=0.0).plan([(5.0, 6.0)], 120.0)
        assert not w.padded

    def test_reversed_boundary_is_rejected(self):
        with pytest.raises(ValueError):
            ContextWindowPolicy().plan([(5.0, 4.0)], 120.0)

    def test_negative_parameters_are_rejected(self):
        with pytest.raises(ValueError):
            ContextWindowPolicy(short_threshold_s=-1)
        with pytest.raises(ValueError):
            ContextWindowPolicy(context_s=-1)


# --- Keeping the right words ----------------------------------------------


def window(start: float, end: float, pad: float = 10.0) -> Window:
    return Window(
        segment_index=0,
        start=start,
        end=end,
        padded_start=max(0.0, start - pad),
        padded_end=end + pad,
    )


class TestKeepWords:
    def test_keeps_words_whose_midpoint_is_inside(self):
        w = window(30.0, 32.0)
        kept = keep_words_in_segment(truth_words(20.0, 42.0), w)
        assert [k.text for k in kept] == [" w30", " w31"]

    def test_output_timestamps_are_relative_to_the_segment(self):
        w = window(30.0, 32.0)
        kept = keep_words_in_segment(truth_words(20.0, 42.0), w)
        assert kept[0].start == pytest.approx(0.0)
        assert kept[0].end == pytest.approx(0.6)
        assert kept[1].start == pytest.approx(1.0)

    def test_word_on_the_cut_goes_to_the_next_segment(self):
        # A word centred exactly on t=32.0 sits on the boundary.
        on_cut = Word(start=31.8 - 20.0, end=32.2 - 20.0, text=" cut")
        left = window(30.0, 32.0)
        right = window(32.0, 34.0)
        assert keep_words_in_segment([on_cut], left) == []
        right_words = [Word(start=31.8 - 22.0, end=32.2 - 22.0, text=" cut")]
        assert [k.text for k in keep_words_in_segment(right_words, right)] == [" cut"]

    def test_contiguous_segments_partition_every_word_exactly_once(self):
        # Irregular cuts, all short: each padded window overlaps its
        # neighbours heavily, yet every word must land in one segment only.
        cuts = [0.0, 1.5, 3.0, 7.2, 8.0, 12.5, 13.0, 20.0, 25.5, 26.0, 40.0]
        boundaries = list(zip(cuts, cuts[1:]))
        windows = ContextWindowPolicy().plan(boundaries, 40.0)
        seen: list[str] = []
        for w in windows:
            heard = truth_words(w.padded_start, w.padded_end)
            seen.extend(k.text for k in keep_words_in_segment(heard, w))
        expected = [f" w{k}" for k in range(40)]
        assert sorted(seen, key=lambda t: int(t[2:])) == expected
        assert len(seen) == len(set(seen))

    def test_words_outside_are_dropped(self):
        w = window(30.0, 32.0)
        far = [Word(start=0.0, end=0.5, text=" w20"), Word(start=21.0, end=21.5, text=" w41")]
        assert keep_words_in_segment(far, w) == []

    def test_unpadded_window_is_identity(self):
        w = Window(segment_index=0, start=30.0, end=32.0, padded_start=30.0, padded_end=32.0)
        words = truth_words(30.0, 32.0)
        kept = keep_words_in_segment(words, w)
        assert [(k.start, k.end, k.text) for k in kept] == [
            (x.start, x.end, x.text) for x in words if 30.0 <= 30.0 + x.midpoint < 32.0
        ]

    def test_empty_input(self):
        assert keep_words_in_segment([], window(30.0, 32.0)) == []


class TestJoinWords:
    def test_raw_tokens_keep_engine_spacing_and_punctuation(self):
        words = [
            Word(0, 0.3, " Salle"),
            Word(0.3, 0.6, " d'eau"),
            Word(0.6, 0.7, ","),
            Word(0.7, 1.0, " carrelage"),
            Word(1.0, 1.1, "."),
        ]
        assert join_words(words) == "Salle d'eau, carrelage."

    def test_no_words_gives_empty_text(self):
        assert join_words([]) == ""


class TestDecodingOverrides:
    def test_padded_window_disables_anti_repetition(self):
        assert decoding_overrides(window(30.0, 32.0)) == {
            "repetition_penalty": 1.0,
            "no_repeat_ngram_size": 0,
        }

    def test_unpadded_window_changes_nothing(self):
        w = Window(segment_index=0, start=0.0, end=30.0, padded_start=0.0, padded_end=30.0)
        assert decoding_overrides(w) == {}


# --- End to end with a fake engine ------------------------------------------


class TestTranscribeWithContext:
    def test_text_per_segment_matches_the_truth(self):
        # Every segment here contains at least one word centre; a segment
        # with none takes the empty fallback, tested separately below.
        cuts = [0.0, 1.5, 3.0, 7.2, 8.0, 12.2, 13.0, 20.0, 25.1, 26.0, 40.0, 75.0, 120.0]
        boundaries = list(zip(cuts, cuts[1:]))
        calls: list[tuple[float, float]] = []
        segments, report = transcribe_with_context(boundaries, fake_engine(calls), TIMELINE_S)

        assert [(s.start, s.end) for s in segments] == boundaries
        for seg in segments:
            expected = join_words(
                [w for w in truth_words(0.0, TIMELINE_S) if seg.start <= w.midpoint < seg.end]
            )
            assert seg.text == expected
        assert report.fallbacks == 0

    def test_report_counts_padded_segments(self):
        boundaries = [(0.0, 2.0), (2.0, 30.0), (30.0, 31.0), (31.0, 120.0)]
        _, report = transcribe_with_context(boundaries, fake_engine([]), TIMELINE_S)
        assert report.total_segments == 4
        assert report.padded_segments == 2

    def test_long_segments_use_the_original_call_exactly(self):
        calls: list[tuple[float, float]] = []
        transcribe_with_context([(10.0, 50.0)], fake_engine(calls), TIMELINE_S)
        assert calls == [(10.0, 50.0)]

    def test_short_segments_are_sent_with_context(self):
        calls: list[tuple[float, float]] = []
        transcribe_with_context([(30.0, 32.0)], fake_engine(calls), TIMELINE_S)
        assert calls == [(20.0, 42.0)]

    def test_no_window_ever_leaves_the_file(self):
        cuts = [0.0, 0.5, 1.0, 60.0, 119.0, 119.5, 120.0]
        boundaries = list(zip(cuts, cuts[1:]))
        calls: list[tuple[float, float]] = []
        transcribe_with_context(boundaries, fake_engine(calls), TIMELINE_S)
        assert all(0.0 <= t0 <= t1 <= TIMELINE_S for t0, t1 in calls)

    def test_empty_window_falls_back_to_the_original_call(self):
        calls: list[tuple[float, float]] = []

        def silent_then_normal(t0: float, t1: float) -> list[Word]:
            calls.append((t0, t1))
            if t1 - t0 > 5.0:  # the padded call
                return []
            return [Word(0.0, 0.5, " ok")]

        segments, report = transcribe_with_context(
            [(30.0, 32.0)], silent_then_normal, TIMELINE_S
        )
        assert calls == [(20.0, 42.0), (30.0, 32.0)]
        assert segments[0].text == "ok"
        assert report.fallbacks_empty == 1
        assert report.fallbacks_desync == 0

    def test_desync_is_detected_and_counted(self):
        calls: list[tuple[float, float]] = []

        def wrong_audio(t0: float, t1: float) -> list[Word]:
            calls.append((t0, t1))
            if t1 - t0 > 5.0:
                # Timestamps far beyond the 22 s the engine was given:
                # it did not hear what we think it heard.
                return [Word(0.0, 0.5, " w"), Word(58.0, 59.0, " way-off")]
            return [Word(0.0, 0.5, " ok")]

        segments, report = transcribe_with_context([(30.0, 32.0)], wrong_audio, TIMELINE_S)
        assert calls == [(20.0, 42.0), (30.0, 32.0)]
        assert segments[0].text == "ok"
        assert report.fallbacks_desync == 1
        assert report.fallbacks_empty == 0

    def test_small_timestamp_overshoot_is_tolerated(self):
        def slightly_long(t0: float, t1: float) -> list[Word]:
            return [Word(10.0, 10.4, " w30"), Word(21.9, 22.3, " tail")]

        segments, report = transcribe_with_context(
            [(30.0, 32.0)], slightly_long, TIMELINE_S, desync_tolerance_s=0.5
        )
        assert report.fallbacks_desync == 0
        assert segments[0].text == "w30"

    def test_custom_policy_is_honoured(self):
        calls: list[tuple[float, float]] = []
        policy = ContextWindowPolicy(short_threshold_s=5.0, context_s=3.0)
        transcribe_with_context([(30.0, 32.0), (40.0, 47.0)], fake_engine(calls), 120.0, policy)
        assert calls == [(27.0, 35.0), (40.0, 47.0)]

    def test_empty_boundaries(self):
        segments, report = transcribe_with_context([], fake_engine([]), TIMELINE_S)
        assert segments == []
        assert report == ContextWindowReport()
