"""Engine bench — two measures or none, and a judge you know is biased.

The question comes up in every transcription shop: *can the expensive
engine be replaced by a cheaper one?* The honest answer needs a bench
that survives three traps the production one fell into before it was
right.

**Trap 1 — one measure lies.** Accuracy alone (the share of produced
words found in the human-validated text) rewards an engine that
transcribes half the file and gets that half right. A distilled
model looked competitive on accuracy and had returned barely half
the words. Every row therefore carries **two measures**: accuracy
*and* production (words returned, relative to the reference). A
verdict is read on both, never on one.

**Trap 2 — the judge is biased.** The reference is a human-corrected
text, and the human corrected the output of *one* engine, so the
reference resembles that engine. The bench records, per file, which
engine's draft the reference was corrected from, and reports the
comparison **inside each group**. An engine that wins where the
reference favours it *and* where it favours the other one really
wins. In production the paid engine won in both groups; the gap was
eight points, and that is what the monthly bill was buying.

**Trap 3 — the runtime is part of the engine.** Quantising to
eight-bit cost one local model four to five points, left another
untouched, and made a third *gain* because it produced more words.
The differences being sought are of the same order, so a bench in
eight-bit gives a wrong verdict. Measure with the production
precision, and record it on every row.

Plus the operational rules that made the bench rerunnable: results
are stored one row per (engine, file) and a measured pair is skipped
on the next run, so the sample can grow without recomputing; a
resource gate refuses to load a model when the shared accelerator is
short of memory (production comes first); heavy campaigns run at
night.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


# --- the two measures ------------------------------------------------------------


def accuracy(reference: str, hypothesis: str) -> float:
    """Share of the hypothesis' words that align with the reference.

    Word-level alignment; a word counts when it sits in a matching
    block. Read together with ``production`` — alone it rewards an
    engine that says little and says it right.
    """
    ref, hyp = words(reference), words(hypothesis)
    if not hyp:
        return 0.0
    matcher = SequenceMatcher(a=ref, b=hyp, autojunk=False)
    matched = sum(size for _, _, size in matcher.get_matching_blocks())
    return matched / len(hyp)


def production(reference: str, hypothesis: str) -> float:
    """Words returned, relative to the reference. Below ~0.9 something was skipped."""
    ref = len(words(reference))
    if ref == 0:
        return 1.0 if not words(hypothesis) else float("inf")
    return len(words(hypothesis)) / ref


# --- rows and store --------------------------------------------------------------


@dataclass(frozen=True)
class BenchRow:
    engine: str
    file: str
    accuracy: float
    production: float
    precision: str = "float16"
    reference_origin: str = ""
    """Which engine's draft the human corrected to make the reference."""
    seconds: float = 0.0

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.engine, self.file, self.precision)


class ResultStore:
    """One JSON line per row; a measured (engine, file, precision) is skipped."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.rows: dict[tuple[str, str, str], BenchRow] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = BenchRow(**json.loads(line))
                    self.rows[row.key] = row

    def has(self, engine: str, file: str, precision: str = "float16") -> bool:
        return (engine, file, precision) in self.rows

    def add(self, row: BenchRow) -> None:
        self.rows[row.key] = row
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    def all(self) -> list[BenchRow]:
        return list(self.rows.values())


# --- running -----------------------------------------------------------------------

EngineFn = Callable[[str], str]
"""``engine_fn(file) -> hypothesis text``."""


class ResourceGate:
    """Refuse to run when the shared accelerator is short of memory.

    ``free_bytes_fn`` reports the free memory of the device the
    engines load into. Production keeps its own models resident;
    a bench that evicts them is a bench that breaks production.
    """

    def __init__(self, min_free_bytes: int, free_bytes_fn: Callable[[], int]):
        self.min_free_bytes = min_free_bytes
        self.free_bytes_fn = free_bytes_fn

    def allows(self) -> bool:
        return self.free_bytes_fn() >= self.min_free_bytes


class GateClosedError(RuntimeError):
    """The resource gate refused to run: production comes first."""


@dataclass
class RunReport:
    measured: int = 0
    skipped: int = 0
    failed: list[tuple[str, str, str]] = field(default_factory=list)


def run_bench(
    files: Iterable[tuple[str, str, str]],
    engines: dict[str, EngineFn],
    store: ResultStore,
    precision: str = "float16",
    gate: ResourceGate | None = None,
    clock: Callable[[], float] | None = None,
) -> RunReport:
    """Measure every (engine, file) not yet in the store.

    ``files`` yields ``(file, reference_text, reference_origin)``.
    A failing engine call is recorded and never swallowed; the run
    goes on with the next pair.
    """
    report = RunReport()
    for file, reference, origin in files:
        for name, engine in engines.items():
            if store.has(name, file, precision):
                report.skipped += 1
                continue
            if gate is not None and not gate.allows():
                raise GateClosedError(
                    "not enough free memory on the shared device; production first"
                )
            t0 = clock() if clock else 0.0
            try:
                hypothesis = engine(file)
            except Exception as exc:  # noqa: BLE001 - every failure must stay visible
                report.failed.append((name, file, f"{type(exc).__name__}: {exc}"))
                continue
            elapsed = (clock() - t0) if clock else 0.0
            store.add(
                BenchRow(
                    engine=name,
                    file=file,
                    accuracy=round(accuracy(reference, hypothesis), 4),
                    production=round(production(reference, hypothesis), 4),
                    precision=precision,
                    reference_origin=origin,
                    seconds=round(elapsed, 2),
                )
            )
            report.measured += 1
    return report


# --- reading the results ----------------------------------------------------------


@dataclass
class EngineSummary:
    engine: str
    files: int
    accuracy: float
    production: float
    wins_vs_control: int = 0
    losses_vs_control: int = 0
    by_origin: dict[str, float] = field(default_factory=dict)
    """Mean accuracy inside each reference-origin group."""


def summarize(rows: list[BenchRow], control: str | None = None) -> list[EngineSummary]:
    """Per-engine means, paired wins against the control, split by origin.

    Only files measured for **every** engine enter the paired counts,
    so a larger sample for one engine cannot inflate its score. The
    ``by_origin`` split is the biased-judge check: read the control's
    margin in the group whose reference favours the *other* engine.
    """
    by_engine: dict[str, dict[str, BenchRow]] = defaultdict(dict)
    for row in rows:
        by_engine[row.engine][row.file] = row
    if not by_engine:
        return []

    common = set.intersection(*(set(files) for files in by_engine.values()))
    summaries: list[EngineSummary] = []
    for engine, files in by_engine.items():
        measured = list(files.values())
        origins: dict[str, list[float]] = defaultdict(list)
        for row in measured:
            if row.reference_origin:
                origins[row.reference_origin].append(row.accuracy)
        summary = EngineSummary(
            engine=engine,
            files=len(measured),
            accuracy=round(sum(r.accuracy for r in measured) / len(measured), 4),
            production=round(sum(r.production for r in measured) / len(measured), 4),
            by_origin={k: round(sum(v) / len(v), 4) for k, v in sorted(origins.items())},
        )
        if control and control in by_engine and engine != control:
            for file in common:
                mine, theirs = files[file].accuracy, by_engine[control][file].accuracy
                if mine > theirs:
                    summary.wins_vs_control += 1
                elif mine < theirs:
                    summary.losses_vs_control += 1
        summaries.append(summary)
    return sorted(summaries, key=lambda s: -s.accuracy)


def disqualified(summary: EngineSummary, min_production: float = 0.9) -> bool:
    """An engine that skips a tenth of the audio is out, whatever its accuracy."""
    return summary.production < min_production
