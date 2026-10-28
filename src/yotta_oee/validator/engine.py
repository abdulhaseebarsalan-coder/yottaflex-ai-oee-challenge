"""Validation engine coordinator executing all data-quality and integrity rules."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, List, Optional
import polars as pl
from rich.console import Console
from rich.table import Table

from yotta_oee.domain.enums import Severity
from yotta_oee.validator.base import BaseValidationRule, RuleFinding, ValidationSummary
from yotta_oee.validator.rules_business import (
    CorrectionReferenceValidityRule,
    CountProgressionRule,
    CycleTimeAdherenceRule,
    OrderLifecycleRule,
    PerformancePlausibilityRule,
    QualityMassBalanceRule,
    RunningStateAuthorizationRule,
    StateTransitionLifecycleRule,
)
from yotta_oee.validator.rules_oee import (
    EffectiveDateRule,
    OEERecomputeConsistencyRule,
    OEEIdentityRule,
    OEERangeSanityRule,
)
from yotta_oee.validator.rules_relational import (
    DeDuplicationRule,
    EnumDomainRule,
    FKReferentialIntegrityRule,
    PKUniquenessRule,
    RequiredFieldsRule,
)
from yotta_oee.validator.rules_temporal import (
    BreakDowntimeOverlapRule,
    DurationConsistencyRule,
    StateMutualExclusivityRule,
    TemporalMonotonicityRule,
    TimeAccountingRule,
)

console = Console(safe_box=True)


class ValidationEngine:
    """Orchestrates independent multi-rule validation over manufacturing CSV datasets."""

    def __init__(self, rules: Optional[List[BaseValidationRule]] = None) -> None:
        if rules is not None:
            self.rules = rules
        else:
            # Complete system validation suite
            self.rules = [
                PKUniquenessRule(),
                FKReferentialIntegrityRule(),
                EnumDomainRule(),
                RequiredFieldsRule(),
                DeDuplicationRule(),
                TemporalMonotonicityRule(),
                DurationConsistencyRule(),
                StateMutualExclusivityRule(),
                BreakDowntimeOverlapRule(),
                TimeAccountingRule(),
                EffectiveDateRule(),
                StateTransitionLifecycleRule(),
                CountProgressionRule(),
                CorrectionReferenceValidityRule(),
                RunningStateAuthorizationRule(),
                QualityMassBalanceRule(),
                CycleTimeAdherenceRule(),
                PerformancePlausibilityRule(),
                OrderLifecycleRule(),
                OEERecomputeConsistencyRule(),
                OEEIdentityRule(),
                OEERangeSanityRule(),
            ]

    def validate_directory(
        self,
        data_dir: Path,
        output_report: Optional[Path] = None,
        run_timestamp: Optional[str] = None,
    ) -> ValidationSummary:
        """Load dataset from directory (ignoring ground truth) and run all validation rules."""
        dataset = self._load_dataset(data_dir)
        all_findings: List[RuleFinding] = []
        findings_by_rule: Dict[str, int] = {r.rule_id.value: 0 for r in self.rules}
        findings_by_severity: Dict[str, int] = {
            Severity.ERROR.value: 0,
            Severity.WARNING.value: 0,
            Severity.INFO.value: 0,
        }

        passed_rules = 0
        failed_rules = 0

        for rule in self.rules:
            rule_findings = rule.validate(dataset)
            count = len(rule_findings)
            findings_by_rule[rule.rule_id.value] = count

            if count == 0:
                passed_rules += 1
            else:
                failed_rules += 1
                for f in rule_findings:
                    findings_by_severity[f.severity.value] += 1
                all_findings.extend(rule_findings)

        # Sort findings canonically for bitwise deterministic output across separate runs
        all_findings.sort(key=lambda f: (f.rule_id.value, f.table_name, f.record_id, f.message))

        summary = ValidationSummary(
            run_timestamp=run_timestamp or "2026-10-22T00:00:00Z",
            total_rules_evaluated=len(self.rules),
            passed_rules=passed_rules,
            failed_rules=failed_rules,
            total_findings=len(all_findings),
            findings_by_rule=findings_by_rule,
            findings_by_severity=findings_by_severity,
            findings=all_findings,
        )

        if output_report is not None:
            output_report.parent.mkdir(parents=True, exist_ok=True)
            with open(output_report, "w", encoding="utf-8") as f:
                json.dump(summary.to_dict(), f, indent=2)

        return summary

    @staticmethod
    def _load_dataset(data_dir: Path) -> Dict[str, pl.DataFrame]:
        """Load all primary CSV files from directory, strictly ignoring ground truth."""
        dataset: Dict[str, pl.DataFrame] = {}
        for csv_path in data_dir.glob("*.csv"):
            # GOVERNANCE ENFORCEMENT: Never load ground truth files into validation engine
            if "ground_truth" in csv_path.name.lower():
                continue
            dataset[csv_path.name] = pl.read_csv(csv_path)
        return dataset
