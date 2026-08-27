"""Download and verify public evaluation corpora.

No client data — ever. Three public sources:
1. Assemblee nationale (formal French, multi-speaker, reference transcript)
2. Mozilla Common Voice FR (diverse accents, variable quality)
3. LibriVox FR (long-form, public domain)

The corpus is NOT committed. This script downloads it.
Only corpus/sample/ is committed (smoke test).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import click


CORPUS_DIR = Path(__file__).parent / "data"
SAMPLE_DIR = Path(__file__).parent / "sample"


@click.command()
@click.option("--sample-only", is_flag=True, help="Only verify the committed smoke-test sample")
@click.option("--output", "-o", type=click.Path(), default=str(CORPUS_DIR))
def main(sample_only: bool, output: str):
    """Fetch evaluation corpora for benchmarking."""
    if sample_only:
        sample_files = list(SAMPLE_DIR.glob("*"))
        if not sample_files:
            click.echo("No sample files found in corpus/sample/", err=True)
            sys.exit(1)
        click.echo(f"Sample corpus OK: {len(sample_files)} files in {SAMPLE_DIR}")
        return

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)

    click.echo("Corpus download not yet implemented.")
    click.echo("Place audio files (.wav/.mp3) and reference transcripts (.txt)")
    click.echo(f"in {out}/ with matching filenames.")
    click.echo("See MANIFEST.toml for recommended public sources.")


if __name__ == "__main__":
    main()
