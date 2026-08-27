# ADR 0003: Deterministic detection before probabilistic repair

## Status
Accepted

## Context
We have two types of quality checks: deterministic rules (regex,
thresholds, structural checks) and probabilistic checks (LLM-based
semantic analysis). Both catch real problems. The question is how to
order and combine them.

## Decision
Deterministic detectors run FIRST and exhaustively. The LLM repair
pass runs ONLY on segments flagged by deterministic detectors.

## Reasons

1. **Deterministic rules are free.** They run in milliseconds, cost
   nothing, and never hallucinate themselves. Running them first
   filters out obvious cases before the expensive LLM pass.

2. **Deterministic rules are auditable.** When a detector fires, you
   can trace exactly why: this regex matched, this threshold was
   exceeded, this timestamp went backwards. An LLM's "this looks wrong"
   is not auditable.

3. **The LLM is the LAST resort, not the first.** In our testing,
   sending clean segments to the LLM for "extra checking" produced
   false positives 8% of the time — the LLM "found" problems that
   weren't there. Constraining it to pre-flagged segments drops false
   positives to <1%.

4. **Cost control.** At $3/M input tokens, running the LLM on every
   segment of a 1-hour transcript costs ~$0.90. Running it only on
   flagged segments (~5%) costs ~$0.05. The 18x difference matters
   at scale.

## Consequences
- The pipeline misses hallucinations that no deterministic rule catches.
  This is a known gap. We track it as "hallucination escape rate" and
  add new detectors when we find recurring patterns.
- The LLM never sees a "clean" segment — it can't learn from context
  across the full transcript. This is an acceptable tradeoff for cost
  and false positive rate.
