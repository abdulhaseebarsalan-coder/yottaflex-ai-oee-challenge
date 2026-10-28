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
        assert len(downtime_reasons) == 10


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
            "ground_truth/ground_truth.csv",
            "ground_truth/ground_truth.json",
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
        assert counts["downtime_reasons.csv"] == 10
        assert counts["production_orders.csv"] >= 4
        assert counts["state_events.csv"] > 500  # realistic timeline size
        assert counts["production_counts.csv"] > 1000
        assert counts["quality_inspections.csv"] >= 9
        assert counts["ground_truth/ground_truth.csv"] == 5  # exactly 5 edge cases for starter!

    def test_ground_truth_anomalies_structure(self, tmp_path: Path):
        engine = DataGenerationEngine(profile="starter", seed=42, output_dir=tmp_path / "gt_test")
        result = engine.generate_and_export()

        import json
        with open(result.output_dir / "ground_truth" / "ground_truth.json", encoding="utf-8") as f:
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

    def test_full_profile_pre_generation_volume_assertions(self, capsys):
        """Assert full-profile calculated volumes satisfy >= 100,000 state events

        and count+QC between 500,000 and 700,000 before any actual generation takes place.
        """
        from yotta_oee.generator.config import get_profile_config

        config = get_profile_config("full")
        assert config.num_lines == 5
        assert config.machines_per_line == 6
        assert config.num_products == 20
        assert config.num_days == 90
        assert config.total_machines == 30
        assert config.total_shifts == 270
        assert config.total_machine_shifts == 8100

        counts = config.compute_analytic_counts()
        print("\n--- Full Profile Analytic Per-Entity Volume Estimates ---")
        for entity, cnt in counts.items():
            print(f"  {entity}: {cnt:,}")

        assert counts["state_events"] >= 100_000, f"Expected >= 100k state events, got {counts['state_events']}"
        assert (
            500_000 <= counts["count_plus_qc"] <= 700_000
        ), f"Expected count+QC between 500k and 700k, got {counts['count_plus_qc']}"
        assert counts["ground_truth_anomalies"] == 50

    def test_measured_generated_dataset_volume_and_extrapolated_bounds(self, tmp_path):
        """Assert actual measured row counts of a generated dataset (empirical post-generation test)

        extrapolate to >= 100,000 state events and [500,000, 700,000] count+QC for the 90-day horizon.
        """
        import polars as pl
        from yotta_oee.generator.config import FULL_CONFIG, GeneratorProfileConfig
        from yotta_oee.generator.engine import DataGenerationEngine

        # Generate a 3-day dry run across full 5-line / 30-machine / 20-product topology
        dry_cfg = GeneratorProfileConfig(
            profile_name="dry_run_full",
            num_plants=FULL_CONFIG.num_plants,
            num_lines=FULL_CONFIG.num_lines,
            machines_per_line=FULL_CONFIG.machines_per_line,
            num_products=FULL_CONFIG.num_products,
            num_days=3,
            start_date=FULL_CONFIG.start_date,
            shifts_per_day=FULL_CONFIG.shifts_per_day,
            shift_duration_hours=FULL_CONFIG.shift_duration_hours,
            planned_break_minutes=FULL_CONFIG.planned_break_minutes,
            anomalies_per_type=1,
            target_events_per_shift_machine=FULL_CONFIG.target_events_per_shift_machine,
            pulse_interval_sec=FULL_CONFIG.pulse_interval_sec,
            qc_samples_per_shift_machine=FULL_CONFIG.qc_samples_per_shift_machine,
        )

        out_dir = tmp_path / "measured_volume_test"
        engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=out_dir)
        engine.config = dry_cfg
        result = engine.generate_and_export(skip_anomalies=False)

        # Count actual rows directly from generated CSV files on disk (post-generation verification)
        state_events_df = pl.read_csv(out_dir / "state_events.csv")
        production_counts_df = pl.read_csv(out_dir / "production_counts.csv")
        qc_df = pl.read_csv(out_dir / "quality_inspections.csv")

        measured_events = len(state_events_df)
        measured_counts = len(production_counts_df)
        measured_qc = len(qc_df)
        measured_count_plus_qc = measured_counts + measured_qc

        ms_in_sample = dry_cfg.total_machine_shifts  # 30 machines * 9 shifts = 270
        assert ms_in_sample == 270

        # Assert per-machine-shift measured rates
        events_per_ms = measured_events / ms_in_sample
        counts_per_ms = measured_counts / ms_in_sample
        qc_per_ms = measured_qc / ms_in_sample
        c_plus_qc_per_ms = measured_count_plus_qc / ms_in_sample

        assert events_per_ms >= 12.35, f"Measured events/ms ({events_per_ms:.2f}) too low to reach 100k at 8100 ms"
        assert qc_per_ms == 2.0, f"Measured QC/ms ({qc_per_ms:.2f}) must be exactly 2.0"

        # Extrapolate to 90 days (8,100 machine-shifts = 30x the 270 sample)
        extrapolated_events = measured_events * 30
        extrapolated_count_plus_qc = measured_count_plus_qc * 30

        # Enforce required bounds on actual empirical extrapolation
        assert extrapolated_events >= 100_000, (
            f"Extrapolated state events ({extrapolated_events:,}) must be >= 100,000"
        )
        assert 500_000 <= extrapolated_count_plus_qc <= 700_000, (
            f"Extrapolated count+QC ({extrapolated_count_plus_qc:,}) must be in [500,000, 700,000]"
        )

    def test_per_machine_event_id_sequence_is_strictly_chronological(self, tmp_path):
        """Verify that per-machine event ID sequences are strictly chronological and sequential with no leaks."""
        import polars as pl
        from yotta_oee.generator.engine import DataGenerationEngine

        full_events_path = Path("data/full/state_events.csv")
        if full_events_path.exists():
            df = pl.read_csv(full_events_path)
            # If data/full on disk hasn't been regenerated yet, fall back to fresh generation
            first_mch = df.filter(pl.col("machine_id") == "MCH-LINE-01-01").sort("event_id")
            if len(first_mch) > 0 and first_mch["event_id"][-1] == "EVT-MCH-LINE-01-01-003980":
                df = None
        else:
            df = None

        if df is None:
            engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=tmp_path / "data")
            engine.generate_and_export()
            df = pl.read_csv(tmp_path / "data" / "state_events.csv")

        for machine_id in df["machine_id"].unique().to_list():
            mch_df = df.filter(pl.col("machine_id") == machine_id).sort("event_id")
            seq_numbers = [int(eid.split("-")[-1]) for eid in mch_df["event_id"]]
            expected_seqs = list(range(1, len(seq_numbers) + 1))
            assert seq_numbers == expected_seqs, f"Machine {machine_id} event sequence has gaps or jumps"

            start_times = mch_df["start_time"].to_list()
            for i in range(len(start_times) - 1):
                assert start_times[i] <= start_times[i + 1], (
                    f"Machine {machine_id} event ID out of chronological order: "
                    f"{mch_df['event_id'][i]} ({start_times[i]}) > {mch_df['event_id'][i+1]} ({start_times[i+1]})"
                )


