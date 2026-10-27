"""Unit and integration tests for the GroundTruthBenchmark evaluator."""

from pathlib import Path
import pytest

from yotta_oee.evaluator.benchmark import GroundTruthBenchmark
from yotta_oee.generator.engine import DataGenerationEngine
from yotta_oee.validator.engine import ValidationEngine


@pytest.fixture(scope="module")
def starter_dataset_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    temp_dir = tmp_path_factory.mktemp("benchmark_starter")
    engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=temp_dir)
    engine.generate_and_export()
    return temp_dir


class TestGroundTruthBenchmark:
    def test_benchmark_evaluation_metrics(self, starter_dataset_path: Path):
        """Run validation, then run benchmark and verify 100% recall of all 5 injected anomalies."""
        engine = ValidationEngine()
        summary = engine.validate_directory(starter_dataset_path)

        gt_file = starter_dataset_path / "ground_truth" / "ground_truth.json"
        benchmark = GroundTruthBenchmark(gt_file)

        # Convert findings to dicts for evaluation
        findings_dicts = [f.to_dict() for f in summary.findings]
        result = benchmark.evaluate(findings_dicts)

        assert result.total_ground_truth_anomalies == 5
        assert result.true_positives == 5
        assert result.false_negatives == 0
        assert result.recall == 1.0  # 100% recall!
        assert result.precision > 0.80
        assert result.f1_score > 0.85

    def test_benchmark_breakdown_by_edge_case(self, starter_dataset_path: Path):
        """Confirm each specific edge case type is marked detected."""
        engine = ValidationEngine()
        summary = engine.validate_directory(starter_dataset_path)

        gt_file = starter_dataset_path / "ground_truth" / "ground_truth.json"
        benchmark = GroundTruthBenchmark(gt_file)
        result = benchmark.evaluate([f.to_dict() for f in summary.findings])

        expected_types = [
            "OVERLAPPING_STATE",
            "UNEXPLAINED_COUNT_DROP",
            "SCRAP_EXCEEDS_TOTAL",
            "INVALID_CYCLE_TIME",
            "BREAKDOWN_OVERLAPS_BREAK",
        ]
        for atype in expected_types:
            assert atype in result.detection_by_type
            assert result.detection_by_type[atype]["detected"] == 1
