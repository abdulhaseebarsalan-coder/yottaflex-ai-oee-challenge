"""Unit and integration tests for the OEECalculatorEngine and aggregation logic."""

from pathlib import Path
import pytest

from yotta_oee.calculator.aggregator import OEECalculatorEngine
from yotta_oee.generator.engine import DataGenerationEngine


@pytest.fixture(scope="module")
def starter_dataset_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    temp_dir = tmp_path_factory.mktemp("calculator_starter")
    engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=temp_dir)
    engine.generate_and_export()
    return temp_dir


class TestOEECalculatorEngine:
    def test_aggregate_generation_and_volume(self, starter_dataset_path: Path):
        """Verify 54 aggregates are generated (9 shifts * 6 machines)."""
        calc = OEECalculatorEngine(starter_dataset_path)
        aggregates, meta = calc.calculate_all()

        # 9 shifts * 6 machines = 54 shift-machine rollups
        assert len(aggregates) == 54
        assert meta["total_aggregates"] == 54

    def test_planned_production_time_accounting(self, starter_dataset_path: Path):
        """Verify PPT dynamically subtracts planned break events from shift duration."""
        calc = OEECalculatorEngine(starter_dataset_path)
        aggregates, _ = calc.calculate_all()

        for agg in aggregates:
            assert agg.planned_prod_time_sec == (28800 - agg.planned_downtime_sec)
            assert agg.planned_prod_time_sec > 0

    def test_metric_boundary_sanity(self, starter_dataset_path: Path):
        """Verify A, P, Q, OEE metric values fall within expected domains."""
        calc = OEECalculatorEngine(starter_dataset_path)
        aggregates, _ = calc.calculate_all()

        for agg in aggregates:
            assert agg.availability >= 0.0
            assert agg.performance >= 0.0
            assert 0.0 <= agg.quality <= 1.0
            assert agg.oee >= 0.0
            assert agg.total_count >= 0
            assert agg.good_count <= agg.total_count

    def test_analytical_equivalence_identity(self, starter_dataset_path: Path):
        """Verify |(A * P * Q) - ((GoodCount * ICT) / PPT)| <= 1e-6."""
        calc = OEECalculatorEngine(starter_dataset_path)
        _, meta = calc.calculate_all()

        eq_meta = meta["equivalence_verification"]
        assert eq_meta["total_verified"] == 54
        # Analytical equivalence identity holds across all 54 aggregates with tolerance <= 1e-6
        assert eq_meta["passed_count"] == 54
        assert eq_meta["failed_count"] == 0

    def test_calculator_consumes_validator_findings(self, starter_dataset_path: Path):
        """Verify calculator applies decision policy from findings, populating status and exception_count."""
        from yotta_oee.domain.enums import AggregateStatus
        from yotta_oee.validator.engine import ValidationEngine

        val_engine = ValidationEngine()
        val_summary = val_engine.validate_directory(starter_dataset_path)

        calc = OEECalculatorEngine(starter_dataset_path)
        aggregates, _ = calc.calculate_all(findings=val_summary.findings)

        statuses = {agg.status for agg in aggregates}
        assert AggregateStatus.CLEAN in statuses
        assert AggregateStatus.ANOMALOUS in statuses

        anomalous_aggs = [agg for agg in aggregates if agg.status == AggregateStatus.ANOMALOUS]
        assert len(anomalous_aggs) >= 1
        for a in anomalous_aggs:
            assert a.exception_count > 0

    def test_clean_baseline_recovery_and_documented_triage(self, tmp_path: Path):
        """Generate clean baseline and mutated dataset; verify zero findings on clean and triage recovery on mutated."""
        from yotta_oee.domain.enums import AggregateStatus
        from yotta_oee.generator.engine import DataGenerationEngine
        from yotta_oee.validator.engine import ValidationEngine

        clean_dir = tmp_path / "clean_baseline"
        mutated_dir = tmp_path / "mutated_dataset"

        # 1. Generate clean baseline (same seed, anomalies bypassed)
        clean_engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=clean_dir)
        clean_res = clean_engine.generate_and_export(skip_anomalies=True)

        # 2. Generate mutated dataset (same seed, anomalies injected)
        mut_engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=mutated_dir)
        mut_res = mut_engine.generate_and_export(skip_anomalies=False)

        # 3. Validate clean baseline -> Must have ZERO findings
        val_engine = ValidationEngine()
        clean_summary = val_engine.validate_directory(clean_dir)
        assert len(clean_summary.findings) == 0, f"Clean baseline had unexpected findings: {clean_summary.findings}"

        # 4. Validate mutated dataset -> Must detect anomalies
        mut_summary = val_engine.validate_directory(mutated_dir)
        assert len(mut_summary.findings) > 0

        # 5. Compute OEE on clean baseline
        clean_calc = OEECalculatorEngine(clean_dir)
        clean_aggs, clean_meta = clean_calc.calculate_all()
        assert clean_meta["equivalence_verification"]["passed_count"] == 54

        # 6. Compute OEE on mutated dataset consuming validator findings
        mut_calc = OEECalculatorEngine(mutated_dir)
        mut_aggs, mut_meta = mut_calc.calculate_all(findings=mut_summary.findings)
        assert mut_meta["equivalence_verification"]["passed_count"] == 54

        clean_by_key = {(a.shift_id, a.machine_id): a for a in clean_aggs}
        mut_by_key = {(a.shift_id, a.machine_id): a for a in mut_aggs}

        for key, clean_agg in clean_by_key.items():
            mut_agg = mut_by_key[key]

            if mut_agg.status == AggregateStatus.CLEAN:
                # Unaffected shift-machines must match clean baseline identically
                assert mut_agg.availability == clean_agg.availability
                assert mut_agg.performance == clean_agg.performance
                assert mut_agg.quality == clean_agg.quality
                assert mut_agg.oee == clean_agg.oee
                assert mut_agg.total_count == clean_agg.total_count
                assert mut_agg.good_count == clean_agg.good_count
                assert mut_agg.planned_prod_time_sec == clean_agg.planned_prod_time_sec
                assert mut_agg.operating_time_sec == clean_agg.operating_time_sec
            else:
                # Affected shift-machines must recover to clean baseline under triage decisions
                # or differ only in the documented way:
                # - EC-01: Earlier event truncated at next start -> operating time reduced by 900s,
                #   planned break increased by 900s, shift sum preserved at exactly 28,800s.
                # - EC-02: Total count is sum of count_delta (excluding negative drop) -> total count recovers.
                # - EC-03: Invalid inspection excluded from Q -> Q computes conforming yield from valid inspections (not Q=0).
                # - EC-04: Performance uses master ICT standard -> performance recovers to clean baseline.
                # - EC-05: Breakdown clipped at break boundary -> availability recovers to clean baseline.
                assert mut_agg.exception_count > 0

                if key == ("SHIFT-2026-01-01-A", "MCH-LINE-01-01"):
                    # EC-01: Later event start clipped to prior end -> operating time, PPT, and OEE recover 100% to clean
                    assert mut_agg.operating_time_sec == clean_agg.operating_time_sec
                    assert mut_agg.planned_prod_time_sec == clean_agg.planned_prod_time_sec
                    assert mut_agg.availability == clean_agg.availability
                    assert mut_agg.performance == clean_agg.performance
                    assert mut_agg.quality == clean_agg.quality
                    assert mut_agg.oee == clean_agg.oee
                    assert (
                        mut_agg.operating_time_sec + mut_agg.planned_downtime_sec + mut_agg.unplanned_downtime_sec
                        == 28800
                    )
                    assert mut_agg.status == AggregateStatus.ANOMALOUS
                elif key == ("SHIFT-2026-01-01-A", "MCH-LINE-01-02"):
                    # EC-02: Documented total_count from sum of valid count_delta (omits single corrupted pulse)
                    assert 0 < clean_agg.total_count - mut_agg.total_count <= 50
                    assert mut_agg.availability == clean_agg.availability
                elif key == ("SHIFT-2026-01-01-A", "MCH-LINE-01-03"):
                    # EC-03: Invalid inspection excluded from Q -> Q computes conforming yield from remaining valid inspections (not Q=0)
                    assert mut_agg.total_count == clean_agg.total_count
                    assert mut_agg.availability == clean_agg.availability
                    assert mut_agg.performance == clean_agg.performance
                    assert 0.90 <= mut_agg.quality <= 1.0
                    assert mut_agg.status == AggregateStatus.ANOMALOUS
                else:
                    assert mut_agg.total_count == clean_agg.total_count
                    assert mut_agg.good_count == clean_agg.good_count
                    assert mut_agg.quality == clean_agg.quality
                    assert mut_agg.performance == clean_agg.performance
                    assert mut_agg.availability == clean_agg.availability
                    assert mut_agg.oee == clean_agg.oee

