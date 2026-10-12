"""Engine responses are read the way the SDKs return them, offline.

The openai SDK hands back pydantic models: ``TranscriptionVerbose.segments``
holds ``TranscriptionSegment`` objects that cannot be subscripted. Older
clients and raw JSON give dicts. The repair model's SDK returns a message
object with ``content[0].text`` and ``usage``. No network, no API key: the
clients are fakes injected in place of the SDK modules.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from trusted_transcription.models import (
    HallucinationFlag,
    Segment,
    Severity,
    TranscriptResult,
)
from trusted_transcription.pipeline import Pipeline, _field
from trusted_transcription.repair.llm_repair import LLMRepairer


class FakeSegment:
    """Attribute access only, like a pydantic model: ``seg["start"]`` raises."""

    def __init__(self, start: float, end: float, text: str, no_speech_prob: float) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.no_speech_prob = no_speech_prob

    def __getitem__(self, key: str) -> Any:
        raise TypeError("'FakeSegment' object is not subscriptable")


def fake_openai(monkeypatch: pytest.MonkeyPatch, response: Any) -> list[dict[str, Any]]:
    """Install a fake ``openai`` module whose client returns ``response``."""
    calls: list[dict[str, Any]] = []

    class Transcriptions:
        def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return response

    class OpenAI:
        def __init__(self) -> None:
            self.audio = types.SimpleNamespace(transcriptions=Transcriptions())

    module = types.ModuleType("openai")
    module.OpenAI = OpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    return calls


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "a.mp3"
    path.write_bytes(b"\x00")
    return path


def pipeline() -> Pipeline:
    return Pipeline(repairer=LLMRepairer(client=object()))  # type: ignore[arg-type]


class TestField:
    def test_dict_and_object(self) -> None:
        assert _field({"start": 1.5}, "start") == 1.5
        assert _field(FakeSegment(2.0, 3.0, "x", 0.1), "start") == 2.0

    def test_missing_gives_default(self) -> None:
        assert _field({}, "no_speech_prob", 0.0) == 0.0
        assert _field(object(), "no_speech_prob", 0.0) == 0.0


class TestTranscribe:
    def test_object_segments(self, monkeypatch: pytest.MonkeyPatch, audio: Path) -> None:
        response = types.SimpleNamespace(
            duration=4.0,
            segments=[
                FakeSegment(0.0, 2.0, " Bonjour.", 0.1),
                FakeSegment(2.0, 4.0, " Au revoir.", 0.25),
            ],
        )
        calls = fake_openai(monkeypatch, response)
        out = pipeline().transcribe(audio)
        assert [(s.start, s.end, s.text) for s in out.segments] == [
            (0.0, 2.0, " Bonjour."),
            (2.0, 4.0, " Au revoir."),
        ]
        assert [s.confidence for s in out.segments] == pytest.approx([0.9, 0.75])
        assert out.metadata["audio_duration_sec"] == 4.0
        assert calls[0]["response_format"] == "verbose_json"

    def test_dict_segments(self, monkeypatch: pytest.MonkeyPatch, audio: Path) -> None:
        response = {
            "duration": 3.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Un.", "no_speech_prob": 0.5},
                {"start": 1.0, "end": 3.0, "text": "Deux."},
            ],
        }
        fake_openai(monkeypatch, response)
        out = pipeline().transcribe(audio)
        assert [s.text for s in out.segments] == ["Un.", "Deux."]
        assert [s.confidence for s in out.segments] == pytest.approx([0.5, 1.0])
        assert out.metadata["audio_duration_sec"] == 3.0

    def test_no_segments(self, monkeypatch: pytest.MonkeyPatch, audio: Path) -> None:
        fake_openai(monkeypatch, types.SimpleNamespace(duration=1.0, segments=None))
        assert pipeline().transcribe(audio).segments == []

    def test_real_sdk_types(self, monkeypatch: pytest.MonkeyPatch, audio: Path) -> None:
        """The SDK's own models, when the api extra is installed."""
        audio_types = pytest.importorskip("openai.types.audio")
        seg = audio_types.TranscriptionSegment(
            id=0,
            avg_logprob=-0.2,
            compression_ratio=1.1,
            end=2.5,
            no_speech_prob=0.2,
            seek=0,
            start=0.5,
            temperature=0.0,
            text=" Bonjour.",
            tokens=[1, 2],
        )
        response = audio_types.TranscriptionVerbose(
            duration=2.5, language="french", text="Bonjour.", segments=[seg]
        )
        fake_openai(monkeypatch, response)
        out = pipeline().transcribe(audio)
        assert [(s.start, s.end, s.text) for s in out.segments] == [(0.5, 2.5, " Bonjour.")]
        assert out.segments[0].confidence == pytest.approx(0.8)


class FakeMessages:
    """Returns a message object: ``content`` blocks and ``usage``, attributes only."""

    def __init__(self, blocks: list[Any]) -> None:
        self.blocks = blocks
        self.calls = 0

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        return types.SimpleNamespace(
            content=self.blocks,
            usage=types.SimpleNamespace(input_tokens=1000, output_tokens=200),
        )


def text_block(text: str) -> Any:
    return types.SimpleNamespace(type="text", text=text)


TRANSCRIPT = TranscriptResult(
    segments=[
        Segment(start=0, end=5, text="Bonjour."),
        Segment(start=5, end=10, text="Thank you for watching."),
    ]
)
FLAG = HallucinationFlag(
    segment_index=1,
    detector="test",
    severity=Severity.CRITICAL,
    reason="test",
)


class TestRepairResponse:
    def repair(self, blocks: list[Any]) -> tuple[Any, FakeMessages]:
        messages = FakeMessages(blocks)
        client = types.SimpleNamespace(messages=messages)
        repairer = LLMRepairer(client=client)  # type: ignore[arg-type]
        return repairer.repair(TRANSCRIPT, [FLAG]), messages

    def test_message_object_is_read(self) -> None:
        result, _ = self.repair([text_block(REPLY)])
        assert [(a.segment_index, a.action) for a in result.actions] == [(1, "delete")]
        assert not result.declined
        assert result.cost_usd == pytest.approx(1000 * 5 / 1e6 + 200 * 25 / 1e6)

    def test_text_block_after_a_thinking_block(self) -> None:
        thinking = types.SimpleNamespace(type="thinking", thinking="...", signature="s")
        result, _ = self.repair([thinking, text_block(REPLY)])
        assert [(a.segment_index, a.action) for a in result.actions] == [(1, "delete")]

    def test_no_text_block_is_retried_then_declined(self) -> None:
        thinking = types.SimpleNamespace(type="thinking", thinking="...", signature="s")
        result, messages = self.repair([thinking])
        assert result.declined
        assert result.actions == []
        assert messages.calls == 3


REPLY = json.dumps(
    [
        {
            "segment_index": 1,
            "original_text": "Thank you for watching.",
            "repaired_text": "",
            "action": "delete",
            "confidence": 0.95,
            "reasoning": "credit",
        }
    ]
)
