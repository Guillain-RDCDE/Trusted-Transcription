# ADR 0010: Regenerate from the drift point, keep what the human typed

## Status
Accepted (procedure in production since April 2026)

## Context
A reviewer typing along a dictation of more than an hour reported that
after about forty minutes "the audio and the text no longer match":
they heard one thing and read another. The tempting conclusion was to
abandon the draft — and forty minutes of careful work with it.

In the draft, the break was visible as **one short sentence**:

> Je crois que témoign限 la gamine. Carinória a 많이 dureивать ou des
> Bre Marchessoft lorsque vous êtes là bullet.

Characters from other writing systems mixed into French, invented
but plausible names. After that line the text "recovered" — fluent,
well punctuated, in the vocabulary of the domain — and **no longer
followed the audio**. The visible garbage is one line; the damage is
everything after it.

Likely cause: on long audio the engine's voice-activity segmentation
isolates a stretch that falls out of the expected language, the
decoder falls back to automatic language detection, and its state
never fully recovers. No upstream fix was found. What works, every
time, is to transcribe the rest **as a fresh file**.

## Decision
1. **Detect the drift point, not just the garbage.** A segment mixing
   the expected script with letters from another is a drift
   (`detectors/script_drift.py`). The first one carries the span to
   regenerate: from its start to the end of the file. A segment
   wholly in another script is a different failure and is left to
   the language-switch detector.
2. **Re-transcribe from the drift point to the end.** Cut the tail
   with a stream copy (`prevention.reencode.ffmpeg_tail_command`) and
   send it as a new file. The decoder starts clean.
3. **Keep everything before it.** The human's corrected text up to
   the drift point is the most valuable thing in the folder.

## What not to do — learned the hard way
- **Do not write into a draft a reviewer has open.** Their editor
  auto-saves and overwrites the change; or worse, the change
  overwrites theirs. Wait for the lock to be released, or hand the
  regenerated text to a person who passes it on.
- **Do not re-run the full pipeline for this.** It regenerates
  anchors and structure that the reviewer already fixed. Use the
  lightest endpoint that returns corrected text.
- **Do not abandon the dictation.** The reviewer keeps their draft,
  deletes from the garbage line to the end, and pastes the
  regenerated tail.

## Two smaller field lessons recorded with this one

**Empty answer on audible sound: re-encode before blaming the audio.**
An eleven-minute dictation, clear voice, came back with zero words,
twice. The same audio re-encoded as a small mono MP3 transcribed in
full. One container/codec combination made the engine return nothing.
Uncompressed and lossless containers are now re-encoded before the
first upload (`prevention/reencode.py`), and an empty answer on real
audio is a critical flag (`detectors/empty_output.py`) — the coverage
check could not see it, having no segment to measure.

**Phantom phrases follow the decoded language.** A detector that
knows only the English sign-offs is blind to "Sous-titrage Société
Radio-Canada" or "Untertitel im Auftrag des ZDF". The lists are now
per language (`detectors/phantom_phrases.py`) and all checked by
default, because a drifted French dictation returns English credits.
Writing the tests for them exposed a false positive in the original
list: a pattern meant for a segment that is only "you" matched every
sentence *ending* in "you".

## Consequences
- The drift flag is critical even when the text after it reads well:
  that is precisely the dangerous case.
- Languages written in several scripts are not asserted on.
- The regeneration is a procedure with a human in it, not an
  automatic rewrite. That is deliberate: the draft belongs to the
  reviewer while they hold it.
