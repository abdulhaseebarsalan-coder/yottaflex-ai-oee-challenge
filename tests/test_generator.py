"""Unit and integration tests for the synthetic data generator and anomaly injector."""

from pathlib import Path
import random
import pytest

from yotta_oee.domain import AnomalyType, MachineState, ValidationRuleId
from yotta_oee.generator.config import STARTER_CONFIG
from yotta_oee.generator.engine import DataGenerationEngine
from yotta_oee.generator.master_data import MasterDataGenerator


class TestMasterDataGenerator:
    def test_starter_master_data_quantities(self):
        rng = random.Random(42)
        gen = MasterDataGenerator(STARTER_CONFIG, rng)

        plants = gen.generate_plants()
        assert len(plants) == 1
        assert plants[0].plant_id == "PLANT-01"

        lines = gen.generate_lines(plants)
        assert len(lines) == 2
        assert lines[0].line_id == "LINE-01"
        assert lines[1].line_id == "LINE-02"

        machines = gen.generate_machines(lines)
        assert len(machines) == 6  # 2 lines * 3 machines
        assert machines[0].machine_id == "MCH-LINE-01-01"

        products = gen.generate_products()
        assert len(products) == 4
        assert products[0].product_id == "PRD-0001"

        shifts = gen.generate_shifts(plants[0])
        assert len(shifts) == 9  # 3 days * 3 shifts = 9 shifts
        assert shifts[0].planned_break_sec == 3600

        standards = gen.generate_standards(machines, products)
        assert len(standards) == 24  # 6 machines * 4 products = 24 standards
        for std in standards:
            assert std.ideal_cycle_time_sec > 0.0

        downtime_reasons = gen.get_downtime_reasons()
        assert len(downtime_reasons) == 9


class TestDataGenerationEngineStarter:
    def test_starter_generation_pipeline(self, tmp_path: Path):
        engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=tmp_path / "data")
        result = engine.generate_and_export()

        assert result.profile_name == "starter"
        assert result.seed == 20261022

        # Check required files exist
        expected_files = [
            "plants.csv",
            "lines.csv",
            "machines.csv",
            "products.csv",
            "shifts.csv",
            "machine_product_standards.csv",
            "downtime_reasons.csv",
            "production_orders.csv",
            "state_events.csv",
            "production_counts.csv",
            "quality_inspections.csv",
            "ground_truth.csv",
            "ground_truth.json",
            "manifest.json",
        ]
        for filename in expected_files:
            file_path = result.output_dir / filename
            assert file_path.exists(), f"Missing file: {filename}"
            assert file_path.stat().st_size > 0, f"Empty file: {filename}"

        # Verify row counts
        counts = result.row_counts
        assert counts["plants.csv"] == 1
        assert counts["lines.csv"] == 2
        assert counts["machines.csv"] == 6
        assert counts["products.csv"] == 4
        assert counts["shifts.csv"] == 9
        assert counts["machine_product_standards.csv"] == 24
        assert counts["downtime_reasons.csv"] == 9
        assert counts["production_orders.csv"] >= 4
        assert counts["state_events.csv"] > 500  # realistic timeline size
        assert counts["production_counts.csv"] > 1000
        assert counts["quality_inspections.csv"] >= 9
        assert counts["ground_truth.csv"] == 5  # exactly 5 edge cases for starter!

    def test_ground_truth_anomalies_structure(self, tmp_path: Path):
        engine = DataGenerationEngine(profile="starter", seed=42, output_dir=tmp_path / "gt_test")
        result = engine.generate_and_export()

        import json
        with open(result.output_dir / "ground_truth.json", encoding="utf-8") as f:
            gt_data = json.load(f)

        assert len(gt_data) == 5

        anom_types = {entry["anomaly_type"] for entry in gt_data}
        expected_types = {
            AnomalyType.OVERLAPPING_STATE.value,
            AnomalyType.UNEXPLAINED_COUNT_DROP.value,
            AnomalyType.SCRAP_EXCEEDS_TOTAL.value,
            AnomalyType.INVALID_CYCLE_TIME.value,
            AnomalyType.BREAKDOWN_OVERLAPS_BREAK.value,
        }
        assert anom_types == expected_types

        # Check rule IDs mapped
        rule_ids = {entry["detection_rule_id"] for entry in gt_data}
        expected_rules = {
            ValidationRuleId.VAL_TIME_002.value,
            ValidationRuleId.VAL_COUNT_001.value,
            ValidationRuleId.VAL_QUAL_001.value,
            ValidationRuleId.VAL_PERF_001.value,
            ValidationRuleId.VAL_TIME_003.value,
        }
        assert rule_ids == expected_rules
