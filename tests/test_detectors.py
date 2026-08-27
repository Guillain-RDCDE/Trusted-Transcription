"""Tests for hallucination detectors.

Each test constructs a synthetic transcript that exhibits exactly one
failure mode, runs the corresponding detector, and asserts it fires.
No audio files, no API calls, no network — pure unit tests.
"""

import pytest

from trusted_transcription.models import Segment, TranscriptResult, Severity


def make_transcript(segments, **metadata):
    return TranscriptResult(
        segments=[Segment(**s) if isinstance(s, dict) else s for s in segments],
        metadata=metadata,
    )


# --- Repetition Loop ---

class TestRepetitionLoop:
    def test_repetition_loop_detected(self):
        from trusted_transcription.detectors.repetition_loop import RepetitionLoopDetector
        detector = RepetitionLoopDetector(ngram_size=3, max_repeats=3, window_segments=10)

        segments = [
            {"start": i * 2.0, "end": i * 2.0 + 2.0, "text": "the quick brown fox"}
            for i in range(10)
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) > 0
        assert flags[0].severity == Severity.CRITICAL
        assert flags[0].detector == "repetition_loop"

    def test_no_false_positive_on_varied_text(self):
        from trusted_transcription.detectors.repetition_loop import RepetitionLoopDetector
        detector = RepetitionLoopDetector()

        texts = [
            "Nous constatons que la porte est fermee a cle",
            "Les volets du premier etage sont clos et verrouilles",
            "La serrure ne presente aucune trace visible",
            "Le compteur electrique fonctionne parfaitement",
            "Les murs du salon sont en bon etat general",
            "La cuisine dispose de tous les equipements prevus",
            "Le balcon donne sur le jardin interieur",
            "Les canalisations ont ete verifiees par le plombier",
            "Le chauffage central est en ordre de marche",
            "Nous procedons maintenant a la verification du toit",
        ]
        segments = [
            {"start": i * 2.0, "end": i * 2.0 + 2.0, "text": texts[i]}
            for i in range(10)
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) == 0


# --- Silence Hallucination ---

class TestSilenceHallucination:
    def test_silence_hallucination_phantom_phrase(self):
        from trusted_transcription.detectors.silence_hallucination import SilenceHallucinationDetector
        detector = SilenceHallucinationDetector()

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Bonjour, nous sommes ici pour le constat."},
            {"start": 5.0, "end": 35.0, "text": "Thank you for watching."},
            {"start": 35.0, "end": 40.0, "text": "Veuillez noter que la porte est fermee."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        phantom_flags = [f for f in flags if "phantom" in f.reason.lower() or "Known" in f.reason]
        assert len(phantom_flags) >= 1
        assert phantom_flags[0].segment_index == 1

    def test_sparse_text_long_segment(self):
        from trusted_transcription.detectors.silence_hallucination import SilenceHallucinationDetector
        detector = SilenceHallucinationDetector()

        segments = [
            {"start": 0.0, "end": 60.0, "text": "Oui."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) >= 1


# --- Prompt Echo ---

class TestPromptEcho:
    def test_prompt_echo_detected(self):
        from trusted_transcription.detectors.prompt_echo import PromptEchoDetector
        detector = PromptEchoDetector()

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Le constat a ete realise le 15 mars."},
            {"start": 5.0, "end": 10.0, "text": "system: You are a helpful transcription assistant."},
            {"start": 10.0, "end": 15.0, "text": "La porte etait ouverte."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) >= 1
        assert flags[0].segment_index == 1
        assert flags[0].severity == Severity.CRITICAL

    def test_reasoning_leak_detected(self):
        from trusted_transcription.detectors.prompt_echo import PromptEchoDetector
        detector = PromptEchoDetector()

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Let me think about what the transcription shows here."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) >= 1


# --- Temporal Drift ---

class TestTemporalDrift:
    def test_temporal_drift_backwards(self):
        from trusted_transcription.detectors.temporal_drift import TemporalDriftDetector
        detector = TemporalDriftDetector()

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Premier segment."},
            {"start": 10.0, "end": 15.0, "text": "Deuxieme segment."},
            {"start": 3.0, "end": 8.0, "text": "Troisieme segment qui revient en arriere."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        backwards = [f for f in flags if "backwards" in f.reason.lower()]
        assert len(backwards) >= 1

    def test_temporal_drift_stall(self):
        from trusted_transcription.detectors.temporal_drift import TemporalDriftDetector
        detector = TemporalDriftDetector()

        segments = [
            {"start": 5.0, "end": 10.0, "text": "Segment A."},
            {"start": 5.0, "end": 10.0, "text": "Segment B identique timestamps."},
            {"start": 5.0, "end": 10.0, "text": "Segment C encore."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        stall = [f for f in flags if "stall" in f.reason.lower()]
        assert len(stall) >= 1

    def test_normal_timestamps_no_flag(self):
        from trusted_transcription.detectors.temporal_drift import TemporalDriftDetector
        detector = TemporalDriftDetector()

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Premier."},
            {"start": 5.0, "end": 10.0, "text": "Deuxieme."},
            {"start": 10.0, "end": 15.0, "text": "Troisieme."},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) == 0


# --- Phantom Subtitle ---

class TestPhantomSubtitle:
    def test_phantom_subtitle_isolated(self):
        from trusted_transcription.detectors.phantom_subtitle import PhantomSubtitleDetector
        detector = PhantomSubtitleDetector(context_window=2, similarity_threshold=0.02)

        legal_text = "le constat a ete dresse en presence des parties concernees"
        segments = [
            {"start": i * 5.0, "end": i * 5.0 + 5.0, "text": f"{legal_text} segment {i}"}
            for i in range(5)
        ]
        segments.insert(3, {
            "start": 15.0, "end": 20.0,
            "text": "the spaceship launched into orbit carrying supplies for the station"
        })
        for i, s in enumerate(segments):
            s["start"] = i * 5.0
            s["end"] = i * 5.0 + 5.0

        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) >= 1


# --- Language Switch ---

class TestLanguageSwitch:
    def test_language_switch_detected(self):
        from trusted_transcription.detectors.language_switch import LanguageSwitchDetector
        detector = LanguageSwitchDetector(expected_language="fr")

        segments = [
            {"start": 0.0, "end": 5.0, "text": "Nous constatons que la porte est fermee.", "language": "fr"},
            {"start": 5.0, "end": 10.0, "text": "The door was found to be closed and locked.", "language": "en"},
            {"start": 10.0, "end": 15.0, "text": "Les cles etaient sur la table.", "language": "fr"},
        ]
        transcript = make_transcript(segments)
        flags = detector.detect(transcript)
        assert len(flags) >= 1
        assert flags[0].segment_index == 1


# --- Completeness ---

class TestCompleteness:
    def test_completeness_low_coverage(self):
        from trusted_transcription.detectors.completeness import CompletenessDetector
        detector = CompletenessDetector(min_coverage_ratio=0.7)

        segments = [
            {"start": 0.0, "end": 30.0, "text": "Premier paragraphe du constat avec beaucoup de details."},
        ]
        transcript = make_transcript(segments, audio_duration_sec=300.0)
        flags = detector.detect(transcript)
        coverage_flags = [f for f in flags if "coverage" in f.reason.lower() or "dropped" in f.reason.lower()]
        assert len(coverage_flags) >= 1
        assert coverage_flags[0].severity == Severity.CRITICAL

    def test_full_coverage_no_flag(self):
        from trusted_transcription.detectors.completeness import CompletenessDetector
        detector = CompletenessDetector()

        segments = [
            {"start": i * 10.0, "end": i * 10.0 + 10.0, "text": f"Segment numero {i} avec du contenu normal."}
            for i in range(6)
        ]
        transcript = make_transcript(segments, audio_duration_sec=60.0)
        flags = detector.detect(transcript)
        coverage_flags = [f for f in flags if "coverage" in f.reason.lower()]
        assert len(coverage_flags) == 0
