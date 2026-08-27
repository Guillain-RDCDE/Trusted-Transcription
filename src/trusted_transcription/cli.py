"""CLI entry point — the operator interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from trusted_transcription.detectors import ALL_DETECTORS
from trusted_transcription.models import TranscriptResult
from trusted_transcription.scoring import compute_scores


@click.group()
def main():
    """Trusted-Transcription: catch confident lies in automatic transcription."""


@main.command()
@click.argument("audio_path", type=click.Path(exists=True))
@click.option("--language", "-l", default="fr", help="ISO 639-1 language code")
@click.option("--no-repair", is_flag=True, help="Skip the LLM repair pass")
@click.option("--reference", "-r", type=click.Path(exists=True), help="Reference transcript")
@click.option("--output", "-o", type=click.Path(), help="Write report JSON to file")
def run(audio_path, language, no_repair, reference, output):
    """Run the full pipeline on an audio file."""
    from trusted_transcription.pipeline import Pipeline

    ref_text = None
    if reference:
        ref_text = Path(reference).read_text(encoding="utf-8")

    pipeline = Pipeline(language=language, repair_enabled=not no_repair)
    report = pipeline.run(audio_path, reference_text=ref_text)

    report_json = report.model_dump_json(indent=2)

    if output:
        Path(output).write_text(report_json)
        click.echo(f"Report written to {output}")
    else:
        click.echo(report_json)

    click.echo(f"\n--- Summary ---", err=True)
    click.echo(f"Segments: {report.scores.get('total_segments', 0)}", err=True)
    click.echo(f"Critical flags: {report.scores.get('critical_flags', 0)}", err=True)
    click.echo(f"Warning flags: {report.scores.get('warning_flags', 0)}", err=True)
    click.echo(f"Hallucination rate: {report.scores.get('hallucination_rate', 0):.1%}", err=True)
    if "wer" in report.scores and report.scores["wer"] is not None:
        click.echo(f"WER: {report.scores['wer']:.1%}", err=True)
    click.echo(f"Cost: ${report.cost_usd:.4f}", err=True)
    click.echo(f"Duration: {report.duration_sec:.1f}s", err=True)


@main.command()
@click.argument("transcript_json", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["json", "table"]), default="table")
def detect(transcript_json, fmt):
    """Run hallucination detectors on a transcript JSON file."""
    raw = Path(transcript_json).read_text(encoding="utf-8")
    transcript = TranscriptResult.model_validate_json(raw)

    all_flags = []
    for detector in ALL_DETECTORS:
        flags = detector.detect(transcript)
        all_flags.extend(flags)

    if fmt == "json":
        click.echo(json.dumps([f.model_dump() for f in all_flags], indent=2))
    else:
        if not all_flags:
            click.echo("No hallucinations detected.")
            return

        click.echo(f"{'SEG':>4}  {'SEVERITY':<10}  {'DETECTOR':<25}  REASON")
        click.echo("-" * 80)
        for flag in sorted(all_flags, key=lambda f: (f.segment_index, f.severity.value)):
            click.echo(
                f"{flag.segment_index:>4}  {flag.severity.value:<10}  "
                f"{flag.detector:<25}  {flag.reason[:60]}"
            )

    click.echo(f"\nTotal: {len(all_flags)} flags", err=True)


@main.command()
@click.argument("audio_duration_min", type=float)
@click.option("--hall-rate", default=0.05, help="Expected hallucination rate (0-1)")
def cost(audio_duration_min, hall_rate):
    """Estimate processing cost for a given audio duration."""
    minutes = audio_duration_min
    whisper_cost = minutes * 0.006
    segments_estimate = minutes * 6
    repair_segments = segments_estimate * hall_rate
    repair_cost = repair_segments * 0.002
    result = {
        "whisper_cost_usd": round(whisper_cost, 4),
        "repair_cost_usd": round(repair_cost, 4),
        "total_cost_usd": round(whisper_cost + repair_cost, 4),
        "cost_per_hour_usd": round((whisper_cost + repair_cost) * (60 / minutes), 2),
    }

    click.echo(f"Whisper API:  ${result['whisper_cost_usd']:.4f}")
    click.echo(f"LLM repair:   ${result['repair_cost_usd']:.4f}")
    click.echo(f"Total:        ${result['total_cost_usd']:.4f}")
    click.echo(f"Per hour:     ${result['cost_per_hour_usd']:.2f}")


if __name__ == "__main__":
    main()
