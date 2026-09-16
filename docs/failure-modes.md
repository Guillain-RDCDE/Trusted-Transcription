# Failure Modes Catalog

How an ASR pipeline silently produces confident garbage, and the control that catches each one.

| # | Mode | Symptom | Detector | Danger |
|---|------|---------|----------|--------|
| 1 | Repetition Loop | Same phrase 5-50x in sequence | `repetition_loop.py` | High |
| 2 | Silence Hallucination | Text on silence ("Thank you for watching") | `silence_hallucination.py` | High |
| 3 | Prompt Echo | System prompt or reasoning in output | `prompt_echo.py` | Critical |
| 4 | Temporal Drift | Timestamps overlap, reverse, or stall | `temporal_drift.py` | Medium |
| 5 | Phantom Subtitle | Coherent text unrelated to context | `phantom_subtitle.py` | High |
| 6 | Language Switch | French transcript switches to English | `language_switch.py` | Medium |
| 7 | Completeness Failure | Sections silently missing, no error | `completeness.py` | Critical |
| 8 | Degenerate Output | One word thousands of times, one sentence hundreds | `loop_guard.py` | High |
| 9 | Vocabulary Echo | The engine returns its vocabulary prompt instead of the audio | `prompt_echo.py` | Critical |
| 10 | Chunk Deficit | One chunk far shorter than a second transcript of the same minutes | `reference_deficit.py` | Critical |
| 11 | Swallowed Passage | The *repair* drops a whole paragraph; tags still add up | `repair/completeness_guard.py` | Critical |
| 12 | Over-production | The *repair* lengthens the text; retries stack until the end repeats | `repair/completeness_guard.py` | High |

| 13 | Silent Skip | A file refused for its size before the chunking could apply; no second pass, no error | `prevention/chunking.py` | Critical |

Modes 11 and 12 are failures of the correction stage, not of the engine ([ADR 0007](adr/0007-completeness-of-the-repair.md)).
Mode 13 is a failure of plumbing ([ADR 0008](adr/0008-cap-the-chunk-not-the-file.md)): the cap belongs on the chunk, and the proof that nothing was lost is the sum of the chunk durations.
They are caught by comparing what the model was sent with what it returned — the only pair that means anything.

Modes 9 and 10 are the two faces of the same incident ([ADR 0006](adr/0006-repair-the-chunk-not-the-file.md)):
mode 9 needs only the prompt, mode 10 needs a second transcript. Mode 8 differs from mode 1 in scale —
a local stutter versus a text that is a loop as a whole — and in the calibration that keeps
ritual formulas out of it.

## Root cause you control: starved segments

Modes 2 and 5 are mostly not a property of the model. They are a
property of **what you feed it**. A pipeline that cuts audio at its
own reference points (photo timestamps, speaker turns, chapter marks)
produces slices of a few seconds with no context, and those slices
hallucinate at a rate an order of magnitude above the rest. The
remedy is upstream of every detector: give the model more audio than
the segment and keep only the words that belong to it.
See [ADR 0005](adr/0005-context-window-for-short-segments.md) and
`trusted_transcription.prevention.context_window`.

## Not yet automated

- **Synonym substitution**: rare correct word replaced by common alternative. Needs domain vocabulary.
- **Speaker drift**: correct words attributed to wrong speaker. Needs diarization.
- **Numeric hallucination**: plausible wrong number. Needs cross-referencing.

## Key insight

Modes 1-6, 8 and 12 produce visible garbage a reviewer can spot. Modes 7, 9, 10, 11 and 13 produce *less* — a shorter draft that reads fine, or a draft that never got its second pass. Nothing looks correct. That makes silent loss the most dangerous family in production, and the reason two of its detectors work on the raw engine output rather than after repair.
