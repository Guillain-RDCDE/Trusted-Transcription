"""Completeness guard for the repair stage — never less, never more.

A language model asked to correct a long passage sometimes **swallows a
paragraph**: the whole description of one room, dictated and present
in the raw transcript, gone from the corrected text. The output reads
fine. Any guard that counts tags or anchors is blind to it, because
those are reinjected from the source after correction and always add
up. Measured in production, a passage was swallowed on a good half of
the corrections replayed, by blocks of a hundred to more than a
thousand words — and intermittently: the same input loses nothing on
the next run.

The same stage can also **over-produce**: asked to restore what it
lost, it lengthens the text instead, and without a bound those
lengthenings stack up through retries until the end of the document
is repeated several times over.

Two invariants, enforced together at every level:

* **Loss** — `lost_passage`: at word level, on each divergent zone
  between source and output, the *net* loss is words removed minus
  words added. A rephrasing replaces (as many words in as out); an
  amputation removes without counterpart. A net loss above
  ``min_net_loss_words`` on one zone, or an output under
  ``min_ratio`` of the source, is a swallowed passage.
* **Over-production** — `overproduces`: the output never has more
  than ``ratio * source + slack`` words. Beyond that it is rejected,
  whatever it says.

`guarded_repair` runs the recovery ladder from production: repair;
if a passage was lost, retry with a reinforced instruction; if it
still resists, **split the text in two and repair each half**,
recursively, because a model only swallows on long passages; at the
floor, keep the correction and record the loss as irreducible. Every
level is bounded by the over-production invariant, so a doubling
cannot stack.

Two detectors were tried before this one and thrown away — see
ADR 0007 for why "vocabulary found elsewhere" and "sentence by
sentence" both fail on real dictation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MIN_NET_LOSS_WORDS = 50
"""Below this, the removed words are chatter the correction was right
to drop (asides, hesitations, an off-record exchange)."""

MIN_RATIO = 0.70
"""An output shorter than this share of the source is truncated,
whatever the zones say."""

MIN_ANCHOR_WORDS = 3
"""A matching run shorter than this does not close a divergent zone."""

OVERPRODUCTION_RATIO = 1.15
OVERPRODUCTION_SLACK = 8
"""``output <= source * ratio + slack``. The slack lets a very short
passage gain a few words of punctuation or a restored name."""

MAX_DEPTH = 4
MAX_RETRIES = 2
MIN_UNITS = 3
"""Do not split below this many sentences: a passage of two sentences
cannot hide a paragraph."""

_WORD = re.compile(r"\S+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def words(text: str) -> list[str]:
    return _WORD.findall(text)


# --- invariants ---------------------------------------------------------------


@dataclass(frozen=True)
class LossReport:
    source_words: int
    output_words: int
    max_net_loss: int
    ratio: float


def net_loss(source: str, output: str, min_anchor_words: int = MIN_ANCHOR_WORDS) -> LossReport:
    """Largest net loss over the divergent zones between source and output.

    A zone is closed only by a run of at least ``min_anchor_words``
    matching words. A passage deleted around one or two surviving
    words ("the", "is") therefore still counts as one loss: a stray
    match inside an amputation is not restored content.
    """
    src, out = words(source), words(output)
    matcher = SequenceMatcher(a=src, b=out, autojunk=False)
    max_net = 0
    zone_removed = zone_added = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" and (i2 - i1) >= min_anchor_words:
            max_net = max(max_net, zone_removed - zone_added)
            zone_removed = zone_added = 0
            continue
        if tag != "equal":
            zone_removed += i2 - i1
            zone_added += j2 - j1
    max_net = max(max_net, zone_removed - zone_added)
    ratio = len(out) / len(src) if src else 1.0
    return LossReport(len(src), len(out), max_net, round(ratio, 3))


def lost_passage(
    source: str,
    output: str,
    min_net_loss_words: int = MIN_NET_LOSS_WORDS,
    min_ratio: float = MIN_RATIO,
) -> tuple[bool, LossReport]:
    """Did the output swallow a passage of the source?"""
    report = net_loss(source, output)
    if report.source_words == 0:
        return False, report
    lost = report.max_net_loss >= min_net_loss_words or report.ratio < min_ratio
    return lost, report


def max_output_words(
    source_words: int,
    ratio: float = OVERPRODUCTION_RATIO,
    slack: int = OVERPRODUCTION_SLACK,
) -> int:
    # Floating point: 100 * 1.15 is 114.99999…; nudge before truncating.
    return int(source_words * ratio + slack + 1e-9)


def overproduces(
    source: str,
    output: str,
    ratio: float = OVERPRODUCTION_RATIO,
    slack: int = OVERPRODUCTION_SLACK,
) -> bool:
    """Does the output have more words than the source can justify?"""
    return len(words(output)) > max_output_words(len(words(source)), ratio, slack)


# --- the ladder ----------------------------------------------------------------

RepairFn = Callable[[str, int], str]
"""``repair_fn(text, attempt) -> corrected text``. ``attempt`` is 0 on
the first call and grows on each retry, so the caller can reinforce
the instruction ("you deleted a whole passage — return everything")."""


@dataclass
class GuardResult:
    text: str
    retries: int = 0
    splits: int = 0
    irreducible: int = 0
    overproduction_rejections: int = 0
    trail: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.irreducible == 0


def guarded_repair(
    text: str,
    repair_fn: RepairFn,
    max_retries: int = MAX_RETRIES,
    max_depth: int = MAX_DEPTH,
    min_units: int = MIN_UNITS,
    min_net_loss_words: int = MIN_NET_LOSS_WORDS,
    min_ratio: float = MIN_RATIO,
    overproduction_ratio: float = OVERPRODUCTION_RATIO,
    overproduction_slack: int = OVERPRODUCTION_SLACK,
) -> GuardResult:
    """Repair ``text`` so that nothing is lost and nothing is invented in bulk."""
    result = GuardResult(text=text)
    result.text = _repair_level(
        text,
        repair_fn,
        result,
        depth=0,
        max_retries=max_retries,
        max_depth=max_depth,
        min_units=min_units,
        min_net_loss_words=min_net_loss_words,
        min_ratio=min_ratio,
        ratio=overproduction_ratio,
        slack=overproduction_slack,
    )
    return result


def _bounded(
    source: str, candidate: str, result: GuardResult, ratio: float, slack: int
) -> str | None:
    """The candidate if it respects the over-production bound, else None."""
    if overproduces(source, candidate, ratio, slack):
        result.overproduction_rejections += 1
        result.trail.append(
            f"rejected: {len(words(candidate))} words for {len(words(source))} in the source"
        )
        return None
    return candidate


def _repair_level(
    text: str,
    repair_fn: RepairFn,
    result: GuardResult,
    depth: int,
    max_retries: int,
    max_depth: int,
    min_units: int,
    min_net_loss_words: int,
    min_ratio: float,
    ratio: float,
    slack: int,
) -> str:
    first_clean: str | None = None
    corrected = _bounded(text, repair_fn(text, 0), result, ratio, slack)
    if corrected is not None:
        first_clean = corrected
        lost, _ = lost_passage(text, corrected, min_net_loss_words, min_ratio)
        if not lost:
            return corrected

    # Retry with a reinforced instruction.
    for attempt in range(1, max_retries + 1):
        result.retries += 1
        candidate = _bounded(text, repair_fn(text, attempt), result, ratio, slack)
        if candidate is None:
            continue
        first_clean = first_clean or candidate
        lost, _ = lost_passage(text, candidate, min_net_loss_words, min_ratio)
        if not lost:
            result.trail.append(f"depth {depth}: recovered on retry {attempt}")
            return candidate

    # Divide and conquer.
    halves = split_in_two(text, min_units)
    if halves is not None and depth < max_depth:
        result.splits += 1
        result.trail.append(f"depth {depth}: split")
        left, right = halves
        repaired = " ".join(
            _repair_level(
                part, repair_fn, result, depth + 1, max_retries, max_depth, min_units,
                min_net_loss_words, min_ratio, ratio, slack,
            )
            for part in (left, right)
        )
        joined = _bounded(text, repaired, result, ratio, slack)
        if joined is not None:
            return joined

    # Floor: keep the correction we have, never the raw text, and say so.
    result.irreducible += 1
    result.trail.append(f"depth {depth}: irreducible loss kept")
    return first_clean if first_clean is not None else text


def split_in_two(text: str, min_units: int = MIN_UNITS) -> tuple[str, str] | None:
    """Split at the sentence boundary closest to the middle.

    Never assume the source is split into sentences: an engine can
    return four hundred words without a full stop. With fewer than
    ``min_units`` sentences the split falls back on the word midpoint,
    and a text under ``2 * min_units`` words is not split at all.
    """
    sentences = [s for s in _SENTENCE_END.split(text.strip()) if s]
    if len(sentences) >= 2 * min_units:
        lengths = [len(words(s)) for s in sentences]
        total = sum(lengths)
        best, running, best_gap = 1, 0, total
        for i, n in enumerate(lengths[:-1], start=1):
            running += n
            gap = abs(total - 2 * running)
            if gap < best_gap:
                best, best_gap = i, gap
        return " ".join(sentences[:best]), " ".join(sentences[best:])

    tokens = words(text)
    if len(tokens) < 2 * min_units:
        return None
    mid = len(tokens) // 2
    return " ".join(tokens[:mid]), " ".join(tokens[mid:])
