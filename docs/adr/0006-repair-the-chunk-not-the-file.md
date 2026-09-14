# ADR 0006: Repair the broken chunk, never fall back on the whole file

## Status
Accepted (deployed in production, August 2026)

## Context
A lawyer's dictation came back "rotten", a re-run changed nothing,
and the reviewer had spent two hours on it. The draft was missing a
third of its words — from the middle, silently. Three of the five
chunks sent to the transcription API had come back with a few dozen
words each instead of well over a thousand: the API had returned the
**vocabulary prompt** it was given, word for word, instead of a
transcription.

Three guards existed and none saw it:

- the *empty output* guard: the output was not empty;
- the *completeness* guard: it compared the input and output of the
  repair stage, which had received the truncated text and preserved
  it faithfully;
- the *tag count* guard: tags are reinjected after correction, so the
  count always matched.

Every guard was looking downstream of the loss. Measured over two
weeks, a heavy tail of dictations lost a fifth or more of their words
this way, and a draft that lost that much was closer to half wrong
than three-quarters right. The reviewer retypes instead of correcting.

The same month, the same API locked into loops on difficult audio:
one word thousands of times, a short sentence hundreds of times. The
downstream stages preserved those too.

## Decision

Two deterministic detectors that work **without a reference**:

1. **Vocabulary echo** (`prompt_echo`): a chunk whose content words
   are mostly words from the prompt is an echo. The detector takes the
   prompt itself, not a list of generic instruction markers.
2. **Degenerate output** (`loop_guard`): one word dominating the
   text, or a block of fifteen words repeated a dozen times or more.

One detector that uses a **second transcription of the same audio**
when there is one (`reference_deficit`): word count per chunk of
audio against the reference, with inline tags stripped from the
reference first.

And one repair rule: **re-transcribe only the broken chunk**, never
fall back on a cheaper engine for the whole file. The ladder is
(1) the chunk without the prompt — the cause of the echo, (2) the
chunk with the prompt again — some failures are transient, (3) the
chunk split in shorter pieces without the prompt. Every attempt goes
through the same acceptance check (not empty, not degenerate, not an
echo, not far short of the expected word count). The first accepted
attempt wins; if none passes, the caller decides.

Cost on a healthy dictation: zero extra API call.

## What the calibration taught

- **Strip the tags from the reference.** A report heavy with photos
  carries dozens of anchors in a row. Counted as words, they made a
  healthy chunk look like a hole. With tags stripped, healthy chunks
  and real holes no longer overlapped at all.
- **A formula repeated is not a loop.** Formal dictation repeats
  ritual phrases on purpose — once per room, per occupant, per
  exhibit. A naive "three repeats" rule flagged them. The separation
  between a refrain and a loop is roughly an order of magnitude: a
  handful of times versus dozens or hundreds. The thresholds sit in
  that gap, and known refrains can be listed explicitly.
- **The complaint was about something else.** The reviewer's real
  grievance was recognition quality on that speaker, which no prompt,
  engine or audio clean-up changed. The hole was real and fixed; the
  quality problem was a separate, non-technical one. Do not let one
  finding absorb the other.

## Consequences
- The detectors sit before the repair stage, on the raw engine output
  — where the loss happens.
- The `reference_deficit` detector is not in the default list: it
  needs a second transcript.
- A chunk that fails every rung stays visible as a flagged hole. A
  visible hole is better than a silent one.
