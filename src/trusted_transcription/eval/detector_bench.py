"""Detector bench — expected flags per transcript, precision and recall per detector.

A labels file names, for each transcript, the detectors that **must**
fire and, implicitly, those that must not. Running the detectors over
the corpus then gives, per detector, the files where it fired
rightly, fired wrongly, or missed — and precision and recall follow.

Two uses, same code:

* on the committed samples, a **regression gate**: the CI fails when
  a detector stops firing where it should, or starts firing where it
  should not;
* on a real corpus of engine outputs, the **table** that says what
  each detector is worth in practice. The numbers then live in the
  generated report, never in prose (see ADR 0011 on why a number
  typed by hand is wrong by the next release).

Labels format (JSON):

    {"silence_hallucination.json": ["silence_hallucination", "repetition_loop"],
     "clean_transcript.json": []}

Detectors not named in any expectation but present in the run are
still scored: a flag on a file whose label does not list it is a
false positive.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from trusted_transcription.detectors import ALL_DETECTORS, Detector
from trusted_transcription.models import TranscriptResult


@dataclass
class DetectorScore:
    detector: str
    true_positives: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        fired = len(self.true_positives) + len(self.false_positives)
        return len(self.true_positives) / fired if fired else None

    @property
    def recall(self) -> float | None:
        expected = len(self.true_positives) + len(self.false_negatives)
        return len(self.true_positives) / expected if expected else None

    @property
    def clean(self) -> bool:
        return not self.false_positives and not self.false_negatives


@dataclass
class BenchReport:
    files: int
    scores: dict[str, DetectorScore]
    missing_files: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.missing_files and all(s.clean for s in self.scores.values())

    def broken(self) -> list[str]:
        """Human-readable list of every broken expectation."""
        lines = [f"missing file: {f}" for f in self.missing_files]
        for name, score in sorted(self.scores.items()):
            lines += [f"{name}: fired but not expected on {f}" for f in score.false_positives]
            lines += [f"{name}: expected but did not fire on {f}" for f in score.false_negatives]
        return lines


def load_labels(path: str | Path) -> dict[str, set[str]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("labels must be an object mapping file name to a list of detectors")
    return {name: set(expected) for name, expected in raw.items()}


def fired_detectors(transcript: TranscriptResult, detectors: list[Detector]) -> set[str]:
    return {flag.detector for d in detectors for flag in d.detect(transcript)}


def run_detector_bench(
    corpus_dir: str | Path,
    labels: dict[str, set[str]],
    detectors: list[Detector] | None = None,
) -> BenchReport:
    detectors = detectors if detectors is not None else list(ALL_DETECTORS)
    corpus = Path(corpus_dir)
    scores: dict[str, DetectorScore] = {}
    for d in detectors:
        scores[d.name] = DetectorScore(d.name)

    per_file: dict[str, tuple[set[str], set[str]]] = {}
    missing: list[str] = []
    for name, expected in sorted(labels.items()):
        path = corpus / name
        if not path.exists():
            missing.append(name)
            continue
        transcript = TranscriptResult.model_validate_json(path.read_text(encoding="utf-8"))
        per_file[name] = (expected, fired_detectors(transcript, detectors))

    seen: dict[str, bool] = defaultdict(bool)
    for name, (expected, fired) in per_file.items():
        for detector in expected | fired:
            seen[detector] = True
            score = scores.setdefault(detector, DetectorScore(detector))
            if detector in expected and detector in fired:
                score.true_positives.append(name)
            elif detector in fired:
                score.false_positives.append(name)
            else:
                score.false_negatives.append(name)

    return BenchReport(files=len(per_file), scores=scores, missing_files=missing)


def render(report: BenchReport) -> str:
    """A fixed-width table, one line per detector, then the verdict."""
    head = f"{'DETECTOR':<24} {'TP':>3} {'FP':>3} {'FN':>3} {'PRECISION':>10} {'RECALL':>8}"
    lines = [head, "-" * len(head)]
    for name in sorted(report.scores):
        s = report.scores[name]
        p = "-" if s.precision is None else f"{s.precision:.0%}"
        r = "-" if s.recall is None else f"{s.recall:.0%}"
        lines.append(
            f"{name:<24} {len(s.true_positives):>3} {len(s.false_positives):>3} "
            f"{len(s.false_negatives):>3} {p:>10} {r:>8}"
        )
    lines.append("")
    if report.clean:
        lines.append(f"{report.files} files, every expectation met.")
    else:
        lines.append(f"{report.files} files, broken expectations:")
        lines += [f"  - {b}" for b in report.broken()]
    return "\n".join(lines)
