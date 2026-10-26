"""Base interfaces and data structures for the multi-rule validation engine."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import polars as pl

from yotta_oee.domain.enums import Severity, ValidationRuleId


@dataclass
class RuleFinding:
    """Individual data-quality or business-rule violation."""
    rule_id: ValidationRuleId
    severity: Severity
    table_name: str
    record_id: str
    field_name: str
    message: str
    observed_value: Any
    expected_condition: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id.value,
            "severity": self.severity.value,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "field_name": self.field_name,
            "message": self.message,
            "observed_value": str(self.observed_value),
            "expected_condition": self.expected_condition,
            "details": self.details,
        }


@dataclass
class ValidationSummary:
    """Consolidated summary of a validation engine run."""
    run_timestamp: str
    total_rules_evaluated: int
    passed_rules: int
    failed_rules: int
    total_findings: int
    findings_by_rule: Dict[str, int]
    findings_by_severity: Dict[str, int]
    findings: List[RuleFinding]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_timestamp": self.run_timestamp,
            "total_rules_evaluated": self.total_rules_evaluated,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "total_findings": self.total_findings,
            "findings_by_rule": self.findings_by_rule,
            "findings_by_severity": self.findings_by_severity,
            "findings": [f.to_dict() for f in self.findings],
        }


class BaseValidationRule(ABC):
    """Abstract base class for all independent validation rules."""

    @property
    @abstractmethod
    def rule_id(self) -> ValidationRuleId:
        """Unique identifier for this validation rule."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable explanation of rule purpose."""
        pass

    @abstractmethod
    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        """Execute validation against loaded dataset tables.
        
        Args:
            dataset: Dictionary mapping table filenames (e.g. 'state_events.csv')
                     to loaded Polars DataFrames.
                     
        Returns:
            List of RuleFinding objects (empty list if clean).
        """
        pass
