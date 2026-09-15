# ADR 0007: The repair never returns less than the source, nor much more

## Status
Accepted (deployed in production, July 2026)

## Context
A reviewer working from a corrected draft noticed that "a whole
paragraph was missing": the entire description of a bathroom,
dictated, present in the raw transcript, gone from the corrected text.
The correction stage had swallowed a hundred contiguous words.

Nobody had seen it because the only guard on that stage counted
**tags**. Tags are reinjected from the source *after* correction, so
their count always matches — a text loss is structurally invisible to
a tag count. That is a design blind spot, not a setting.

Replaying real corrections and comparing **the text sent to the model
with the text it returned** (the only pair that means anything): a
passage was swallowed on a good half of them, by blocks of a hundred
to more than a thousand words. And it is intermittent — the same
input loses nothing on the next run. Never conclude from one replay.

No delivered document was truncated: the reviewer re-listens to the
audio and restores what is missing. The safety net was human time.

Six days later the mirror image appeared: the end of a report
repeated four or five times. The completeness retry, asked to restore
what it thought was lost, had **lengthened** the text at each level
of recursion, and nothing bounded the stacking.

## Decision

### Loss: net loss per divergent zone
Align source and output **word by word**. On each divergent zone,
the *net* loss is the words removed minus the words added. A
rephrasing replaces — as many words in as out. An amputation removes
without counterpart. A zone with a net loss of fifty words or more is
a swallowed passage; an output under seventy percent of the source is
truncated whatever the zones say. Below fifty words, what was removed
is chatter the correction was right to drop.

A run of one or two matching words inside a deleted passage does not
close the zone: a stray "the" is not restored content.

### Recovery: divide and conquer, never the raw text
The direction was explicit: *no fallback on the raw text, which is
unusable. Just see that a piece is missing and make sure it is there
when we do it again. The workflow is mandatory.*

1. Retry, with the instruction reinforced ("you deleted a whole
   passage — return everything"). It often recovers.
2. If it resists, **split the text in two and correct each half**,
   recursively. A model only swallows on long passages; the shorter
   the piece, the less it can skip.
3. At the floor (a few sentences, no longer splittable), keep the
   *correction* obtained — never the raw text — and record the loss
   as irreducible, so that it is visible in the log and the report.

### Over-production: bounded at every level
The output of a correction never has more words than
`1.15 × source + 8`. Beyond that it is rejected and the previous clean
correction (or the source) is used. The bound applies at **every
level** of the recursion, so a doubling cannot stack: the "end
repeated five times" becomes structurally impossible.

Implementation: `trusted_transcription.repair.completeness_guard`.
The pipeline applies the over-production bound to every replacement
the repair stage proposes.

## What we tried and abandoned

- **"A contiguous block is absent and its content is found nowhere
  else."** Missed the amputation. The vocabulary of a bathroom
  (ceiling, radiator, painted) is found in every other room of the
  report, so the lost block was absolved. *A report is repetitive by
  nature: never judge on global vocabulary.*
- **Sentence-by-sentence matching.** False positives on good work. A
  transcription engine returns river sentences of four hundred words
  without a full stop; the correction splits them properly. No output
  sentence could cover half a river sentence, so hundreds of words
  were declared swallowed while everything was there. *Never assume
  the source is split into sentences.* This is also why the split
  falls back on the word midpoint when there are no sentence
  boundaries.
- **Calibrating against the pre-correction text** instead of the
  model's own input: more than half of the alerts were false, because
  that text still carries the spelled-out names and verbal tics the
  pipeline removes on purpose. The only valid pair is input/output of
  the correction stage.
- **A threshold of thirty words** instead of fifty: below fifty, the
  removed words were off-record chatter, rightly dropped.

## A root cause found while testing the split
The prompt told each continuation chunk "*continue, do not repeat
anything, no new introduction*". When a chunk was resubmitted (a
retry) or halved (a split), the model took its **beginning** for a
repetition and deleted it — the swallowed passage was always at the
head. Retries and sub-chunks now get an "excerpt" instruction
instead. Without the split experiment, this cause would still be
there.

## Consequences
- Retries and splits add calls only on the faulty pieces; a clean
  correction costs nothing more.
- The irreducible counter is the health signal: if it rises, either
  the detector is crying wolf (re-read the input/output pair before
  concluding — two detectors already died there) or the model really
  truncates (revisit the prompt).
- ADR 0004 said the repair must not make things worse; this ADR gives
  it two numbers.
