# Measuring a change to an ASR pipeline — five pitfalls

Every number in this repository was read against a control. Here is
why, and the four other traps that produced wrong conclusions before
they were caught. They apply to any A/B comparison on Whisper or a
similar engine.

## 1. Whisper is not deterministic: without a control, every number is wrong

Re-running a few hundred dictations with **strictly identical
parameters** already moves the phantom-phrase rate, the quality score
and the anchor positions. One dictation lost tens of points between
two runs where nothing had changed. On a sample of twenty, the noise
looked like a large improvement; on two hundred it was a small
regression.

Cause: float16 reductions on the GPU are not associative, so logits
differ slightly, and beam decisions flip on the ambiguous passages —
which are exactly the ones that hallucinate.

**Rule: run the control (same parameters) on the same corpus, and read
every result against it. Never against zero.**

## 2. "The word before the anchor changed" is not "the anchor moved"

First measurement of anchor displacement: a quarter to a half of the
anchors. Alarming. Side by side, the photo was at the same place in
the narrative; the *label* had changed, often for the better
("photographes" → "photographies"), and in one case the production
anchor was literally attached to `…une partie du trottoir Merci
d'avoir regardé cette vidéo !`.

Correct measurement: align the two transcripts **word by word**,
project the position of each reference anchor into the variant,
compare with its actual position, and express the gap **in words**.
The displacement fell to the noise floor, with most anchors at zero
words of difference.

## 3. Count anchors *with* the orphans

A pipeline that cannot place an anchor inside the text typically
returns it in an "orphans" block at the end of the document. Counting
only the anchors inside the text makes a variant look like it lost
some. **Total = in-text + orphans**, and that total must be identical.
Report separately the anchors that *moved to the orphan block*: that
is a real regression even with no loss.

## 4. Audio coverage is a measurement of its own

A change can "improve the text" by **no longer transcribing part of
the audio**. Removing the forced cuts (ADR 0005) lost almost a tenth
of the audio — more than half on one dictation — while the number of
anchors did not move at all. Measure the union of the segment
intervals against the file duration, every time.

## 5. An interception must prove itself

A test harness that patches the production code to re-route segments
has to know, for every call, which piece of audio it is handling. If
the expected length and the received length disagree, **fall back to
the production behaviour and increment a counter**. Without the
counter, a drift of one segment would produce wrong results in
silence. `transcribe_with_context` carries the same guard in the
library: `ContextWindowReport.fallbacks_desync`.

## Practical rules that came with them

- **Reference = what production already wrote to disk**, not a re-run:
  more faithful, and half the GPU time.
- **Ground truth for quality = the human-validated text.** It is a
  rewrite, so absolute scores are low; only the *paired difference*
  between variant and control means anything.
- **Take the corpus in natural order** (the most recent eligible
  dictations), never hand-picked.
- **Do not mix a defective variant's results with the others**: move
  the folder aside and verify that every result file carries the
  corrected configuration before reading anything.
- **A dictation can change between the production run and the bench**
  (photos added in the afternoon). The analyser must flag a total
  mismatch, not average it away.
- **The GPU is the bottleneck.** Running the bench in parallel
  changes nothing; run it at night.
