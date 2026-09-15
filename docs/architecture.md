# Architecture

```
Audio File + cut points
    |
    v
[Context window] ── short segments get audio context, boundaries unchanged
    |
    v
[Whisper API / faster-whisper]
    |
    v
TranscriptResult (segments + timestamps + confidence)
    |
    v
[Detectors] ── independent, deterministic, parallel
    |              repetition_loop
    |              silence_hallucination
    |              prompt_echo (markers + vocabulary echo)
    |              temporal_drift
    |              phantom_subtitle
    |              language_switch
    |              completeness
    |              degenerate_output
    |              reference_deficit (opt-in, needs a second transcript)
    v
HallucinationFlags (severity + evidence)
    |
    |── no critical flags ──> PASS (auto-deliver)
    |
    |── echo / loop / deficit on a chunk ──> [Targeted re-transcription]
    |                                          that chunk only: no prompt, prompt, split
    v
[LLM Repair] ── Claude, structured output, anti-aggravation guard
    |              completeness guard: no net loss, never more than source + margin,
    |              retry then split in two, bounded at every level
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
5. Detection is not enough — stop starving the model (ADR 0005)
6. Repair the broken chunk, never fall back on the whole file (ADR 0006)
7. The repair never returns less than the source, nor much more (ADR 0007)

## Integration

The pipeline is exposed three ways:

- **CLI** (`tt run`, `tt detect`, `tt windows`, `tt cost`) for operators
- **Python API** (`Pipeline().run(audio_path)`) for embedding
- **MCP server** (`tt-mcp`) for AI agent orchestration
