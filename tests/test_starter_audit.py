"""Automated pytest integration test suite for the Phase 3 starter dataset audit."""

import json
from pathlib import Path
import pytest

from yotta_oee.generator.engine import DataGenerationEngine
from scripts.audit_starter_dataset import run_audit


@pytest.fixture(scope="module")
def audited_starter_dataset(tmp_path_factory: pytest.TempPathFactory):
    """Generate a starter dataset in a temporary path and run the complete audit."""
    temp_dir = tmp_path_factory.mktemp("audit_starter")
    engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=temp_dir)
    result = engine.generate_and_export()
    audit_results = run_audit(temp_dir)
    return audit_results


def test_audit_verdict_pass(audited_starter_dataset):
    """Confirm overall audit verdict is PASS with zero findings."""
    assert audited_starter_dataset["verdict"] == "PASS"
    assert len(audited_starter_dataset["findings"]) == 0


def test_no_ground_truth_leaks(audited_starter_dataset):
    """Confirm ground truth is not imported or read in domain/generator/calculator modules."""
    assert audited_starter_dataset["metrics"]["ground_truth_leaks"] == 0
    assert audited_starter_dataset["metrics"]["ground_truth_count"] == 5


def test_referential_integrity_zero_orphans(audited_starter_dataset):
    """Confirm zero orphaned foreign keys across all relationships."""
    orphan_counts = audited_starter_dataset["metrics"]["orphan_counts"]
    for rel_name, count in orphan_counts.items():
        assert count == 0, f"Found {count} orphaned records for relationship {rel_name}"


def test_primary_key_uniqueness(audited_starter_dataset):
    """Confirm zero duplicate primary keys in any table."""
    duplicate_counts = audited_starter_dataset["metrics"]["duplicate_counts"]
    for table_name, count in duplicate_counts.items():
        assert count == 0, f"Found {count} duplicate primary keys in {table_name}"


def test_id_regex_patterns(audited_starter_dataset):
    """Confirm all primary keys adhere to their documented regex pattern."""
    pattern_errors = audited_starter_dataset["metrics"]["id_pattern_errors"]
    for id_type, count in pattern_errors.items():
        assert count == 0, f"Found {count} invalid ID patterns for {id_type}"


def test_temporal_integrity_and_anomaly_isolation(audited_starter_dataset):
    """Confirm temporal overlaps are strictly limited to the intentional EC-01 and EC-05 anomalies."""
    assert audited_starter_dataset["metrics"]["negative_duration_events"] == 0
    assert audited_starter_dataset["metrics"]["temporal_overlaps_count"] == 2
    assert audited_starter_dataset["metrics"]["invalid_break_durations"] == 0


def test_production_count_reconciliation(audited_starter_dataset):
    """Confirm cumulative counts reconcile perfectly and EC-02 is the only uncorrected drop."""
    assert audited_starter_dataset["metrics"]["cumulative_count_arithmetic_violations"] == 0
    assert audited_starter_dataset["metrics"]["unexplained_count_drops"] == 1


def test_quality_mass_balance_reconciliation(audited_starter_dataset):
    """Confirm quality inspection mass-balance holds and EC-03 is the only violation."""
    assert audited_starter_dataset["metrics"]["qc_mass_balance_violations"] == 1
    assert audited_starter_dataset["metrics"]["scrap_overflows"] == 1


def test_standards_and_ideal_cycle_times(audited_starter_dataset):
    """Confirm cycle times are valid standards and EC-04 is the only invalid takt time."""
    assert audited_starter_dataset["metrics"]["anomalous_standards_count"] == 1
