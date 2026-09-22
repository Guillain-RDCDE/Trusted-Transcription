# ADR 0011: Two measures or none, and a judge you know is biased

## Status
Accepted (bench in production, August 2026)

## Context
The question came from the top, in plain words: *the paid engine is a
nuisance, what cheaper services could replace it?* Then: *investigate
what we can do better, test it, working at one hundred percent.*

A bench was built on real dictations, with the production settings,
comparing the paid engine to the local models already installed. It
gave a clear answer — and on the way fell into three traps that
would each have produced a wrong verdict.

## Decision

### Two measures, never one
Every row of the bench carries **accuracy** (the share of produced
words that align with the human-validated text) *and* **production**
(the words returned, relative to the reference). A distilled model
looked competitive on accuracy; it had returned barely half the
words. An engine that skips a tenth of the audio is out, whatever its
accuracy says.

### The judge is biased; measure inside each group
The reference is a text corrected by a human — who corrected the
draft of *one* engine, so the reference resembles that engine. The
bench records, for each file, which engine's draft the reference
came from, and reports the comparison **inside each group**. The paid
engine won in the group whose reference favoured it *and* in the
group whose reference favoured the local model. That is what makes
the verdict real: an engine that wins only where the judge likes it
has not won.

### The runtime is part of the engine
Eight-bit quantisation cost one local model four to five points,
left another untouched, and made a third *gain* — because it then
produced more words. The differences being sought are of the same
order. The bench measures with the production precision and records
it on every row; two rows at different precisions are two different
engines.

### Paired against a control, on common files only
An engine's wins are counted file by file against the control, and
only on the files measured for every engine, so that a larger sample
for one engine cannot inflate its score.

### Rerunnable, and polite to production
Results are stored one row per (engine, file, precision); a measured
pair is skipped on the next run, so the sample can grow without
recomputing. A resource gate refuses to load a model when the shared
accelerator is short of memory — production keeps its own models
resident, and a bench that evicts them is a bench that breaks
production. Heavy campaigns run at night, from a scheduled job that
removes itself.

Implementation: `trusted_transcription.eval.engine_bench`.
Operator view: `tt bench-report results.jsonl --control <engine>`.

## What the bench found — and what it did not decide
The paid engine won on every file and in both groups; the local
alternatives lost several points each, and the full-size local model
was *worse* than its turbo variant while being three times slower —
counter-intuitive and constant. The monthly bill was buying a
measurable margin of reviewer time.

The economy, if there is one, is not "switch to free" but "try
another paid engine" — ideally one that returns word timestamps,
which the incumbent refused and which was the root of a whole
machinery of anchor replacement. That needs trial accounts, which the
bench does not open by itself.

## Two things learned on the side
- **A model that returns few words is not necessarily misconfigured.**
  Checked with and without the anti-hallucination settings: the same
  word count. It was not a setting; the model truncates.
- **The prompt echo happened live during the bench** (a few dozen
  words for nine minutes of audio). The failure of ADR 0006 is
  recurrent, not anecdotal — which is why its detector runs without
  a reference.

## Consequences
- A bench row without both measures is rejected by construction: the
  row type has no way to carry one without the other.
- Comparisons across precisions are reported as different engines,
  never averaged.
- Adding a paid engine to the bench is a few lines once a key exists.
