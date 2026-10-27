"""Relational and structural integrity validation rules."""

from typing import Dict, List, Set, Tuple
import polars as pl

from yotta_oee.domain.enums import (
    DefectCode,
    DowntimeCategory,
    InspectionType,
    LineType,
    MachineCriticality,
    MachineState,
    OrderStatus,
    Severity,
    ShiftCode,
    ValidationRuleId,
)
from yotta_oee.validator.base import BaseValidationRule, RuleFinding

TABLE_PKS: Dict[str, str] = {
    "plants.csv": "plant_id",
    "lines.csv": "line_id",
    "machines.csv": "machine_id",
    "products.csv": "product_id",
    "shifts.csv": "shift_id",
    "machine_product_standards.csv": "standard_id",
    "downtime_reasons.csv": "reason_code",
    "production_orders.csv": "order_id",
    "state_events.csv": "event_id",
    "production_counts.csv": "count_id",
    "quality_inspections.csv": "inspection_id",
}


class PKUniquenessRule(BaseValidationRule):
    """VAL-REL-001: Every primary key in every entity table must be strictly unique."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_REL_001

    @property
    def description(self) -> str:
        return "Validate that all entity primary keys are strictly unique with zero duplicates."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        for filename, pk in TABLE_PKS.items():
            if filename not in dataset:
                continue
            df = dataset[filename]
            if pk not in df.columns:
                continue

            # Identify duplicate primary keys
            dupes = (
                df.group_by(pk)
                .agg(pl.len().alias("count"))
                .filter(pl.col("count") > 1)
            )

            for row in dupes.iter_rows(named=True):
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name=filename,
                        record_id=str(row[pk]),
                        field_name=pk,
                        message=f"Duplicate primary key '{row[pk]}' detected {row['count']} times in {filename}",
                        observed_value=f"Occurrences: {row['count']}",
                        expected_condition="Primary key must occur exactly once",
                    )
                )

        return findings


class FKReferentialIntegrityRule(BaseValidationRule):
    """VAL-REL-002: Every foreign key must resolve to an existing parent primary key."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_REL_002

    @property
    def description(self) -> str:
        return "Validate referential integrity across all relational foreign keys."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        # Build parent primary key lookup sets
        pks: Dict[str, Set[str]] = {}
        for filename, pk in TABLE_PKS.items():
            if filename in dataset and pk in dataset[filename].columns:
                pks[filename] = set(dataset[filename][pk].to_list())
            else:
                pks[filename] = set()

        fk_definitions: List[Tuple[str, str, str, str, bool]] = [
            # (Child Table, Child FK, Parent Table, Parent PK, Is Nullable)
            ("lines.csv", "plant_id", "plants.csv", "plant_id", False),
            ("machines.csv", "line_id", "lines.csv", "line_id", False),
            ("shifts.csv", "plant_id", "plants.csv", "plant_id", False),
            ("machine_product_standards.csv", "machine_id", "machines.csv", "machine_id", False),
            ("machine_product_standards.csv", "product_id", "products.csv", "product_id", False),
            ("production_orders.csv", "product_id", "products.csv", "product_id", False),
            ("production_orders.csv", "line_id", "lines.csv", "line_id", False),
            ("state_events.csv", "machine_id", "machines.csv", "machine_id", False),
            ("state_events.csv", "shift_id", "shifts.csv", "shift_id", False),
            ("state_events.csv", "order_id", "production_orders.csv", "order_id", True),
            ("state_events.csv", "reason_code", "downtime_reasons.csv", "reason_code", True),
            ("production_counts.csv", "order_id", "production_orders.csv", "order_id", False),
            ("production_counts.csv", "machine_id", "machines.csv", "machine_id", False),
            ("production_counts.csv", "shift_id", "shifts.csv", "shift_id", False),
            ("production_counts.csv", "correction_ref_id", "production_counts.csv", "count_id", True),
            ("quality_inspections.csv", "order_id", "production_orders.csv", "order_id", False),
            ("quality_inspections.csv", "machine_id", "machines.csv", "machine_id", False),
            ("quality_inspections.csv", "shift_id", "shifts.csv", "shift_id", False),
            # Note: defect_code has its own enum domain and is no longer an FK to downtime_reasons
        ]

        for child_table, fk_col, parent_table, parent_pk, is_nullable in fk_definitions:
            if child_table not in dataset or parent_table not in dataset:
                continue

            child_df = dataset[child_table]
            child_pk_col = TABLE_PKS.get(child_table, "id")
            parent_set = pks.get(parent_table, set())

            if fk_col not in child_df.columns:
                continue

            for row in child_df.iter_rows(named=True):
                val = row.get(fk_col)
                rec_id = str(row.get(child_pk_col, "UNKNOWN"))

                # Handle nullable FKs
                if is_nullable and (val is None or str(val).strip() == ""):
                    continue

                if val is None or str(val) not in parent_set:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name=child_table,
                            record_id=rec_id,
                            field_name=fk_col,
                            message=f"Orphaned foreign key: '{val}' in {child_table}.{fk_col} does not exist in {parent_table}.{parent_pk}",
                            observed_value=val,
                            expected_condition=f"Must exist in {parent_table}.{parent_pk}",
                        )
                    )

        return findings


class EnumDomainRule(BaseValidationRule):
    """VAL-REL-003: Categorical fields must belong to authorized domain enums."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_REL_003

    @property
    def description(self) -> str:
        return "Validate that categorical enum attributes belong to valid domain enum values."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        enum_checks = [
            ("lines.csv", "line_type", {e.value for e in LineType}, False),
            ("machines.csv", "criticality", {e.value for e in MachineCriticality}, False),
            ("shifts.csv", "shift_code", {e.value for e in ShiftCode}, False),
            ("production_orders.csv", "status", {e.value for e in OrderStatus}, False),
            ("state_events.csv", "state", {e.value for e in MachineState}, False),
            ("downtime_reasons.csv", "category", {e.value for e in DowntimeCategory}, False),
            ("quality_inspections.csv", "inspection_type", {e.value for e in InspectionType}, False),
            ("quality_inspections.csv", "defect_code", {e.value for e in DefectCode}, True),
        ]

        for filename, col, allowed_values, is_nullable in enum_checks:
            if filename not in dataset:
                continue
            df = dataset[filename]
            if col not in df.columns:
                continue

            pk_col = TABLE_PKS.get(filename, "id")
            for row in df.iter_rows(named=True):
                raw_val = row.get(col)
                if is_nullable and (raw_val is None or str(raw_val).strip() == ""):
                    continue

                val = str(raw_val)
                rec_id = str(row.get(pk_col, "UNKNOWN"))
                if val not in allowed_values:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name=filename,
                            record_id=rec_id,
                            field_name=col,
                            message=f"Invalid enum value '{val}' in {filename}.{col}",
                            observed_value=val,
                            expected_condition=f"Allowed values: {sorted(list(allowed_values))}",
                        )
                    )

        return findings


class RequiredFieldsRule(BaseValidationRule):
    """VAL-REL-004: Mandatory entity attributes must not be null, empty, or whitespace."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_REL_004

    @property
    def description(self) -> str:
        return "Validate that all mandatory non-nullable columns across tables are populated."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        mandatory_fields: Dict[str, List[str]] = {
            "plants.csv": ["plant_id", "name", "timezone", "country"],
            "lines.csv": ["line_id", "plant_id", "name", "line_type"],
            "machines.csv": ["machine_id", "line_id", "name", "sequence_order", "criticality"],
            "products.csv": ["product_id", "sku", "name", "family"],
            "shifts.csv": ["shift_id", "plant_id", "shift_code", "start_time", "end_time", "planned_break_sec"],
            "machine_product_standards.csv": ["standard_id", "machine_id", "product_id", "ideal_cycle_time_sec"],
            "downtime_reasons.csv": ["reason_code", "category", "description", "affects_availability"],
            "production_orders.csv": ["order_id", "product_id", "line_id", "target_quantity", "scheduled_start", "scheduled_end", "status", "planned_cycle_time_sec"],
            "state_events.csv": ["event_id", "machine_id", "shift_id", "state", "start_time", "end_time", "duration_sec"],
            "production_counts.csv": ["count_id", "order_id", "machine_id", "shift_id", "timestamp", "count_delta", "cumulative_count", "is_correction"],
            "quality_inspections.csv": ["inspection_id", "order_id", "machine_id", "shift_id", "timestamp", "inspection_type", "inspected_qty", "passed_qty", "scrap_qty", "rework_qty"],
        }

        for filename, cols in mandatory_fields.items():
            if filename not in dataset:
                continue
            df = dataset[filename]
            pk_col = TABLE_PKS.get(filename, "id")

            for col in cols:
                if col not in df.columns:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name=filename,
                            record_id="SCHEMA",
                            field_name=col,
                            message=f"Mandatory column '{col}' is missing entirely from {filename}",
                            observed_value="Column missing",
                            expected_condition="Column must exist",
                        )
                    )
                    continue

                for row in df.iter_rows(named=True):
                    val = row.get(col)
                    rec_id = str(row.get(pk_col, "UNKNOWN"))
                    if val is None or (isinstance(val, str) and str(val).strip() == ""):
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name=filename,
                                record_id=rec_id,
                                field_name=col,
                                message=f"Mandatory field '{col}' is null or blank in {filename} (record {rec_id})",
                                observed_value="null/empty",
                                expected_condition="Must be non-null and non-empty",
                            )
                        )

        return findings


class DeDuplicationRule(BaseValidationRule):
    """VAL-DUP-001: Detect exact duplicate rows across all tables."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_DUP_001

    @property
    def description(self) -> str:
        return "Validate that there are zero exact duplicate rows across any entity table."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        for filename, df in dataset.items():
            if not filename.endswith(".csv") or filename == "ground_truth.csv":
                continue

            dupe_count = len(df) - df.unique().shape[0]
            if dupe_count > 0:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name=filename,
                        record_id="ALL",
                        field_name="row",
                        message=f"{dupe_count} exact duplicate rows detected in {filename}",
                        observed_value=f"Duplicates: {dupe_count}",
                        expected_condition="Zero duplicate rows",
                    )
                )

        return findings

