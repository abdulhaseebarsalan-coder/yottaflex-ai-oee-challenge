"""Tests for independent OEE recomputation, equivalence identity, and range sanity validation rules."""

from pathlib import Path
import polars as pl
import pytest

from yotta_oee.calculator.aggregator import OEECalculatorEngine
from yotta_oee.domain.enums import ValidationRuleId
from yotta_oee.generator.engine import DataGenerationEngine
from yotta_oee.recomputer.engine import IndependentOEERecomputer
from yotta_oee.validator.rules_oee import (
    EffectiveDateRule,
    OEEIdentityRule,
    OEERangeSanityRule,
    OEERecomputeConsistencyRule,
)


@pytest.fixture(scope="module")
def clean_starter_with_aggregates(tmp_path_factory: pytest.TempPathFactory):
    """Generate a clean starter dataset and calculate OEE aggregates."""
    temp_dir = tmp_path_factory.mktemp("clean_oee_test")
    engine = DataGenerationEngine(profile="starter", seed=20261022, output_dir=temp_dir)
    engine.generate_and_export(skip_anomalies=True)

    calc = OEECalculatorEngine(temp_dir)
    agg_csv = temp_dir / "oee_aggregates.csv"
    calc.calculate_all(output_csv=agg_csv, findings=[])

    dataset = {f.name: pl.read_csv(f) for f in temp_dir.glob("*.csv")}
    return temp_dir, agg_csv, dataset


def test_clean_baseline_zero_findings_from_new_rules(clean_starter_with_aggregates):
    """Confirm clean baseline produces zero findings across all new rules."""
    _, _, dataset = clean_starter_with_aggregates

    # 1. VAL-DATE-001 (Effective Dates)
    date_rule = EffectiveDateRule()
    date_findings = date_rule.validate(dataset)
    assert len(date_findings) == 0, f"Expected 0 findings, got {len(date_findings)}: {date_findings}"

    # 2. VAL-OEE-001 (Recompute Consistency)
    recomp_rule = OEERecomputeConsistencyRule()
    recomp_findings = recomp_rule.validate(dataset)
    assert len(recomp_findings) == 0, f"Expected 0 findings, got {len(recomp_findings)}: {recomp_findings}"

    # 3. VAL-OEE-002 (Dual Identity)
    ident_rule = OEEIdentityRule()
    ident_findings = ident_rule.validate(dataset)
    assert len(ident_findings) == 0, f"Expected 0 findings, got {len(ident_findings)}: {ident_findings}"

    # 4. VAL-OEE-003 (Range Sanity)
    range_rule = OEERangeSanityRule()
    range_findings = range_rule.validate(dataset)
    assert len(range_findings) == 0, f"Expected 0 findings, got {len(range_findings)}: {range_findings}"


def test_independent_recomputer_clean_exact_match(clean_starter_with_aggregates):
    """Confirm IndependentOEERecomputer matches oee_aggregates.csv within 1e-6 tolerance."""
    temp_dir, agg_csv, _ = clean_starter_with_aggregates
    recomputer = IndependentOEERecomputer(temp_dir)
    res = recomputer.compare_against_file(agg_csv, tolerance=1e-6)

    assert res["matched"] is True
    assert res["mismatch_count"] == 0
    assert res["compared_count"] > 0


def test_deliberate_tampering_caught_by_recompute_consistency(clean_starter_with_aggregates):
    """Confirm deliberate tampering of an aggregate availability is caught by VAL-OEE-001."""
    _, _, dataset = clean_starter_with_aggregates

    # Tamper with the first row's availability
    tampered_dataset = dict(dataset)
    agg_df = tampered_dataset["oee_aggregates.csv"]

    tampered_agg = agg_df.with_columns(
        pl.when(pl.col("aggregate_id") == agg_df["aggregate_id"][0])
        .then(pl.lit(0.1234))
        .otherwise(pl.col("availability"))
        .alias("availability")
    )
    tampered_dataset["oee_aggregates.csv"] = tampered_agg

    rule = OEERecomputeConsistencyRule()
    findings = rule.validate(tampered_dataset)

    assert len(findings) >= 1
    target_id = agg_df["aggregate_id"][0]
    matched_finding = [f for f in findings if f.record_id == target_id and f.field_name == "availability"]
    assert len(matched_finding) == 1
    assert matched_finding[0].rule_id == ValidationRuleId.VAL_OEE_001


def test_deliberate_tampering_caught_by_dual_identity(clean_starter_with_aggregates):
    """Confirm deliberate tampering of OEE product breaks identity and is caught by VAL-OEE-002."""
    _, _, dataset = clean_starter_with_aggregates

    tampered_dataset = dict(dataset)
    agg_df = tampered_dataset["oee_aggregates.csv"]

    target_id = agg_df["aggregate_id"][0]
    tampered_agg = agg_df.with_columns(
        pl.when(pl.col("aggregate_id") == target_id)
        .then(pl.lit(0.3333))
        .otherwise(pl.col("oee"))
        .alias("oee")
    )
    tampered_dataset["oee_aggregates.csv"] = tampered_agg

    rule = OEEIdentityRule()
    findings = rule.validate(tampered_dataset)

    assert len(findings) >= 1
    matched = [f for f in findings if f.record_id == target_id]
    assert len(matched) == 1
    assert matched[0].rule_id == ValidationRuleId.VAL_OEE_002


def test_deliberate_tampering_caught_by_range_sanity(clean_starter_with_aggregates):
    """Confirm out-of-range metric values are caught by VAL-OEE-003."""
    _, _, dataset = clean_starter_with_aggregates

    tampered_dataset = dict(dataset)
    agg_df = tampered_dataset["oee_aggregates.csv"]

    target_id = agg_df["aggregate_id"][0]
    tampered_agg = agg_df.with_columns(
        pl.when(pl.col("aggregate_id") == target_id)
        .then(pl.lit(1.4500))
        .otherwise(pl.col("availability"))
        .alias("availability")
    )
    tampered_dataset["oee_aggregates.csv"] = tampered_agg

    rule = OEERangeSanityRule()
    findings = rule.validate(tampered_dataset)

    assert len(findings) >= 1
    matched = [f for f in findings if f.record_id == target_id and f.field_name == "availability"]
    assert len(matched) == 1
    assert matched[0].rule_id == ValidationRuleId.VAL_OEE_003
