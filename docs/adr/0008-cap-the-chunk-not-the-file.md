# ADR 0008: Cap the chunk, never the file

## Status
Accepted (deployed in production, July 2026)

## Context
A reviewer opened a draft that started with the raw date in digits and
a spelled-out company name in parentheses — the signature of a
dictation that never got its second pass. It was an hour of audio.

The transcription API refuses uploads above a size limit, and the
pipeline had a guard for it: *refuse any file above the limit*. That
guard was older than the chunking that had since been added a few
lines below, which splits the file in nine-minute pieces before
sending. The file was rejected **before** the chunking could apply.

For a month, roughly one dictation every two days — the longest
ones, an hour of audio, the ones that give the reviewer the most
work — silently went out without their second pass. Nothing looked
broken. The "relaunch" button, the usual workaround, re-hit the same
guard every time.

## Decision
No cap on the file. The cap is on the **chunk**, where it belongs,
with three nets so that a refusable piece is never sent:

1. Cut the file in chunks of nine minutes, **stream-copied** — no
   re-encode, an hour splits in under a second.
2. The design invariant, checked and not assumed: nine minutes at the
   codec's ceiling bitrate fits under the limit with margin.
3. If a chunk still exceeds the limit (an unusual codec, a higher
   bitrate), **re-cut it shorter and re-encode it**.
4. If it cannot be made to fit, or the file cannot be split, **fail
   visibly** and fall back — the previous behaviour, but seen.

And the proof that nothing was lost: **the durations of the chunks
sum to the duration of the source**, to the millisecond. On the
one-hour file that had been refused for a month: 3468.636 s in,
3468.636 s out, every chunk under the limit.

Implementation: `trusted_transcription.prevention.chunking`.
Operator view: `tt chunks <duration> --bitrate <kb/s>`.

## What it cost
An hour of audio took about six minutes end to end — the same order
as an ordinary dictation. No separate lane in the scheduler was
needed.

## What the measurement corrected
The obvious remedy, "re-run the affected dictations", was **not**
applied. Most had been delivered, two had their correction already
validated (re-running the draft changes nothing downstream), and two
were **being corrected by a human at that moment**. Re-running a
draft under a reviewer's hands throws their work away. The fix was
for the dictations to come.

A subtlety seen the same evening: on the dictation that had triggered
the report, the second pass finally ran and did all its work — and
was **discarded**, because a reviewer had opened a draft twenty
minutes earlier and the draft guard protects human work over
automatic work. The log signature of that outcome (work computed, no
final write) is worth recognising before suspecting a fix.

## Consequences
- A chunk that fails is recorded with its error and the result is
  marked incomplete. The caller sees it. A shorter draft that reads
  fine is the failure mode this repository exists to prevent.
- Every chunk starts at zero (`-reset_timestamps 1`), which is what
  the word-timestamp arithmetic of the context window expects.
- A tool timeout tuned for short files must be raised with the file:
  the split of an hour is fast, the re-encode of a chunk is not.
