"""Business logic, telemetry, quality, and performance validation rules."""

from typing import Dict, List, Set, Tuple
import polars as pl

from yotta_oee.domain.enums import MachineState, OrderStatus, Severity, ValidationRuleId
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
        orders_machines = sorted(counts_df.select(["order_id", "machine_id"]).unique().rows())

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
    """VAL-PERF-001: Order planned cycle time must match the authoritative master engineering standard (EC-04)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_PERF_001

    @property
    def description(self) -> str:
        return "Validate that production orders have planned cycle times matching the master engineering standards."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "production_orders.csv" not in dataset or "machine_product_standards.csv" not in dataset:
            return findings

        orders_df = dataset["production_orders.csv"]
        std_df = dataset["machine_product_standards.csv"]

        # Build master standard lookup: (machine_id, product_id) -> ideal_cycle_time_sec
        std_lookup: Dict[Tuple[str, str], float] = {
            (row["machine_id"], row["product_id"]): float(row["ideal_cycle_time_sec"])
            for row in std_df.iter_rows(named=True)
        }

        # Check each order's planned_cycle_time_sec against master standard
        for order in orders_df.iter_rows(named=True):
            o_id = order["order_id"]
            p_id = order["product_id"]
            l_id = order["line_id"]
            planned_ict = float(order.get("planned_cycle_time_sec", 0.0))

            # Primary lead machine on line is MCH-{line_id}-01
            lead_machine = f"MCH-{l_id}-01"
            master_ict = std_lookup.get((lead_machine, p_id))

            if master_ict is None:
                matching_standards = [v for k, v in std_lookup.items() if k[1] == p_id]
                master_ict = matching_standards[0] if matching_standards else None

            if master_ict is not None:
                discrepancy = abs(planned_ict - master_ict)
                if discrepancy > 0.001:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="production_orders.csv",
                            record_id=o_id,
                            field_name="planned_cycle_time_sec",
                            message=(
                                f"Cycle time discrepancy on order {o_id}: planned_cycle_time_sec ({planned_ict:.3f}s) "
                                f"does not match master standard ({master_ict:.3f}s) for product {p_id} on {lead_machine}"
                            ),
                            observed_value=f"{planned_ict:.3f}s",
                            expected_condition=f"Must match master standard {master_ict:.3f}s",
                            details={
                                "order_id": o_id,
                                "product_id": p_id,
                                "line_id": l_id,
                                "lead_machine": lead_machine,
                                "planned_cycle_time_sec": planned_ict,
                                "master_standard_sec": master_ict,
                                "delta_sec": round(planned_ict - master_ict, 3),
                            },
                        )
                    )

        return findings


class CorrectionReferenceValidityRule(BaseValidationRule):
    """VAL-COUNT-003: When is_correction=True, correction_ref_id must reference a valid prior count."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_COUNT_003

    @property
    def description(self) -> str:
        return "Validate that correction count records cite a valid, pre-existing count for the same order and machine."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []
        if "production_counts.csv" not in dataset:
            return findings

        counts_df = dataset["production_counts.csv"]
        counts_by_id = {row["count_id"]: row for row in counts_df.iter_rows(named=True)}

        for row in counts_df.iter_rows(named=True):
            is_corr = row["is_correction"]
            corr_ref = row["correction_ref_id"]
            cnt_id = row["count_id"]
            o_id = row["order_id"]
            m_id = row["machine_id"]
            ts = row["timestamp"]

            if is_corr:
                if not corr_ref or str(corr_ref).strip() == "":
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="production_counts.csv",
                            record_id=cnt_id,
                            field_name="correction_ref_id",
                            message=f"Correction count {cnt_id} has is_correction=True but missing correction_ref_id",
                            observed_value="empty/null",
                            expected_condition="Must reference prior count_id being adjusted",
                        )
                    )
                elif corr_ref not in counts_by_id:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="production_counts.csv",
                            record_id=cnt_id,
                            field_name="correction_ref_id",
                            message=f"Correction count {cnt_id} references nonexistent count_id '{corr_ref}'",
                            observed_value=str(corr_ref),
                            expected_condition="Must exist in production_counts.csv",
                        )
                    )
                else:
                    ref_row = counts_by_id[corr_ref]
                    if ref_row["order_id"] != o_id or ref_row["machine_id"] != m_id:
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_counts.csv",
                                record_id=cnt_id,
                                field_name="correction_ref_id",
                                message=(
                                    f"Correction count {cnt_id} references count {corr_ref} from different "
                                    f"order/machine ({ref_row['order_id']}/{ref_row['machine_id']} vs {o_id}/{m_id})"
                                ),
                                observed_value=f"{ref_row['order_id']}/{ref_row['machine_id']}",
                                expected_condition=f"Same order ({o_id}) and machine ({m_id})",
                            )
                        )
                    elif ref_row["timestamp"] >= ts:
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_counts.csv",
                                record_id=cnt_id,
                                field_name="timestamp",
                                message=(
                                    f"Correction count {cnt_id} at {ts} must not be earlier than or equal to "
                                    f"referenced count {corr_ref} at {ref_row['timestamp']}"
                                ),
                                observed_value=f"correction: {ts} <= referenced: {ref_row['timestamp']}",
                                expected_condition="Correction timestamp must succeed referenced timestamp",
                            )
                        )
            else:
                if corr_ref and str(corr_ref).strip() != "":
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="production_counts.csv",
                            record_id=cnt_id,
                            field_name="correction_ref_id",
                            message=(
                                f"Non-correction count {cnt_id} (is_correction=False) should not have "
                                f"correction_ref_id '{corr_ref}'"
                            ),
                            observed_value=str(corr_ref),
                            expected_condition="correction_ref_id must be empty when is_correction=False",
                        )
                    )

        return findings


class StateTransitionLifecycleRule(BaseValidationRule):
    """VAL-STATE-001: Machine state transitions must adhere to authorized physical lifecycle paths."""

    ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
        MachineState.RUNNING.value: {
            MachineState.UNPLANNED_DOWNTIME.value,
            MachineState.PLANNED_DOWNTIME.value,
            MachineState.CHANGEOVER.value,
            MachineState.STARVED.value,
            MachineState.BLOCKED.value,
            MachineState.OFF.value,
        },
        MachineState.UNPLANNED_DOWNTIME.value: {
            MachineState.RUNNING.value,
            MachineState.CHANGEOVER.value,
            MachineState.OFF.value,
        },
        MachineState.PLANNED_DOWNTIME.value: {
            MachineState.RUNNING.value,
            MachineState.CHANGEOVER.value,
            MachineState.OFF.value,
        },
        MachineState.CHANGEOVER.value: {
            MachineState.RUNNING.value,
            MachineState.UNPLANNED_DOWNTIME.value,
            MachineState.PLANNED_DOWNTIME.value,
            MachineState.OFF.value,
        },
        MachineState.STARVED.value: {
            MachineState.RUNNING.value,
            MachineState.CHANGEOVER.value,
            MachineState.PLANNED_DOWNTIME.value,
            MachineState.OFF.value,
        },
        MachineState.BLOCKED.value: {
            MachineState.RUNNING.value,
            MachineState.CHANGEOVER.value,
            MachineState.PLANNED_DOWNTIME.value,
            MachineState.OFF.value,
        },
        MachineState.OFF.value: {
            MachineState.CHANGEOVER.value,
            MachineState.PLANNED_DOWNTIME.value,
            MachineState.RUNNING.value,
        },
    }

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_STATE_001

    @property
    def description(self) -> str:
        return "Validate that continuous machine state changes follow valid industrial state-transition lifecycle rules."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "state_events.csv" not in dataset:
            return findings

        events_df = dataset["state_events.csv"].sort(["machine_id", "start_time", "event_id"])
        machines = sorted(events_df["machine_id"].unique().to_list())

        for machine in machines:
            m_events = events_df.filter(pl.col("machine_id") == machine).sort("start_time")
            records = m_events.iter_rows(named=True)
            prev_row = None

            for curr_row in records:
                if prev_row is not None:
                    prev_st = prev_row["state"]
                    curr_st = curr_row["state"]
                    rec_id = curr_row["event_id"]

                    if prev_st != curr_st:
                        allowed = self.ALLOWED_TRANSITIONS.get(prev_st, set())
                        if curr_st not in allowed:
                            findings.append(
                                RuleFinding(
                                    rule_id=self.rule_id,
                                    severity=Severity.ERROR,
                                    table_name="state_events.csv",
                                    record_id=rec_id,
                                    field_name="state",
                                    message=(
                                        f"Illegal state transition lifecycle on {machine}: cannot transition directly "
                                        f"from {prev_st} to {curr_st} (events {prev_row['event_id']} -> {rec_id})"
                                    ),
                                    observed_value=f"{prev_st} -> {curr_st}",
                                    expected_condition=f"Allowed from {prev_st}: {sorted(list(allowed))}",
                                )
                            )

                prev_row = curr_row

        return findings


class PerformancePlausibilityRule(BaseValidationRule):
    """VAL-PERF-002: Performance ratio exceeding 1.20 (120%) indicates uncalibrated speed or overcounting."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_PERF_002

    @property
    def description(self) -> str:
        return "Validate that observed performance ratio does not exceed plausible physical limits (P <= 1.20)."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "state_events.csv" not in dataset or "production_counts.csv" not in dataset:
            return findings

        events_df = dataset["state_events.csv"]
        counts_df = dataset["production_counts.csv"]
        orders_df = dataset.get("production_orders.csv")
        std_df = dataset.get("machine_product_standards.csv")

        # Map order_id -> product_id and planned_cycle_time_sec
        order_prod: Dict[str, str] = {}
        order_ict: Dict[str, float] = {}
        if orders_df is not None:
            for o in orders_df.iter_rows(named=True):
                order_prod[o["order_id"]] = o.get("product_id", "")
                order_ict[o["order_id"]] = float(o.get("planned_cycle_time_sec", 10.0))

        # Map (machine_id, product_id) -> ideal_cycle_time_sec
        std_lookup: Dict[Tuple[str, str], float] = {}
        if std_df is not None:
            for s in std_df.iter_rows(named=True):
                std_lookup[(s["machine_id"], s["product_id"])] = float(s["ideal_cycle_time_sec"])

        # Operating time per (machine_id, shift_id)
        running_events = events_df.filter(pl.col("state") == MachineState.RUNNING.value)
        ot_by_ms = (
            running_events.group_by(["machine_id", "shift_id"])
            .agg(pl.col("duration_sec").sum().alias("operating_sec"))
        )
        ot_map = {
            (r["machine_id"], r["shift_id"]): int(r["operating_sec"])
            for r in ot_by_ms.iter_rows(named=True)
        }

        # Counts and weighted cycle time per (machine_id, shift_id)
        counts_by_ms = (
            counts_df.group_by(["machine_id", "shift_id", "order_id"])
            .agg(pl.col("count_delta").sum().alias("order_counts"))
        )

        # Aggregate across orders per (machine_id, shift_id)
        ms_production: Dict[Tuple[str, str], float] = {}
        for row in counts_by_ms.iter_rows(named=True):
            m_id = row["machine_id"]
            s_id = row["shift_id"]
            o_id = row["order_id"]
            cnt = max(0, int(row["order_counts"]))

            p_id = order_prod.get(o_id, "")
            ict = std_lookup.get((m_id, p_id), order_ict.get(o_id, 10.0))
            ms_production[(m_id, s_id)] = ms_production.get((m_id, s_id), 0.0) + (cnt * ict)

        for (m_id, s_id), net_prod_time in ms_production.items():
            ot_sec = ot_map.get((m_id, s_id), 0)
            if ot_sec > 0:
                p_ratio = net_prod_time / float(ot_sec)
                if p_ratio > 1.20:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.WARNING,
                            table_name="production_counts.csv",
                            record_id=f"{m_id}:{s_id}",
                            field_name="performance",
                            message=(
                                f"Performance plausibility warning: machine {m_id} in {s_id} calculated "
                                f"P = {p_ratio:.1%} (> 120%), suggesting potential count inflation or takt time mismatch"
                            ),
                            observed_value=f"{p_ratio:.3f}",
                            expected_condition="Performance ratio P <= 1.20",
                            details={
                                "machine_id": m_id,
                                "shift_id": s_id,
                                "performance_ratio": round(p_ratio, 4),
                                "operating_time_sec": ot_sec,
                                "net_production_time_sec": round(net_prod_time, 2),
                            },
                        )
                    )

        return findings


class OrderLifecycleRule(BaseValidationRule):
    """VAL-ORD-001: Validate order lifecycle consistency.

    1. CANCELLED orders must have zero production counts and zero quality inspections.
    2. IN_PROGRESS orders must not precede any COMPLETED order on the same machine/line.
    """

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_ORD_001

    @property
    def description(self) -> str:
        return "Validate that CANCELLED orders have zero counts/inspections and IN_PROGRESS orders do not precede COMPLETED orders."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        if "production_orders.csv" not in dataset:
            return findings

        orders_df = dataset["production_orders.csv"]
        counts_df = dataset.get("production_counts.csv")
        qc_df = dataset.get("quality_inspections.csv")

        # 1. CANCELLED orders check
        cancelled_orders = orders_df.filter(pl.col("status") == OrderStatus.CANCELLED.value)
        if len(cancelled_orders) > 0:
            cancelled_ids = set(cancelled_orders["order_id"].to_list())

            # Check counts
            if counts_df is not None:
                canc_counts = counts_df.filter(pl.col("order_id").is_in(list(cancelled_ids)))
                if len(canc_counts) > 0:
                    counts_by_ord = canc_counts.group_by("order_id").len()
                    for row in counts_by_ord.iter_rows(named=True):
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_orders.csv",
                                record_id=row["order_id"],
                                field_name="status",
                                message=(
                                    f"Cancelled order {row['order_id']} has {row['len']} "
                                    f"production count records; CANCELLED orders must have zero production counts."
                                ),
                                observed_value=str(row["len"]),
                                expected_condition="0 production counts",
                            )
                        )

            # Check quality inspections
            if qc_df is not None:
                canc_qc = qc_df.filter(pl.col("order_id").is_in(list(cancelled_ids)))
                if len(canc_qc) > 0:
                    qc_by_ord = canc_qc.group_by("order_id").len()
                    for row in qc_by_ord.iter_rows(named=True):
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_orders.csv",
                                record_id=row["order_id"],
                                field_name="status",
                                message=(
                                    f"Cancelled order {row['order_id']} has {row['len']} "
                                    f"quality inspection records; CANCELLED orders must have zero quality inspections."
                                ),
                                observed_value=str(row["len"]),
                                expected_condition="0 quality inspections",
                            )
                        )

        # 2. IN_PROGRESS orders check: must not be earlier than last COMPLETED order on the same machine/line
        in_prog_orders = orders_df.filter(pl.col("status") == OrderStatus.IN_PROGRESS.value)
        completed_orders = orders_df.filter(pl.col("status") == OrderStatus.COMPLETED.value)

        if len(in_prog_orders) > 0 and len(completed_orders) > 0:
            for ip in in_prog_orders.iter_rows(named=True):
                line_completed = completed_orders.filter(pl.col("line_id") == ip["line_id"])
                if len(line_completed) > 0:
                    latest_completed_start = line_completed["scheduled_start"].max()
                    if ip["scheduled_start"] < latest_completed_start:
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_orders.csv",
                                record_id=ip["order_id"],
                                field_name="scheduled_start",
                                message=(
                                    f"In-progress order {ip['order_id']} scheduled_start ({ip['scheduled_start']}) "
                                    f"is earlier than completed order start ({latest_completed_start}) on line {ip['line_id']}."
                                ),
                                observed_value=str(ip["scheduled_start"]),
                                expected_condition=f">= {latest_completed_start}",
                            )
                        )

        return findings


