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
| 14 | Spelled-out Name | The speaker spelled a name because it was misheard; the draft keeps the wrong name *and* the letters | `spelled_out.py` + `repair/spellings.py` | Medium |
| 15 | Script Drift | One line mixing writing systems on long audio; everything after it reads well and no longer follows the audio | `script_drift.py` | Critical |
| 16 | Empty Output | Minutes of audible speech, a well-formed answer, zero words | `empty_output.py` + `prevention/reencode.py` | Critical |

Modes 11 and 12 are failures of the correction stage, not of the engine ([ADR 0007](adr/0007-completeness-of-the-repair.md)).
Mode 13 is a failure of plumbing ([ADR 0008](adr/0008-cap-the-chunk-not-the-file.md)): the cap belongs on the chunk, and the proof that nothing was lost is the sum of the chunk durations.
Modes 15 and 16 come with a procedure rather than a rewrite ([ADR 0010](adr/0010-regenerate-from-the-drift-point.md)): regenerate from the drift point and keep what the human typed; re-encode before blaming the audio.
Mode 2's phantom phrases are listed **per language** (`phantom_phrases.py`) and all checked by default, because they follow the decoded language, not the expected one.
Mode 14 is the one case where the text itself tells you the engine was wrong ([ADR 0009](adr/0009-the-spelling-is-authoritative.md)): the spelling is authoritative, and the fix is deterministic.
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
