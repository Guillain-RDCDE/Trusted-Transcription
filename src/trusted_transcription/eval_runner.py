"""Benchmark runner — evaluate the pipeline against a corpus."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import click


@click.command()
@click.option("--corpus-dir", type=click.Path(exists=True), required=True)
@click.option("--out", type=click.Path(), default="eval/results/")
def main(corpus_dir, out):
    """Run evaluation benchmarks against a reference corpus."""
    corpus_path = Path(corpus_dir)
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)

    pairs = []
    for audio_file in sorted(corpus_path.glob("*.wav")) + sorted(corpus_path.glob("*.mp3")):
        ref_file = audio_file.with_suffix(".txt")
        if ref_file.exists():
            pairs.append((audio_file, ref_file))

    if not pairs:
        click.echo("No audio+reference pairs found in corpus directory.")
        return

    from trusted_transcription.pipeline import Pipeline

    pipeline = Pipeline(repair_enabled=True)
    results = []

    for audio_file, ref_file in pairs:
        click.echo(f"Processing {audio_file.name}...", err=True)
        ref_text = ref_file.read_text(encoding="utf-8").strip()

        try:
            report = pipeline.run(str(audio_file), reference_text=ref_text)
            row = {
                "file": audio_file.name,
                "segments": report.scores.get("total_segments", 0),
                "critical_flags": report.scores.get("critical_flags", 0),
                "hallucination_rate": report.scores.get("hallucination_rate", 0),
                "wer": report.scores.get("wer"),
                "cer": report.scores.get("cer"),
                "cost_usd": report.cost_usd,
                "duration_sec": report.duration_sec,
            }
        except Exception as e:
            row = {"file": audio_file.name, "error": str(e)}

        results.append(row)

    summary_path = out_path / "summary.csv"
    if results:
        fieldnames = list(results[0].keys())
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    detail_path = out_path / "detail.json"
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    click.echo(f"\nResults: {summary_path}")


if __name__ == "__main__":
    main()
