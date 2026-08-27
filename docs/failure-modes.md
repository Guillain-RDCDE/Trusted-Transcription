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

## Not yet automated

- **Synonym substitution**: rare correct word replaced by common alternative. Needs domain vocabulary.
- **Speaker drift**: correct words attributed to wrong speaker. Needs diarization.
- **Numeric hallucination**: plausible wrong number. Needs cross-referencing.

## Key insight

Modes 1-6 produce visible garbage a reviewer can spot. Mode 7 produces nothing. Nothing looks correct. That makes completeness failure the most dangerous mode in production.
