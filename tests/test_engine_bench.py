"""Tests for the engine bench: two measures, a biased judge, an idempotent store."""

from __future__ import annotations

import pytest

from trusted_transcription.eval.engine_bench import (
    BenchRow,
    GateClosedError,
    ResourceGate,
    ResultStore,
    accuracy,
    disqualified,
    production,
    run_bench,
    summarize,
)

REF = (
    "Nous constatons que la porte d'entrée est fermée à clé. Les volets du premier "
    "étage sont clos. La serrure ne présente aucune trace visible. Le compteur "
    "électrique fonctionne. Les murs du salon sont en bon état général."
)


class TestMeasures:
    def test_identical_text(self):
        assert accuracy(REF, REF) == 1.0
        assert production(REF, REF) == 1.0

    def test_half_the_file_done_right_has_high_accuracy_and_low_production(self):
        half = " ".join(REF.split()[: len(REF.split()) // 2])
        assert accuracy(REF, half) == 1.0
        assert production(REF, half) == pytest.approx(0.5, abs=0.05)

    def test_wrong_words_lower_accuracy_not_production(self):
        wrong = REF.replace("serrure", "sirop").replace("compteur", "compte-tours")
        assert accuracy(REF, wrong) < 1.0
        assert production(REF, wrong) == pytest.approx(1.0, abs=0.05)

    def test_empty_hypothesis(self):
        assert accuracy(REF, "") == 0.0
        assert production(REF, "") == 0.0

    def test_case_and_punctuation_do_not_count(self):
        assert accuracy(REF, REF.upper().replace(".", "")) == 1.0


class TestStore:
    def test_rows_persist_and_are_not_remeasured(self, tmp_path):
        path = tmp_path / "results.jsonl"
        store = ResultStore(path)
        store.add(BenchRow("a", "f1", 0.8, 0.97))
        again = ResultStore(path)
        assert again.has("a", "f1")
        assert not again.has("a", "f2")
        assert not again.has("a", "f1", precision="int8")

    def test_precision_is_part_of_the_key(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")
        store.add(BenchRow("a", "f1", 0.8, 0.97, precision="float16"))
        store.add(BenchRow("a", "f1", 0.75, 0.97, precision="int8"))
        assert len(store.all()) == 2


class TestRun:
    def files(self):
        return [("f1", REF, "paid"), ("f2", REF, "local")]

    def test_measures_every_pair_once(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")
        calls: list[str] = []

        def engine(file):
            calls.append(file)
            return REF

        report = run_bench(self.files(), {"paid": engine, "local": engine}, store)
        assert report.measured == 4 and report.skipped == 0
        report = run_bench(self.files(), {"paid": engine, "local": engine}, store)
        assert report.measured == 0 and report.skipped == 4
        assert len(calls) == 4

    def test_failure_is_recorded_not_swallowed(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")

        def broken(file):
            raise TimeoutError("api")

        report = run_bench(self.files(), {"paid": broken}, store)
        assert report.failed == [
            ("paid", "f1", "TimeoutError: api"),
            ("paid", "f2", "TimeoutError: api"),
        ]
        assert store.all() == []

    def test_gate_refuses_when_the_device_is_short(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")
        gate = ResourceGate(min_free_bytes=2_500_000_000, free_bytes_fn=lambda: 1_000_000_000)
        with pytest.raises(GateClosedError):
            run_bench(self.files(), {"paid": lambda f: REF}, store, gate=gate)

    def test_gate_lets_through_when_free(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")
        gate = ResourceGate(2_500_000_000, lambda: 6_000_000_000)
        report = run_bench(self.files(), {"paid": lambda f: REF}, store, gate=gate)
        assert report.measured == 2

    def test_precision_and_origin_are_recorded(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")
        run_bench(self.files(), {"paid": lambda f: REF}, store, precision="int8")
        row = store.all()[0]
        assert (row.precision, row.reference_origin) == ("int8", "paid")

    def test_clock_measures_seconds(self, tmp_path):
        store = ResultStore(tmp_path / "r.jsonl")
        ticks = iter([0.0, 12.0, 100.0, 110.0])
        run_bench(self.files(), {"paid": lambda f: REF}, store, clock=lambda: next(ticks))
        assert [r.seconds for r in store.all()] == [12.0, 10.0]


def rows():
    # Two engines, four files. The reference of f1/f2 was corrected from
    # the paid engine's draft, that of f3/f4 from the local engine's.
    return [
        BenchRow("paid", "f1", 0.86, 0.97, reference_origin="paid"),
        BenchRow("paid", "f2", 0.83, 0.98, reference_origin="paid"),
        BenchRow("paid", "f3", 0.76, 0.96, reference_origin="local"),
        BenchRow("paid", "f4", 0.74, 0.97, reference_origin="local"),
        BenchRow("local", "f1", 0.75, 0.95, reference_origin="paid"),
        BenchRow("local", "f2", 0.72, 0.94, reference_origin="paid"),
        BenchRow("local", "f3", 0.71, 0.95, reference_origin="local"),
        BenchRow("local", "f4", 0.70, 0.96, reference_origin="local"),
        BenchRow("distilled", "f1", 0.90, 0.48, reference_origin="paid"),
        BenchRow("distilled", "f2", 0.88, 0.50, reference_origin="paid"),
        BenchRow("distilled", "f3", 0.87, 0.47, reference_origin="local"),
        BenchRow("distilled", "f4", 0.89, 0.49, reference_origin="local"),
    ]


class TestSummary:
    def test_means_and_ordering(self):
        summaries = summarize(rows(), control="paid")
        assert [s.engine for s in summaries] == ["distilled", "paid", "local"]
        paid = next(s for s in summaries if s.engine == "paid")
        assert paid.accuracy == pytest.approx(0.7975)
        assert paid.production == pytest.approx(0.97)

    def test_paired_wins_against_the_control(self):
        summaries = {s.engine: s for s in summarize(rows(), control="paid")}
        record = {e: (s.wins_vs_control, s.losses_vs_control) for e, s in summaries.items()}
        assert record == {"local": (0, 4), "distilled": (4, 0), "paid": (0, 0)}

    def test_the_biased_judge_check(self):
        summaries = {s.engine: s for s in summarize(rows(), control="paid")}
        # The paid engine still leads in the group whose reference favours local.
        assert summaries["paid"].by_origin["local"] > summaries["local"].by_origin["local"]

    def test_high_accuracy_with_half_the_words_is_disqualified(self):
        summaries = {s.engine: s for s in summarize(rows(), control="paid")}
        assert disqualified(summaries["distilled"])
        assert not disqualified(summaries["paid"])

    def test_only_files_measured_for_every_engine_enter_the_paired_counts(self):
        extra = rows() + [BenchRow("local", "f9", 0.99, 1.0, reference_origin="local")]
        summaries = {s.engine: s for s in summarize(extra, control="paid")}
        assert summaries["local"].files == 5
        assert summaries["local"].wins_vs_control + summaries["local"].losses_vs_control == 4

    def test_empty(self):
        assert summarize([]) == []
