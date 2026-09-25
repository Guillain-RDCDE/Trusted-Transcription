<p align="center">
  <img src=".github/social-preview.png" width="100%" alt="Trusted Transcription — catch confident lies in Whisper output, with no API call">
</p>

# Trusted-Transcription

[![tests](https://github.com/Guillain-RDCDE/Trusted-Transcription/actions/workflows/tests.yml/badge.svg)](https://github.com/Guillain-RDCDE/Trusted-Transcription/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/Guillain-RDCDE/Trusted-Transcription)](https://github.com/Guillain-RDCDE/Trusted-Transcription/releases)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Catch confident lies in automatic transcription — and stop most of them before they exist.**

Whisper produces this on 30 seconds of silence:

> *"Thank you for watching. Please subscribe to my channel."*

Confidence: 0.88. No error, no warning. Your downstream system ingests it as fact.

This project comes from a transcription platform where a wrong word is a legal
liability. Everything in it was learned in production, measured against a
control, and shipped: the detectors that catch the lies, the guards that keep
the repair honest, and the prevention layer that removes the cause.

## Try it in 30 seconds (no API key needed)

```bash
git clone https://github.com/Guillain-RDCDE/Trusted-Transcription.git
cd Trusted-Transcription
pip install -e .
tt detect corpus/sample/silence_hallucination.json --format table
```

```
 SEG  SEVERITY    DETECTOR                   REASON
--------------------------------------------------------------------------------
   2  critical    silence_hallucination      Known phantom phrase: 'Thank you for watching...'
   4  critical    repetition_loop            N-gram 'nous avons constate' repeated 3x in 8 segments
   6  critical    temporal_drift             Timestamp stall: segments 5 and 6 share [55.30-55.30]

Total: 3 flags
```

Zero API calls, and nothing on the clean sample:

```bash
tt detect corpus/sample/clean_transcript.json --format table
# No hallucinations detected.
```

Three small dependencies and no API client. Engines and the repair model are
optional (`pip install -e ".[api]"`). Or without installing anything:

```bash
docker build -t tt . && docker run --rm tt cost 60
```

## What it does

**Prevents.** Most phantom phrases are not the model's fault. They appear on
segments *your pipeline* starved — a few seconds cut at a photo timestamp or a
speaker turn, with no context. `tt windows` shows what the model will hear once
each short segment gets audio on both sides; boundaries never move. Long files
are cut in nine-minute pieces with the cap on the piece, never on the file, and
the proof that nothing was lost is the sum of the durations (`tt chunks`).

**Detects.** Phantom phrases in six languages, repetition loops, a whole output
that is a loop, the vocabulary prompt returned instead of the audio, timestamps
that drift, a language switch, a line mixing writing systems after which
nothing follows the audio any more, minutes of speech with zero words, sections
silently dropped, a name spelled letter by letter next to the misheard word.
Deterministic, auditable, no model in the loop.

**Repairs without making things worse.** The correction model can swallow a
paragraph or lengthen a text until the end repeats; both are caught by
comparing what it was sent with what it returned, and the recovery splits the
text rather than falling back on the raw draft. A broken chunk is
re-transcribed alone, never the whole file. A spelled-out name overrides the
dictated one (`tt spell`).

**Measures honestly.** Every number in the docs was read against a control run,
because Whisper is not deterministic. Comparing engines takes two measures or
none, and a judge you know is biased (`tt bench-report`).

## Where to read next

- **[Reference](docs/REFERENCE.md)** — every command, every detector, the MCP
  server, and the Python entry points.
- **[Failure modes](docs/failure-modes.md)** — the catalog, with the control
  that catches each one.
- **[Architecture decisions](docs/REFERENCE.md#architecture-decisions)** — why
  two models in series, why deterministic before probabilistic, and each
  production incident that turned into a rule. The dead ends are in there too;
  they are the reason the claims are credible.
- **[Measurement pitfalls](docs/measurement-pitfalls.md)** — six ways a
  transcription benchmark lies, learned the expensive way.

## License

MIT — **Guillain d'Erceville** — [guillain@poulpe.us](mailto:guillain@poulpe.us) — [GitHub](https://github.com/Guillain-RDCDE) — [LinkedIn](https://www.linkedin.com/in/guillain-d-erceville)
