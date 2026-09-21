"""Tests for the per-language phantom phrases."""

from __future__ import annotations

import pytest

from trusted_transcription.detectors.phantom_phrases import (
    PHANTOM_PHRASES,
    match_phantom,
    patterns_for,
)
from trusted_transcription.detectors.silence_hallucination import SilenceHallucinationDetector
from trusted_transcription.models import Segment, TranscriptResult

OBSERVED = {
    "en": [
        "Thank you for watching.",
        "Thanks for watching!",
        "Subtitles by the Amara.org community",
    ],
    "fr": [
        "Sous-titrage Société Radio-Canada",
        "Sous-titres réalisés par la communauté d'Amara.org",
        "Merci d'avoir regardé cette vidéo !",
        "Sous-titrage ST' 501",
        "Abonnez-vous à la chaîne",
    ],
    "de": ["Untertitel der Amara.org-Community", "Untertitel im Auftrag des ZDF, 2017",
           "Vielen Dank fürs Zuschauen"],
    "es": ["Subtítulos realizados por la comunidad de Amara.org", "Gracias por ver el vídeo"],
    "it": ["Sottotitoli creati dalla comunità Amara.org", "Sottotitoli e revisione a cura di QTSS"],
    "pt": ["Legendas pela comunidade Amara.org", "Obrigado por assistir"],
}

LEGITIMATE = [
    "Thank you, I will call you.",
    "Je vous remercie d'avoir regardé le compteur avec moi.",
    "Nous constatons que la porte est fermée à clé.",
    "Le sous-titre du document est illisible.",
    "Gracias por venir, empezamos la inspección.",
    "I told you.",
]


@pytest.mark.parametrize(
    ("language", "phrase"),
    [(lang, p) for lang, phrases in OBSERVED.items() for p in phrases],
)
def test_observed_phrases_are_caught_in_their_language(language, phrase):
    assert match_phantom(phrase, [language]) is not None


@pytest.mark.parametrize("phrase", LEGITIMATE)
def test_legitimate_speech_is_not_a_phantom(phrase):
    assert match_phantom(phrase) is None


def test_every_language_has_observations_in_this_test():
    assert set(OBSERVED) == set(PHANTOM_PHRASES)


def test_accents_are_optional():
    assert match_phantom("Sous-titrage Societe Radio-Canada", ["fr"]) is not None


def test_language_filter_restricts_the_lists():
    assert match_phantom("Sous-titrage Société Radio-Canada", ["en"]) is None
    assert len(patterns_for(["fr"])) < len(patterns_for(None))


def test_a_segment_that_is_only_you_is_a_stub_but_a_sentence_ending_in_you_is_not():
    assert match_phantom("you") is not None
    assert match_phantom(" You. ") is not None
    assert match_phantom("I will send the report to you") is None


class TestDetectorIntegration:
    def test_french_credit_is_flagged_by_default(self):
        t = TranscriptResult(
            segments=[
                Segment(start=0, end=5, text="Chambre."),
                Segment(start=5, end=7, text="Sous-titrage Société Radio-Canada"),
            ]
        )
        flags = SilenceHallucinationDetector().detect(t)
        phantoms = [f for f in flags if f.reason.startswith("Known phantom")]
        assert [f.segment_index for f in phantoms] == [1]

    def test_sentence_ending_in_you_no_longer_fires(self):
        t = TranscriptResult(
            segments=[Segment(start=0, end=3, text="We will send the full report to you")]
        )
        assert SilenceHallucinationDetector().detect(t) == []
