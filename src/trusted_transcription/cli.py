"""CLI entry point — the operator interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from trusted_transcription.detectors import ALL_DETECTORS
from trusted_transcription.models import TranscriptResult


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

    click.echo("\n--- Summary ---", err=True)
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
@click.argument("boundaries_json", type=click.Path(exists=True))
@click.option("--threshold", default=10.0, show_default=True,
              help="Segments shorter than this (seconds) get context")
@click.option("--context", "context_s", default=10.0, show_default=True,
              help="Seconds of audio added on each side")
@click.option("--format", "fmt", type=click.Choice(["json", "table"]), default="table")
def windows(boundaries_json, threshold, context_s, fmt):
    """Show what the model will hear for each segment (ADR 0005).

    BOUNDARIES_JSON holds {"audio_duration_sec": N, "boundaries": [[start, end], ...]}.
    """
    from trusted_transcription.prevention.context_window import ContextWindowPolicy

    raw = json.loads(Path(boundaries_json).read_text(encoding="utf-8"))
    boundaries = [(float(a), float(b)) for a, b in raw["boundaries"]]
    duration = raw.get("audio_duration_sec")

    policy = ContextWindowPolicy(short_threshold_s=threshold, context_s=context_s)
    plan = policy.plan(boundaries, duration)

    if fmt == "json":
        click.echo(json.dumps([w.__dict__ | {"padded": w.padded} for w in plan], indent=2))
    else:
        click.echo(f"{'SEG':>4}  {'SEGMENT':<17}  {'MODEL HEARS':<17}  CONTEXT")
        click.echo("-" * 60)
        for w in plan:
            heard = f"{w.padded_start:6.1f}-{w.padded_end:6.1f}"
            seg = f"{w.start:6.1f}-{w.end:6.1f}"
            mark = f"+{w.padded_duration - w.duration:.1f}s" if w.padded else "-"
            click.echo(f"{w.segment_index:>4}  {seg:<17}  {heard:<17}  {mark}")

    padded = sum(1 for w in plan if w.padded)
    click.echo(f"\nContext window: {padded} short segment(s) out of {len(plan)}", err=True)


@main.command()
@click.argument("duration_s", type=float)
@click.option("--bitrate", default=320, show_default=True, help="Source bitrate in kb/s")
@click.option("--chunk", "chunk_s", default=540.0, show_default=True, help="Chunk length (s)")
@click.option("--limit-mb", default=24.0, show_default=True, help="Upload limit per chunk")
def chunks(duration_s, bitrate, chunk_s, limit_mb):
    """Plan the upload chunks for a long file and prove nothing is lost (ADR 0008)."""
    from trusted_transcription.prevention.chunking import (
        ChunkPolicy,
        coverage_error,
        estimated_bytes,
        plan_upload,
    )

    policy = ChunkPolicy(chunk_s=chunk_s, limit_bytes=int(limit_mb * 1024 * 1024))
    plan = plan_upload(duration_s, bitrate * 1000, policy)

    click.echo(f"{'CHUNK':>5}  {'SPAN':<19}  {'EST. SIZE':>10}  ACTION")
    click.echo("-" * 56)
    for i, (a, b) in enumerate(plan.chunks):
        size_mb = estimated_bytes(b - a, bitrate * 1000) / (1024 * 1024)
        if i in plan.refused:
            action = "refuse"
        elif i in plan.reencode:
            action = "re-cut + re-encode"
        else:
            action = "copy"
        click.echo(f"{i:>5}  {a:8.3f}-{b:8.3f}  {size_mb:8.2f} MB  {action}")

    total = sum(b - a for a, b in plan.chunks)
    problem = coverage_error(plan.chunks, duration_s)
    click.echo(f"\nSource {duration_s:.3f}s, chunks sum to {total:.3f}s: "
               f"{'identical' if problem is None else problem}", err=True)
    if not plan.ok:
        click.echo("Some chunks cannot fit under the limit — fail visibly, never skip.", err=True)
        sys.exit(1)


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
