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
        """Verify PPT correctly subtracts planned breaks (28,800s - 3,600s = 25,200s)."""
        calc = OEECalculatorEngine(starter_dataset_path)
        aggregates, _ = calc.calculate_all()

        for agg in aggregates:
            assert agg.planned_prod_time_sec == 25200

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
        # At least 50 of 54 should match within 1e-6 (excluding machines with EC-04 cycle time corruptions)
        assert eq_meta["passed_count"] >= 50
