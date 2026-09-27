"""Download public-domain chapters from the Internet Archive and transcribe them.

    pip install faster-whisper
    python corpus/real/transcribe.py

Writes one transcript per chapter next to this script, in the project's
transcript format. The audio is cached in ``corpus/real/audio/`` (not
committed). Re-running skips chapters already transcribed.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
ITEM = "https://archive.org/download/les_contes_de_la_becasse_0809_librivox/"
CHAPTERS = {
    "01_la_becasse": "lescontesdelabecasse_01_maupassant_64kb.mp3",
    "03_la_folle": "lescontesdelabecasse_03_maupassant_64kb.mp3",
    "05_menuet": "lescontesdelabecasse_05_maupassant_64kb.mp3",
    "10_en_mer": "lescontesdelabecasse_10_maupassant_64kb.mp3",
}
MODEL = "small"
COMPUTE = "int8"


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print("download", url, flush=True)
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel(MODEL, device="cpu", compute_type=COMPUTE)
    for key, name in CHAPTERS.items():
        out = HERE / f"{key}.json"
        if out.exists():
            print("skip", key)
            continue
        audio = AUDIO / f"{key}.mp3"
        fetch(ITEM + name, audio)
        t0 = time.time()
        segments, info = model.transcribe(
            str(audio), language="fr", beam_size=5, word_timestamps=True
        )
        segs = [
            {
                "start": round(s.start, 3),
                "end": round(s.end, 3),
                "text": s.text.strip(),
                "confidence": round(1.0 - (s.no_speech_prob or 0.0), 4),
                "language": "fr",
            }
            for s in segments
        ]
        doc = {
            "segments": segs,
            "metadata": {
                "audio_duration_sec": round(info.duration, 3),
                "model": f"faster-whisper {MODEL} {COMPUTE} cpu",
                "language": "fr",
                "source": ITEM + name,
                "license": "public domain (LibriVox)",
            },
        }
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{key}: {len(segs)} segments, {info.duration:.0f}s audio in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
