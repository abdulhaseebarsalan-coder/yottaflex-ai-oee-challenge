"""Business logic, telemetry, quality, and performance validation rules."""

from typing import Dict, List, Set, Tuple
import polars as pl

from yotta_oee.domain.enums import MachineState, Severity, ValidationRuleId
from yotta_oee.validator.base import BaseValidationRule, RuleFinding


class CountProgressionRule(BaseValidationRule):
    """VAL-COUNT-001: Cumulative count must not decrease without an explicit correction event (EC-02)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_COUNT_001

    @property
    def description(self) -> str:
        return "Validate that cumulative production counts never decrease unless flagged as an authorized correction."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "production_counts.csv" not in dataset:
            return findings

        counts_df = dataset["production_counts.csv"].sort(["order_id", "machine_id", "timestamp"])
        orders_machines = counts_df.select(["order_id", "machine_id"]).unique().rows()

        for o_id, m_id in orders_machines:
            om_counts = counts_df.filter(
                (pl.col("order_id") == o_id) & (pl.col("machine_id") == m_id)
            ).sort("timestamp")

            records = om_counts.iter_rows(named=True)
            prev_row = None

            for curr_row in records:
                if prev_row is not None:
                    prev_cum = prev_row["cumulative_count"]
                    curr_cum = curr_row["cumulative_count"]
                    delta = curr_row["count_delta"]
                    is_corr = curr_row["is_correction"]
                    corr_ref = curr_row["correction_ref_id"]

                    # Check for downward count progression without correction flag
                    if curr_cum < prev_cum or delta < 0:
                        if not is_corr:
                            findings.append(
                                RuleFinding(
                                    rule_id=self.rule_id,
                                    severity=Severity.ERROR,
                                    table_name="production_counts.csv",
                                    record_id=curr_row["count_id"],
                                    field_name="cumulative_count",
                                    message=(
                                        f"Unexplained count decrease: Cumulative count dropped from {prev_cum} to "
                                        f"{curr_cum} (delta: {delta}) on order {o_id}, machine {m_id} without "
                                        f"is_correction=True"
                                    ),
                                    observed_value=f"cumulative_count: {curr_cum}, delta: {delta}, is_correction: {is_corr}",
                                    expected_condition="Decreasing count must have is_correction=True and valid correction_ref_id",
                                    details={
                                        "order_id": o_id,
                                        "machine_id": m_id,
                                        "prior_count_id": prev_row["count_id"],
                                        "prior_cumulative": prev_cum,
                                        "curr_cumulative": curr_cum,
                                    },
                                )
                            )
                        elif not corr_ref or str(corr_ref).strip() == "":
                            findings.append(
                                RuleFinding(
                                    rule_id=self.rule_id,
                                    severity=Severity.ERROR,
                                    table_name="production_counts.csv",
                                    record_id=curr_row["count_id"],
                                    field_name="correction_ref_id",
                                    message=(
                                        f"Correction record {curr_row['count_id']} lacks mandatory correction_ref_id"
                                    ),
                                    observed_value="correction_ref_id is empty/null",
                                    expected_condition="Must reference original count_id being adjusted",
                                )
                            )

                prev_row = curr_row

        return findings


class RunningStateAuthorizationRule(BaseValidationRule):
    """VAL-COUNT-002: Pulse counts must only be registered while equipment is in RUNNING state."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_COUNT_002

    @property
    def description(self) -> str:
        return "Validate that production counts are only recorded during authorized RUNNING machine intervals."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "production_counts.csv" not in dataset or "state_events.csv" not in dataset:
            return findings

        events_df = dataset["state_events.csv"]
        counts_df = dataset["production_counts.csv"]

        # Filter running events
        running_events = events_df.filter(pl.col("state") == MachineState.RUNNING.value)

        # For performance, index running intervals by machine_id
        running_intervals: Dict[str, List[Tuple[str, str]]] = {}
        for row in running_events.iter_rows(named=True):
            running_intervals.setdefault(row["machine_id"], []).append(
                (row["start_time"], row["end_time"])
            )

        for row in counts_df.iter_rows(named=True):
            m_id = row["machine_id"]
            ts = row["timestamp"]
            intervals = running_intervals.get(m_id, [])

            # Check if timestamp falls within any running interval
            is_authorized = any(start <= ts <= end for start, end in intervals)

            if not is_authorized:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="production_counts.csv",
                        record_id=row["count_id"],
                        field_name="timestamp",
                        message=f"Count {row['count_id']} at {ts} emitted while machine {m_id} was NOT in RUNNING state",
                        observed_value=ts,
                        expected_condition="Must occur within a RUNNING machine state interval",
                    )
                )

        return findings


class QualityMassBalanceRule(BaseValidationRule):
    """VAL-QUAL-001: Quality sample mass-balance and scrap <= inspected quantity (EC-03)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_QUAL_001

    @property
    def description(self) -> str:
        return "Validate that inspected_qty = passed_qty + scrap_qty + rework_qty and scrap_qty <= inspected_qty."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "quality_inspections.csv" not in dataset:
            return findings

        qc_df = dataset["quality_inspections.csv"]

        for row in qc_df.iter_rows(named=True):
            inspected = row["inspected_qty"]
            passed = row["passed_qty"]
            scrap = row["scrap_qty"]
            rework = row["rework_qty"]
            rec_id = row["inspection_id"]

            # Mass balance check
            if passed + scrap + rework != inspected:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="quality_inspections.csv",
                        record_id=rec_id,
                        field_name="inspected_qty",
                        message=(
                            f"Mass balance violation in inspection {rec_id}: inspected_qty ({inspected}) != "
                            f"passed ({passed}) + scrap ({scrap}) + rework ({rework})"
                        ),
                        observed_value=f"Sum: {passed + scrap + rework} != {inspected}",
                        expected_condition="passed_qty + scrap_qty + rework_qty == inspected_qty",
                    )
                )

            # Scrap overflow check (EC-03)
            if scrap > inspected:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="quality_inspections.csv",
                        record_id=rec_id,
                        field_name="scrap_qty",
                        message=(
                            f"Scrap exceeds total inspected: scrap_qty ({scrap}) > inspected_qty ({inspected}) "
                            f"in inspection {rec_id}"
                        ),
                        observed_value=f"scrap_qty: {scrap} > inspected_qty: {inspected}",
                        expected_condition="scrap_qty <= inspected_qty",
                    )
                )

        return findings


class CycleTimeAdherenceRule(BaseValidationRule):
    """VAL-PERF-001: Ideal cycle times must adhere to realistic engineering limits (EC-04)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_PERF_001

    @property
    def description(self) -> str:
        return "Validate that machine product standard ideal cycle times adhere to realistic physical limits (>= 1.0s)."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "machine_product_standards.csv" not in dataset:
            return findings

        std_df = dataset["machine_product_standards.csv"]

        for row in std_df.iter_rows(named=True):
            ict = float(row["ideal_cycle_time_sec"])
            rec_id = row["standard_id"]

            # Realistic discrete industrial takt time limits: 1.0s to 120.0s
            # EC-04 injects 0.35s
            if ict < 1.0 or ict > 120.0:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="machine_product_standards.csv",
                        record_id=rec_id,
                        field_name="ideal_cycle_time_sec",
                        message=(
                            f"Invalid standard ideal cycle time {ict}s in {rec_id}. "
                            f"Value violates engineering threshold (1.0s to 120.0s)"
                        ),
                        observed_value=f"{ict}s",
                        expected_condition="1.0s <= ideal_cycle_time_sec <= 120.0s",
                    )
                )

        return findings
