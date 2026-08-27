# ADR 0004: The repair pass must not make things worse

## Status
Accepted

## Context
An LLM tasked with "fixing" a transcript can introduce new errors. In
our testing, 23% of unconstrained repairs made the text worse — the LLM
confidently replaced a correct-but-unusual word with a common
alternative, or fabricated context to "improve" a sentence.

A repair that makes things worse is strictly worse than no repair at
all: the original transcript had a flagged problem (visible to the
reviewer); the "repaired" transcript has an unflagged problem (invisible).

## Decision
Three guardrails on the repair pass:

1. **Structured output only.** The LLM returns a JSON array of
   `RepairAction` objects with explicit `action`, `confidence`, and
   `reasoning` fields. Free-text corrections are rejected.

2. **Confidence threshold.** Replacements with `confidence < 0.7` are
   downgraded to `keep` — the flag stays, the text is untouched, and
   the segment routes to human review.

3. **Decline is the default.** The system prompt instructs the LLM:
   "when in doubt, return keep." The LLM is not penalized for declining.
   A repair pass where every action is `keep` is a valid, successful
   outcome.

## What we tried and abandoned

- **Diff-based guard**: reject repairs where edit distance > N. Failed
  because legitimate repairs (deleting a hallucinated paragraph)
  naturally have high edit distance.
- **Back-translation guard**: re-transcribe the repaired text with a
  TTS model and compare. Too slow (added 8s per segment) and TTS
  introduced its own errors.
- **Ensemble voting**: run 3 repair attempts, keep the majority.
  Tripled cost for marginal improvement (concordance was >90%).

## Consequences
- Some fixable segments are left unfixed (false `keep`). These route
  to human review, which is the correct fallback.
- Repair rate is lower than an unconstrained LLM would achieve (~40%
  of flagged segments are repaired vs ~75% unconstrained), but the
  repairs that DO happen are reliable.
