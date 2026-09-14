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

Modes 1-6 produce visible garbage a reviewer can spot. Mode 7 produces nothing. Nothing looks correct. That makes completeness failure the most dangerous mode in production.
