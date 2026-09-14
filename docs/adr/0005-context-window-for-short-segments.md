# ADR 0005: Detection is not enough — stop starving the model

## Status
Accepted (deployed in production, August 2026)

## Context
The seven detectors catch phantom phrases *after* Whisper produced
them. In production the repair pass then deletes almost all of them
before a human sees the draft. That looked like a solved problem
until a reviewer parked a report for "misplaced photo anchors": the
anchors were correct to the hundredth of a second. What had happened
was that room names dictated in short bursts between photos
("Bedroom", "WC", "Shower room") had come back as `This is it.`,
`Merci d'avoir regardé cette vidéo !` and `Sous-titrage Société
Radio-Canada`. The repair pass deleted the garbage — and with it the
only word that separated two groups of photos. Two rooms were
silently merged. The reviewer saw stacked photos, not a hallucination.

A correction applied after the model has spoken arrives too late
whenever the hallucination *replaced* a real word instead of being
added to silence.

### Where the phantom phrases came from
The pipeline cuts the audio at every photo timestamp, so that each
photo can be anchored to a segment boundary. Between two bursts of
photos this produces slices of one to five seconds that the model
transcribes with no context at all. Measured over a month of
production dictations:

- forced short segments hallucinated about **nineteen times** more
  often than the other segments, and almost every phantom phrase sat
  on one of them;
- the rate fell to the noise floor above ten seconds of audio;
- dictations without photos — hence without forced cuts — had about
  **twenty times fewer** phantom phrases per hour of audio, same
  clients, same period;
- removing the forced cuts in an experiment made most of the phantom
  phrases disappear.

The cause was ours, not the model's.

## Decision
Keep the cuts. Change what the model hears.

For every segment shorter than ten seconds, the audio sent to the
model is widened by ten seconds on each side (clamped to the file).
The model transcribes the widened window with word timestamps, and we
keep only the words whose **midpoint** falls inside the original
segment. Segment boundaries, audio coverage and photo anchors are
byte-identical to the previous behaviour. Segments above the
threshold go through the original path, untouched.

Two defensive fallbacks, both counted so that a silent drift is
visible: if the widened window yields no word inside the segment, or
if the engine returns timestamps outside the audio it was given, the
segment is re-transcribed the original way.

The padded window is decoded **without** anti-repetition penalties
(see "What we tried" below).

Implementation: `trusted_transcription.prevention.context_window`.
Operator view: `tt windows <cuts.json>`.

## Result
Read against a control run with identical parameters on the same
corpus (Whisper is not deterministic — see
[measurement pitfalls](../measurement-pitfalls.md)):

| | Change vs control |
|---|---|
| Phantom phrases | almost eliminated |
| Text quality against the human-validated version | slightly better |
| Audio covered | unchanged |
| Photo anchors | identical count, displacement within noise |
| Transcription time | about a sixth longer |

Rolled out behind a kill switch re-read at every transcription, so
that removing one file restores the previous behaviour without a
restart. Verified end to end through the production endpoint, then by
removing the switch and checking the output was identical to before.

## What we tried and abandoned

- **The engine's own anti-hallucination options**
  (`condition_on_previous_text=False`,
  `hallucination_silence_threshold`). Effect within the measurement
  noise. They address silence, not starvation.
- **No forced cuts at all.** Phantom phrases nearly vanished — and
  almost a tenth of the audio was no longer transcribed, up to more
  than half of one dictation. Without the cuts, only what the voice
  activity detector classifies as speech gets transcribed. The forced
  cuts had been guaranteeing full coverage without anyone intending
  it. A fix that "improves the text" by transcribing less of the
  audio is not a fix.
- **Minimum spacing between cuts** (merge cuts closer than eight
  seconds). Fewer phantom phrases, but a small loss of coverage and a
  wave of anchors pushed to the end of the document. Refused.
- **Anti-repetition on the widened window.** The first version kept
  `repetition_penalty` and `no_repeat_ngram_size` on the padded
  window, as on the short path. Quality dropped several times the
  noise floor. Those settings are tuned for slices where a repeated
  n-gram is a loop; on twenty to thirty seconds of dictation the same
  phrases legitimately return dozens of times, and the penalty forces
  the model to invent variants: "marques de peinture" became
  "marquettes de pintures". With the penalties off on the widened
  window only, the worst dictations went from a large loss to a small
  gain.

## Consequences
- The prevention layer sits *before* the detectors. The detectors
  keep their job: what still gets through, and pipelines that do not
  control their own cuts.
- About a sixth more transcription time on dictations with many short
  segments. Accepted.
- The fix is gated on the flow that was measured. Extending it to
  other flows is a separate measurement, not a flag flip.
- The anchors moved on a small share of segments — within the noise
  of two identical runs. Reviewed by hand on a sample: same place or
  better.
