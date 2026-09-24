"""Every operator command, driven in-process on the committed samples.

The CI smoke steps prove the commands run; these tests pin what they
print and how they exit, so a change in output is a deliberate one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from trusted_transcription.cli import main

SAMPLES = Path(__file__).resolve().parent.parent / "corpus" / "sample"


@pytest.fixture
def run():
    runner = CliRunner()

    def invoke(*args: str):
        return runner.invoke(main, list(args))

    return invoke


class TestDetect:
    def test_table_lists_the_three_flags_of_the_silence_sample(self, run):
        result = run("detect", str(SAMPLES / "silence_hallucination.json"), "--format", "table")
        assert result.exit_code == 0
        assert "silence_hallucination" in result.output
        assert "repetition_loop" in result.output
        assert "temporal_drift" in result.output
        assert "Total: 3 flags" in result.output

    def test_clean_sample_has_no_flag(self, run):
        result = run("detect", str(SAMPLES / "clean_transcript.json"))
        assert result.exit_code == 0
        assert "No hallucinations detected." in result.output

    def test_json_output_is_a_list_of_flags(self, run):
        import json

        result = run("detect", str(SAMPLES / "prompt_echo.json"), "--format", "json")
        assert result.exit_code == 0
        flags = json.loads(result.output.split("\nTotal:")[0])
        assert [f["detector"] for f in flags] == ["prompt_echo"]
        assert flags[0]["evidence"]["type"] == "vocabulary_echo"

    def test_script_drift_sample_reports_the_regeneration_point(self, run):
        result = run("detect", str(SAMPLES / "script_drift.json"))
        assert "script_drift" in result.output
        assert "silence_hallucination" in result.output

    def test_missing_file_is_a_usage_error(self, run):
        result = run("detect", "nope.json")
        assert result.exit_code == 2


class TestWindows:
    def test_table_marks_the_short_segments(self, run):
        result = run("windows", str(SAMPLES / "forced_cuts.json"))
        assert result.exit_code == 0
        assert "+20.0s" in result.output
        assert "6 short segment(s) out of 11" in result.output

    def test_json_carries_the_padded_flag(self, run):
        import json

        result = run("windows", str(SAMPLES / "forced_cuts.json"), "--format", "json")
        plan = json.loads(result.output.split("\nContext window:")[0])
        assert plan[0]["padded"] is False and plan[2]["padded"] is True

    def test_threshold_option(self, run):
        result = run("windows", str(SAMPLES / "forced_cuts.json"), "--threshold", "0")
        assert "0 short segment(s)" in result.output


class TestSpell:
    def test_shows_before_and_after_for_every_changed_segment(self, run):
        result = run("spell", str(SAMPLES / "spellings.json"))
        assert result.exit_code == 0
        assert "BARLET -> VARLET" in result.output
        assert "Jules-Guede -> Jules-Guesde" in result.output
        assert "Segments changed: 4 of 4" in result.output


class TestChunks:
    def test_one_hour_file_sums_to_the_source(self, run):
        result = run("chunks", "3468.636", "--bitrate", "320")
        assert result.exit_code == 0
        assert "chunks sum to 3468.636s: identical" in result.output
        assert result.output.count("copy") == 7

    def test_unfittable_chunk_exits_non_zero(self, run):
        result = run("chunks", "600", "--bitrate", "320", "--limit-mb", "1")
        assert result.exit_code == 1
        assert "refuse" in result.output
        assert "never skip" in result.output


class TestBenchReport:
    def test_paired_record_and_disqualification(self, run):
        result = run("bench-report", str(SAMPLES / "bench_results.jsonl"), "--control", "paid-api")
        assert result.exit_code == 0
        assert "control" in result.output
        assert "0W 4L" in result.output
        assert "OUT: skips audio" in result.output

    def test_without_control_no_paired_column(self, run):
        result = run("bench-report", str(SAMPLES / "bench_results.jsonl"))
        assert result.exit_code == 0
        assert "VS " not in result.output


class TestCost:
    def test_sixty_minutes(self, run):
        result = run("cost", "60")
        assert result.exit_code == 0
        assert "Per hour:     $0.40" in result.output


def test_help_lists_every_command(run):
    result = run("--help")
    for command in ("bench-report", "chunks", "cost", "detect", "run", "spell", "windows"):
        assert command in result.output
