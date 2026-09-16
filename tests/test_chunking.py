"""Tests for long-audio chunking: cap the chunk, never the file."""

from __future__ import annotations

import pytest

from trusted_transcription.prevention.chunking import (
    ChunkPolicy,
    coverage_error,
    estimated_bytes,
    ffmpeg_reencode_command,
    ffmpeg_segment_command,
    ffprobe_duration_command,
    max_chunk_seconds,
    plan_chunks,
    plan_upload,
    transcribe_in_chunks,
)

ONE_HOUR_FILE_S = 3468.636  # the real file that had been refused for a month


class TestArithmetic:
    def test_estimated_bytes(self):
        assert estimated_bytes(540, 320_000) == 21_600_000

    def test_max_chunk_seconds(self):
        assert max_chunk_seconds(24 * 1024 * 1024, 320_000) == pytest.approx(629.1456)

    def test_bitrate_must_be_positive(self):
        with pytest.raises(ValueError):
            max_chunk_seconds(1, 0)


class TestPolicy:
    def test_default_policy_fits_at_the_ceiling(self):
        assert ChunkPolicy().fits_at_ceiling

    def test_a_policy_that_cannot_fit_is_visible(self):
        assert not ChunkPolicy(chunk_s=900).fits_at_ceiling

    def test_invalid_policies(self):
        with pytest.raises(ValueError):
            ChunkPolicy(chunk_s=0)
        with pytest.raises(ValueError):
            ChunkPolicy(recut_s=600, chunk_s=540)
        with pytest.raises(ValueError):
            ChunkPolicy(limit_bytes=0)


class TestPlanChunks:
    def test_one_hour_file_sums_to_the_source_to_the_millisecond(self):
        chunks = plan_chunks(ONE_HOUR_FILE_S, 540.0)
        assert len(chunks) == 7
        assert coverage_error(chunks, ONE_HOUR_FILE_S) is None
        assert sum(b - a for a, b in chunks) == pytest.approx(ONE_HOUR_FILE_S, abs=1e-9)

    def test_last_chunk_ends_at_the_source_duration(self):
        chunks = plan_chunks(1000.0, 540.0)
        assert chunks == [(0.0, 540.0), (540.0, 1000.0)]

    def test_exact_multiple_has_no_empty_tail(self):
        assert plan_chunks(1080.0, 540.0) == [(0.0, 540.0), (540.0, 1080.0)]

    def test_short_file_is_one_chunk(self):
        assert plan_chunks(30.0) == [(0.0, 30.0)]

    def test_empty_file(self):
        assert plan_chunks(0.0) == []

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            plan_chunks(-1.0)
        with pytest.raises(ValueError):
            plan_chunks(10.0, 0)


class TestCoverageError:
    def test_gap(self):
        assert "gap" in coverage_error([(0, 10), (11, 20)], 20)

    def test_overlap(self):
        assert "overlap" in coverage_error([(0, 10), (9, 20)], 20)

    def test_not_starting_at_zero(self):
        assert "starts at" in coverage_error([(1, 20)], 20)

    def test_sum_mismatch(self):
        assert "sum to" in coverage_error([(0, 10), (10, 19)], 20)

    def test_reversed(self):
        assert "reversed" in coverage_error([(10, 0)], 10)

    def test_no_chunks_for_a_non_empty_source(self):
        assert coverage_error([], 10) == "no chunks"
        assert coverage_error([], 0) is None

    def test_tolerance_absorbs_probe_rounding(self):
        assert coverage_error([(0, 10.0004)], 10.0) is None


class TestPlanUpload:
    def test_mp3_at_the_ceiling_needs_no_reencode(self):
        plan = plan_upload(ONE_HOUR_FILE_S, 320_000)
        assert plan.ok and plan.reencode == []

    def test_high_bitrate_source_is_recut_and_reencoded(self):
        # A lossless-ish source at 1.4 Mb/s: 540 s would be far over the limit.
        plan = plan_upload(1200.0, 1_411_000)
        assert plan.reencode == [0, 1]  # the two-minute tail fits as is
        assert plan.ok

    def test_chunk_that_cannot_fit_is_refused_not_skipped(self):
        policy = ChunkPolicy(limit_bytes=1_000_000, recut_s=300, chunk_s=540)
        plan = plan_upload(600.0, 320_000, policy)
        assert plan.refused == [0, 1]
        assert not plan.ok

    def test_short_tail_chunk_under_the_limit_is_left_alone(self):
        plan = plan_upload(545.0, 1_411_000)
        assert plan.reencode == [0]
        assert 1 not in plan.reencode


class TestCommands:
    def test_segment_command_is_a_stream_copy(self):
        cmd = ffmpeg_segment_command("in.mp3", "chunk_%03d.mp3", 540.0)
        assert cmd[0] == "ffmpeg"
        assert cmd[cmd.index("-segment_time") + 1] == "540"
        assert cmd[cmd.index("-c") + 1] == "copy"
        assert "-reset_timestamps" in cmd
        assert cmd[-1] == "chunk_%03d.mp3"

    def test_reencode_command_cuts_the_span(self):
        cmd = ffmpeg_reencode_command("in.wav", "out.mp3", 540.0, 840.5, 128_000)
        assert cmd[cmd.index("-ss") + 1] == "540"
        assert cmd[cmd.index("-to") + 1] == "840.5"
        assert cmd[cmd.index("-b:a") + 1] == "128k"

    def test_ffprobe_prints_only_the_duration(self):
        cmd = ffprobe_duration_command("in.mp3")
        assert "format=duration" in cmd and cmd[-1] == "in.mp3"


class TestTranscribeInChunks:
    def test_all_chunks_concatenated_in_order(self):
        calls = []

        def engine(a, b):
            calls.append((a, b))
            return f"[{a:.0f}-{b:.0f}]"

        result = transcribe_in_chunks(1000.0, engine, 540.0)
        assert result.complete
        assert result.text == "[0-540] [540-1000]"
        assert calls == [(0.0, 540.0), (540.0, 1000.0)]

    def test_a_failing_chunk_is_recorded_not_swallowed(self):
        def engine(a, b):
            if a == 540.0:
                raise TimeoutError("api timed out")
            return "ok"

        result = transcribe_in_chunks(1500.0, engine, 540.0)
        assert not result.complete
        assert result.failed == [1]
        assert result.errors[1] == "TimeoutError: api timed out"
        assert result.text == "ok ok"

    def test_empty_chunk_text_does_not_leave_double_separators(self):
        result = transcribe_in_chunks(1000.0, lambda a, b: "" if a == 0 else "tail", 540.0)
        assert result.text == "tail"
