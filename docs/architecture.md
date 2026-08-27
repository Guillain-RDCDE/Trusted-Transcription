# Architecture

```
Audio File
    |
    v
[Whisper API / faster-whisper]
    |
    v
TranscriptResult (segments + timestamps + confidence)
    |
    v
[Detectors] ── 7 independent, deterministic, parallel
    |              repetition_loop
    |              silence_hallucination
    |              prompt_echo
    |              temporal_drift
    |              phantom_subtitle
    |              language_switch
    |              completeness
    v
HallucinationFlags (severity + evidence)
    |
    |── no critical flags ──> PASS (auto-deliver)
    |
    v
[LLM Repair] ── Claude, structured output, anti-aggravation guard
    |
    |── declined ──> route to human review
    |── repaired ──> apply + re-score
    v
[Scoring] ── WER, CER, hallucination rate, cost, words/min
    |
    v
PipelineReport (JSON)
```

## Key design choices

See `docs/adr/` for the reasoning behind each.

1. Two models in series, not one fine-tuned model (ADR 0001)
2. Human stays in the loop on critical flags and declined repairs (ADR 0002)
3. Deterministic detection before probabilistic repair (ADR 0003)
4. Repair pass must not make things worse (ADR 0004)

## Integration

The pipeline is exposed three ways:

- **CLI** (`tt run`, `tt detect`, `tt cost`) for operators
- **Python API** (`Pipeline().run(audio_path)`) for embedding
- **MCP server** (`tt-mcp`) for AI agent orchestration
