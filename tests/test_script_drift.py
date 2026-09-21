"""Tests for script drift, empty output and the re-encode helpers."""

from __future__ import annotations

import pytest

from trusted_transcription.detectors.empty_output import EmptyOutputDetector
from trusted_transcription.detectors.script_drift import (
    ScriptDriftDetector,
    first_drift_time,
    foreign_letters,
    script_of,
)
from trusted_transcription.models import Segment, TranscriptResult
from trusted_transcription.prevention.reencode import (
    ffmpeg_reencode_for_upload,
    ffmpeg_tail_command,
    needs_reencode,
)

DRIFTED = (
    "Je crois que témoign限 la gamine. Carinória a 많이 dureивать ou des Bre "
    "Marchessoft lorsque vous êtes là bullet."
)


def transcript(*texts: str, **metadata) -> TranscriptResult:
    return TranscriptResult(
        segments=[
            Segment(start=i * 600.0, end=(i + 1) * 600.0, text=t) for i, t in enumerate(texts)
        ],
        metadata=metadata,
    )


class TestScripts:
    def test_script_of(self):
        assert script_of("é") == "LATIN"
        assert script_of("限") == "CJK"
        assert script_of("많") == "HANGUL"
        assert script_of("и") == "CYRILLIC"
        assert script_of("3") is None
        assert script_of(" ") is None

    def test_foreign_letters(self):
        assert foreign_letters(DRIFTED, "LATIN") == list("限많이ивать")
        assert foreign_letters("Tout va bien, 3 pièces.", "LATIN") == []


class TestScriptDrift:
    def test_drift_point_is_reported_with_the_regeneration_span(self):
        t = transcript(
            "Nous constatons que la porte est fermée.",
            "Le salon est en bon état général.",
            DRIFTED,
            "La suite du constat se poursuit dans la cuisine.",
            language="fr",
            audio_duration_sec=2400.0,
        )
        (flag,) = ScriptDriftDetector().detect(t)
        assert flag.segment_index == 2
        assert flag.evidence["regenerate_from_s"] == 1200.0
        assert flag.evidence["regenerate_to_s"] == 2400.0
        assert flag.evidence["scripts"] == ["CJK", "CYRILLIC", "HANGUL"]
        assert first_drift_time(t) == 1200.0

    def test_only_the_first_drift_carries_the_span(self):
        t = transcript(DRIFTED, "ok", DRIFTED, language="fr")
        first, second = ScriptDriftDetector().detect(t)
        assert "regenerate_from_s" in first.evidence
        assert "regenerate_from_s" not in second.evidence

    def test_clean_transcript_is_silent(self):
        t = transcript("Tout est en ordre.", "Rien à signaler.", language="fr")
        assert ScriptDriftDetector().detect(t) == []
        assert first_drift_time(t) is None

    def test_whole_segment_in_another_script_is_left_to_language_switch(self):
        t = transcript("Tout est en ordre.", "Спасибо за просмотр", language="fr")
        assert ScriptDriftDetector().detect(t) == []

    def test_unknown_language_asserts_nothing(self):
        assert ScriptDriftDetector().detect(transcript(DRIFTED)) == []
        assert ScriptDriftDetector().detect(transcript(DRIFTED, language="ja")) == []

    def test_cyrillic_language_flags_latin_intrusion(self):
        t = transcript("Дверь закрыта на ключ, the door всё в порядке", language="ru")
        (flag,) = ScriptDriftDetector().detect(t)
        assert flag.evidence["scripts"] == ["LATIN"]

    def test_explicit_language_overrides_metadata(self):
        t = transcript(DRIFTED, language="ja")
        assert len(ScriptDriftDetector(language="fr").detect(t)) == 1


class TestEmptyOutput:
    def test_eleven_minutes_and_no_text(self):
        t = TranscriptResult(
            segments=[Segment(start=12.0, end=12.0, text="") for _ in range(33)],
            metadata={"audio_duration_sec": 660.0},
        )
        (flag,) = EmptyOutputDetector().detect(t)
        assert flag.evidence["words"] == 0
        assert flag.evidence["hollow_segments"] == 33
        assert "re-encode" in flag.reason

    def test_no_segments_at_all(self):
        t = TranscriptResult(segments=[], metadata={"audio_duration_sec": 300.0})
        assert len(EmptyOutputDetector().detect(t)) == 1

    def test_only_anchors_count_as_empty(self):
        t = TranscriptResult(
            segments=[Segment(start=0, end=600, text="<photo 0:12> <photo 1:40>")],
            metadata={"audio_duration_sec": 600.0},
        )
        assert len(EmptyOutputDetector().detect(t)) == 1

    def test_short_audio_may_be_silence(self):
        t = TranscriptResult(segments=[], metadata={"audio_duration_sec": 12.0})
        assert EmptyOutputDetector().detect(t) == []

    def test_unknown_duration_asserts_nothing(self):
        assert EmptyOutputDetector().detect(TranscriptResult(segments=[])) == []

    def test_normal_transcript_is_silent(self):
        t = TranscriptResult(
            segments=[Segment(start=0, end=60, text="mot " * 120)],
            metadata={"audio_duration_sec": 60.0},
        )
        assert EmptyOutputDetector().detect(t) == []


class TestReencode:
    @pytest.mark.parametrize("name", ["dictee.wav", "DICTEE.WAV", "a.flac", "b.aiff"])
    def test_formats_reencoded_before_upload(self, name):
        assert needs_reencode(name)

    @pytest.mark.parametrize("name", ["dictee.mp3", "a.m4a", "b.ogg", "noext"])
    def test_formats_sent_as_is(self, name):
        assert not needs_reencode(name)

    def test_reencode_command_is_mono_speech_mp3(self):
        cmd = ffmpeg_reencode_for_upload("in.wav", "out.mp3")
        assert cmd[cmd.index("-ar") + 1] == "16000"
        assert cmd[cmd.index("-ac") + 1] == "1"
        assert cmd[cmd.index("-c:a") + 1] == "libmp3lame"
        assert cmd[cmd.index("-b:a") + 1] == "64k"
        assert cmd[-1] == "out.mp3"

    def test_tail_command_seeks_on_the_input_and_copies(self):
        cmd = ffmpeg_tail_command("in.mp3", "tail.mp3", 2400.0)
        assert cmd.index("-ss") < cmd.index("-i")
        assert cmd[cmd.index("-ss") + 1] == "2400"
        assert cmd[cmd.index("-c") + 1] == "copy"

    def test_tail_command_rejects_negative_start(self):
        with pytest.raises(ValueError):
            ffmpeg_tail_command("in.mp3", "tail.mp3", -1)
