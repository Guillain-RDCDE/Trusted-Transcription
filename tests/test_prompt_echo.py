"""Tests for the vocabulary-prompt echo detector."""

from __future__ import annotations

from trusted_transcription.detectors.prompt_echo import (
    PromptEchoDetector,
    content_words,
    echo_ratio,
)
from trusted_transcription.models import Segment, Severity, TranscriptResult

PROMPT = (
    "Constat huissier. Plinthes plafond cloison murs huisseries châssis vantaux "
    "linteau ébrasement carrelage faïence robinetterie ballon chauffe-eau "
    "tableau électrique disjoncteur radiateur convecteur VMC"
)


def transcript(*texts: str, **metadata) -> TranscriptResult:
    return TranscriptResult(
        segments=[
            Segment(start=i * 10.0, end=i * 10.0 + 10.0, text=t) for i, t in enumerate(texts)
        ],
        metadata=metadata,
    )


class TestContentWords:
    def test_folds_case_and_accents_and_drops_short_tokens(self):
        assert content_words("Les Châssis, à côté du linteau.") == ["chassis", "cote", "linteau"]


class TestEchoRatio:
    def test_ratio_and_count(self):
        ratio, count = echo_ratio("plinthes plafond cloison jardin", set(content_words(PROMPT)))
        assert count == 4
        assert ratio == 0.75

    def test_no_content_words(self):
        assert echo_ratio("le la de", {"plinthes"}) == (0.0, 0)


class TestVocabularyEcho:
    def test_prompt_returned_verbatim_is_flagged(self):
        t = transcript(
            "Nous sommes au deuxième étage, porte gauche.",
            PROMPT,
            "La cuisine est en bon état.",
        )
        flags = PromptEchoDetector(prompt=PROMPT).detect(t)
        assert [f.segment_index for f in flags] == [1]
        assert flags[0].severity == Severity.CRITICAL
        assert flags[0].evidence["type"] == "vocabulary_echo"

    def test_prompt_can_come_from_metadata(self):
        t = transcript(PROMPT, initial_prompt=PROMPT)
        assert len(PromptEchoDetector().detect(t)) == 1

    def test_normal_speech_using_vocabulary_words_is_not_flagged(self):
        t = transcript(
            "Dans la salle de bain, le carrelage est fissuré près de la robinetterie "
            "et la faïence présente des traces de moisissure sous la fenêtre."
        )
        assert PromptEchoDetector(prompt=PROMPT).detect(t) == []

    def test_short_segment_with_one_vocabulary_word_is_not_flagged(self):
        t = transcript("Le radiateur.")
        assert PromptEchoDetector(prompt=PROMPT).detect(t) == []

    def test_partial_echo_above_threshold(self):
        # Mostly vocabulary with a couple of stray words: still an echo.
        t = transcript("plinthes plafond cloison murs huisseries châssis vantaux jardin")
        assert len(PromptEchoDetector(prompt=PROMPT).detect(t)) == 1

    def test_without_prompt_only_markers_apply(self):
        t = transcript(PROMPT)
        assert PromptEchoDetector().detect(t) == []


class TestInstructionMarkers:
    def test_system_prompt_leak(self):
        t = transcript("system: You are a helpful transcription assistant.")
        (flag,) = PromptEchoDetector().detect(t)
        assert flag.evidence["type"] == "instruction_marker"

    def test_reasoning_leak_is_a_warning(self):
        t = transcript("Let me think about what the transcription shows here.")
        (flag,) = PromptEchoDetector().detect(t)
        assert flag.severity == Severity.WARNING
        assert flag.evidence["type"] == "reasoning_marker"
