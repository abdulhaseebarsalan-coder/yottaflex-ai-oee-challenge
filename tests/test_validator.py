"""Unit and integration tests for the multi-rule validation engine."""

import shutil
from pathlib import Path
import pytest
import polars as pl

from yotta_oee.domain.enums import ValidationRuleId
from yotta_oee.generator.engine import DataGenerationEngine
from yotta_oee.validator.engine import ValidationEngine
from yotta_oee.validator.rules_relational import (
    EnumDomainRule,
    FKReferentialIntegrityRule,
    PKUniquenessRule,
)
from yotta_oee.validator.rules_temporal import TemporalMonotonicityRule


@pytest.fixture(scope="module")
def starter_dataset_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    temp_dir = tmp_path_factory.mktemp("validator_starter")
    engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=temp_dir)
    engine.generate_and_export()
    return temp_dir


class TestValidationEngineDetection:
    def test_independent_detection_of_all_five_anomalies(self, starter_dataset_path: Path):
        """Validate that the engine independently catches EC-01 through EC-05."""
        engine = ValidationEngine()
        summary = engine.validate_directory(starter_dataset_path)

        assert summary.total_findings >= 5
        detected_rule_ids = {f.rule_id.value for f in summary.findings}

        # Check all 5 target rules fired
        assert ValidationRuleId.VAL_TIME_002.value in detected_rule_ids, "EC-01 (State Overlap) not detected"
        assert ValidationRuleId.VAL_COUNT_001.value in detected_rule_ids, "EC-02 (Count Drop) not detected"
        assert ValidationRuleId.VAL_QUAL_001.value in detected_rule_ids, "EC-03 (Scrap Overflow) not detected"
        assert ValidationRuleId.VAL_PERF_001.value in detected_rule_ids, "EC-04 (Invalid Cycle Time) not detected"
        assert ValidationRuleId.VAL_TIME_003.value in detected_rule_ids, "EC-05 (Break Collision) not detected"

    def test_validator_succeeds_without_ground_truth_files(self, starter_dataset_path: Path, tmp_path: Path):
        """CRITICAL GOVERNANCE TEST: Prove validator works when ground truth files are completely deleted."""
        # Copy dataset to temporary directory and delete ground_truth files
        blind_dir = tmp_path / "blind_dataset"
        shutil.copytree(starter_dataset_path, blind_dir)

        gt_json = blind_dir / "ground_truth.json"
        gt_csv = blind_dir / "ground_truth.csv"
        if gt_json.exists():
            gt_json.unlink()
        if gt_csv.exists():
            gt_csv.unlink()

        assert not gt_json.exists()
        assert not gt_csv.exists()

        # Run validation engine in completely blind environment
        engine = ValidationEngine()
        summary = engine.validate_directory(blind_dir)

        # Must still discover all 5 anomalies!
        detected_rule_ids = {f.rule_id.value for f in summary.findings}
        assert ValidationRuleId.VAL_TIME_002.value in detected_rule_ids
        assert ValidationRuleId.VAL_COUNT_001.value in detected_rule_ids
        assert ValidationRuleId.VAL_QUAL_001.value in detected_rule_ids
        assert ValidationRuleId.VAL_PERF_001.value in detected_rule_ids
        assert ValidationRuleId.VAL_TIME_003.value in detected_rule_ids


class TestIndividualValidationRules:
    def test_pk_uniqueness_rule_on_duplicate(self):
        rule = PKUniquenessRule()
        df = pl.DataFrame({
            "plant_id": ["PLANT-01", "PLANT-01"],
            "name": ["Facility A", "Facility B"],
        })
        findings = rule.validate({"plants.csv": df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_REL_001
        assert "PLANT-01" in findings[0].message

    def test_fk_referential_integrity_rule_on_orphan(self):
        rule = FKReferentialIntegrityRule()
        plants_df = pl.DataFrame({"plant_id": ["PLANT-01"]})
        lines_df = pl.DataFrame({
            "line_id": ["LINE-01", "LINE-02"],
            "plant_id": ["PLANT-01", "PLANT-99"],  # PLANT-99 is an orphan
        })
        dataset = {"plants.csv": plants_df, "lines.csv": lines_df}
        findings = rule.validate(dataset)
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_REL_002
        assert "PLANT-99" in findings[0].message

    def test_enum_domain_rule_on_invalid_enum(self):
        rule = EnumDomainRule()
        lines_df = pl.DataFrame({
            "line_id": ["LINE-01"],
            "line_type": ["INVALID_LINE_TYPE"],
        })
        findings = rule.validate({"lines.csv": lines_df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_REL_003

    def test_temporal_monotonicity_rule_on_negative_time(self):
        rule = TemporalMonotonicityRule()
        events_df = pl.DataFrame({
            "event_id": ["EVT-01"],
            "start_time": ["2026-01-01T10:00:00Z"],
            "end_time": ["2026-01-01T09:00:00Z"],  # End before start
        })
        findings = rule.validate({"state_events.csv": events_df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_TIME_001

    def test_required_fields_rule_catches_nulls(self):
        from yotta_oee.validator.rules_relational import RequiredFieldsRule
        rule = RequiredFieldsRule()
        df = pl.DataFrame({
            "plant_id": ["PLANT-01", "PLANT-02"],
            "name": ["Facility A", ""],  # Blank name
            "timezone": ["UTC", "UTC"],
            "country": ["USA", "USA"],
        })
        findings = rule.validate({"plants.csv": df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_REL_004
        assert findings[0].record_id == "PLANT-02"

    def test_duration_consistency_rule_catches_discrepancy(self):
        from yotta_oee.validator.rules_temporal import DurationConsistencyRule
        rule = DurationConsistencyRule()
        events_df = pl.DataFrame({
            "event_id": ["EVT-01"],
            "start_time": ["2026-01-01T10:00:00Z"],
            "end_time": ["2026-01-01T10:30:00Z"],  # 1800 seconds
            "duration_sec": [1200],                 # Discrepancy (1200 != 1800)
        })
        findings = rule.validate({"state_events.csv": events_df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_TIME_004
        assert "1800" in findings[0].message

    def test_time_accounting_rule_catches_shift_sum_error(self):
        from yotta_oee.validator.rules_temporal import TimeAccountingRule
        rule = TimeAccountingRule()
        shifts_df = pl.DataFrame({
            "shift_id": ["SHIFT-01"],
            "start_time": ["2026-01-01T06:00:00Z"],
            "end_time": ["2026-01-01T14:00:00Z"],  # 28,800 seconds
        })
        events_df = pl.DataFrame({
            "event_id": ["EVT-01"],
            "machine_id": ["MCH-01"],
            "shift_id": ["SHIFT-01"],
            "duration_sec": [27000],  # 27,000s != 28,800s
        })
        findings = rule.validate({"state_events.csv": events_df, "shifts.csv": shifts_df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_TIME_005
        assert "discrepancy" in findings[0].message

    def test_state_transition_lifecycle_catches_illegal_transition(self):
        from yotta_oee.validator.rules_business import StateTransitionLifecycleRule
        rule = StateTransitionLifecycleRule()
        events_df = pl.DataFrame({
            "event_id": ["EVT-01", "EVT-02"],
            "machine_id": ["MCH-01", "MCH-01"],
            "start_time": ["2026-01-01T06:00:00Z", "2026-01-01T06:30:00Z"],
            "state": ["PLANNED_DOWNTIME", "STARVED"],  # Illegal direct transition
            "order_id": [None, None],
            "reason_code": [None, None],
        })
        findings = rule.validate({"state_events.csv": events_df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_STATE_001

    def test_correction_reference_validity(self):
        from yotta_oee.validator.rules_business import CorrectionReferenceValidityRule
        rule = CorrectionReferenceValidityRule()
        counts_df = pl.DataFrame({
            "count_id": ["CNT-01"],
            "order_id": ["PO-01"],
            "machine_id": ["MCH-01"],
            "timestamp": ["2026-01-01T06:05:00Z"],
            "is_correction": [True],
            "correction_ref_id": [None],  # Missing correction_ref_id!
        })
        findings = rule.validate({"production_counts.csv": counts_df})
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_COUNT_003

    def test_cycle_time_adherence_compares_order_with_master(self):
        from yotta_oee.validator.rules_business import CycleTimeAdherenceRule
        rule = CycleTimeAdherenceRule()
        orders_df = pl.DataFrame({
            "order_id": ["PO-01"],
            "product_id": ["PRD-01"],
            "line_id": ["LINE-01"],
            "planned_cycle_time_sec": [0.35],  # Inconsistent takt time
        })
        std_df = pl.DataFrame({
            "standard_id": ["STD-01"],
            "machine_id": ["MCH-LINE-01-01"],
            "product_id": ["PRD-01"],
            "ideal_cycle_time_sec": [12.0],    # Master engineering standard
        })
        findings = rule.validate({
            "production_orders.csv": orders_df,
            "machine_product_standards.csv": std_df,
        })
        assert len(findings) == 1
        assert findings[0].rule_id == ValidationRuleId.VAL_PERF_001
        assert "0.350s" in findings[0].message
        assert "12.000s" in findings[0].message

