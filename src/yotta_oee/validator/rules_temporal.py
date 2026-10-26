"""Temporal integrity and timeline validation rules."""

from datetime import datetime
from typing import Dict, List
import polars as pl

from yotta_oee.domain.enums import MachineState, Severity, ValidationRuleId
from yotta_oee.validator.base import BaseValidationRule, RuleFinding


class TemporalMonotonicityRule(BaseValidationRule):
    """VAL-TIME-001: For every interval record, start_time must be <= end_time."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_TIME_001

    @property
    def description(self) -> str:
        return "Validate that chronological start_time <= end_time on all interval events."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        tables_to_check = [
            ("state_events.csv", "event_id", "start_time", "end_time"),
            ("shifts.csv", "shift_id", "start_time", "end_time"),
            ("production_orders.csv", "order_id", "scheduled_start", "scheduled_end"),
        ]

        for filename, pk_col, start_col, end_col in tables_to_check:
            if filename not in dataset:
                continue
            df = dataset[filename]
            if start_col not in df.columns or end_col not in df.columns:
                continue

            invalid = df.filter(pl.col(start_col) > pl.col(end_col))
            for row in invalid.iter_rows(named=True):
                rec_id = str(row.get(pk_col, "UNKNOWN"))
                s_val = str(row.get(start_col))
                e_val = str(row.get(end_col))
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name=filename,
                        record_id=rec_id,
                        field_name=start_col,
                        message=f"Negative duration: {start_col} ({s_val}) is after {end_col} ({e_val})",
                        observed_value=f"{s_val} > {e_val}",
                        expected_condition=f"{start_col} <= {end_col}",
                    )
                )

        return findings


class StateMutualExclusivityRule(BaseValidationRule):
    """VAL-TIME-002: Machine state events on the same machine must not overlap in time (EC-01)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_TIME_002

    @property
    def description(self) -> str:
        return "Validate that machine operational states are mutually exclusive with zero temporal overlaps."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "state_events.csv" not in dataset:
            return findings

        events_df = dataset["state_events.csv"].sort(["machine_id", "start_time", "event_id"])
        machines = events_df["machine_id"].unique().to_list()

        for machine in machines:
            m_events = events_df.filter(pl.col("machine_id") == machine).sort("start_time")
            records = m_events.iter_rows(named=True)
            prev_row = None

            for curr_row in records:
                if prev_row is not None:
                    # Check if current event begins before previous event concluded
                    # Compare as ISO strings or timestamps
                    prev_end = prev_row["end_time"]
                    curr_start = curr_row["start_time"]

                    if curr_start < prev_end:
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="state_events.csv",
                                record_id=curr_row["event_id"],
                                field_name="start_time",
                                message=(
                                    f"State event {curr_row['event_id']} ({curr_row['state']}) overlaps with "
                                    f"prior event {prev_row['event_id']} ({prev_row['state']}) on {machine}. "
                                    f"Starts at {curr_start} while prior ends at {prev_end}"
                                ),
                                observed_value=f"Start: {curr_start} < Prior End: {prev_end}",
                                expected_condition=f"start_time >= {prev_end}",
                                details={
                                    "machine_id": machine,
                                    "conflicting_event_id": prev_row["event_id"],
                                    "prior_end_time": prev_end,
                                    "curr_start_time": curr_start,
                                },
                            )
                        )

                prev_row = curr_row

        return findings


class BreakDowntimeOverlapRule(BaseValidationRule):
    """VAL-TIME-003: Unplanned downtime must not collide with or overlap planned shift breaks (EC-05)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_TIME_003

    @property
    def description(self) -> str:
        return "Validate that unplanned downtime stoppages do not collide with scheduled shift breaks."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "state_events.csv" not in dataset:
            return findings

        events_df = dataset["state_events.csv"]

        # Filter planned break events
        break_events = events_df.filter(
            (pl.col("state") == MachineState.PLANNED_DOWNTIME.value)
            & (pl.col("reason_code") == "DT-PLANNED-BREAK")
        ).iter_rows(named=True)

        # Index break intervals by (machine_id, shift_id)
        breaks_by_machine_shift: Dict[tuple, List[dict]] = {}
        for b in break_events:
            key = (b["machine_id"], b["shift_id"])
            breaks_by_machine_shift.setdefault(key, []).append(b)

        # Filter unplanned downtime events
        unplanned_events = events_df.filter(
            pl.col("state") == MachineState.UNPLANNED_DOWNTIME.value
        ).iter_rows(named=True)

        for unp in unplanned_events:
            key = (unp["machine_id"], unp["shift_id"])
            relevant_breaks = breaks_by_machine_shift.get(key, [])

            unp_start = unp["start_time"]
            unp_end = unp["end_time"]

            for brk in relevant_breaks:
                brk_start = brk["start_time"]
                brk_end = brk["end_time"]

                # Overlap condition between intervals [A, B] and [C, D]:
                # max(A, C) < min(B, D)
                if max(unp_start, brk_start) < min(unp_end, brk_end):
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="state_events.csv",
                            record_id=unp["event_id"],
                            field_name="start_time",
                            message=(
                                f"Unplanned downtime event {unp['event_id']} collides with scheduled break "
                                f"{brk['event_id']} on {unp['machine_id']}. Break interval [{brk_start}, {brk_end}] "
                                f"overlaps breakdown [{unp_start}, {unp_end}]."
                            ),
                            observed_value=f"Overlap in interval [{max(unp_start, brk_start)}, {min(unp_end, brk_end)}]",
                            expected_condition=f"Unplanned downtime must not overlap planned break {brk['event_id']}",
                            details={
                                "machine_id": unp["machine_id"],
                                "break_event_id": brk["event_id"],
                                "break_start": brk_start,
                                "break_end": brk_end,
                            },
                        )
                    )

        return findings
