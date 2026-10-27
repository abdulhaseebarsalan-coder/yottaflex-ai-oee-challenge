"""Shift-level OEE calculation and aggregation engine."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import polars as pl
from rich.console import Console
from rich.table import Table

from yotta_oee.domain.enums import AggregateStatus, MachineState, Severity
from yotta_oee.domain.models import OEEAggregate
from yotta_oee.domain.oee_math import (
    calculate_availability,
    calculate_oee,
    calculate_operating_time,
    calculate_performance,
    calculate_planned_production_time,
    calculate_quality,
    calculate_sampled_quality,
    calculate_weighted_ideal_cycle_time,
    verify_oee_equivalence,
)
from yotta_oee.validator.base import RuleFinding

console = Console(safe_box=True)


class OEECalculatorEngine:
    """Calculates Shift x Machine OEE metrics from raw telemetry source records."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.dataset = self._load_data()

    def _load_data(self) -> Dict[str, pl.DataFrame]:
        """Load required source files, strictly ignoring ground truth."""
        dfs = {}
        for csv_file in self.data_dir.glob("*.csv"):
            if "ground_truth" in csv_file.name.lower():
                continue
            dfs[csv_file.name] = pl.read_csv(csv_file)
        return dfs

    def calculate_all(
        self,
        output_csv: Optional[Path] = None,
        findings: Optional[List[RuleFinding]] = None,
    ) -> Tuple[List[OEEAggregate], Dict[str, Any]]:
        """Compute shift-level OEE metrics and analytical equivalence identities."""
        shifts_df = self.dataset["shifts.csv"]
        machines_df = self.dataset["machines.csv"]
        events_df = self.dataset["state_events.csv"]
        counts_df = self.dataset["production_counts.csv"]
        qc_df = self.dataset["quality_inspections.csv"]
        std_df = self.dataset["machine_product_standards.csv"]
        orders_df = self.dataset["production_orders.csv"]

        # Build standards lookup: (machine_id, product_id) -> ideal_cycle_time_sec
        std_lookup: Dict[Tuple[str, str], float] = {
            (row["machine_id"], row["product_id"]): float(row["ideal_cycle_time_sec"])
            for row in std_df.iter_rows(named=True)
        }
        # Build order lookup: order_id -> product_id
        order_product: Dict[str, str] = {
            row["order_id"]: row["product_id"] for row in orders_df.iter_rows(named=True)
        }
        # Machine to line lookup
        machine_line: Dict[str, str] = {
            row["machine_id"]: row["line_id"] for row in machines_df.iter_rows(named=True)
        }

        # Index validator findings by (machine_id, shift_id) and identify excluded records
        excluded_events: Set[str] = set()
        excluded_counts: Set[str] = set()
        excluded_qc: Set[str] = set()
        findings_by_ms: Dict[Tuple[str, str], List[RuleFinding]] = {}

        if findings:
            # Pre-index source tables for record-to-(machine, shift) routing
            evt_ms = {
                r["event_id"]: (r["machine_id"], r["shift_id"])
                for r in events_df.iter_rows(named=True)
            }
            cnt_ms = {
                r["count_id"]: (r["machine_id"], r["shift_id"])
                for r in counts_df.iter_rows(named=True)
            }
            qc_ms = {
                r["inspection_id"]: (r["machine_id"], r["shift_id"])
                for r in qc_df.iter_rows(named=True)
            }

            order_ms_map: Dict[str, Set[Tuple[str, str]]] = {}
            for r in counts_df.iter_rows(named=True):
                order_ms_map.setdefault(r["order_id"], set()).add((r["machine_id"], r["shift_id"]))

            for f in findings:
                # Documented Decision Policy: EXCLUDE invalid records identified by validation
                if f.rule_id.value in ("VAL-TIME-001", "VAL-REL-004") and f.table_name.startswith("state_events"):
                    excluded_events.add(f.record_id)
                elif f.rule_id.value == "VAL-COUNT-001" and f.table_name.startswith("production_counts"):
                    excluded_counts.add(f.record_id)
                elif f.rule_id.value == "VAL-QUAL-001" and f.table_name.startswith("quality_inspections"):
                    excluded_qc.add(f.record_id)

                # Route finding to machine-shift
                tbl = f.table_name.replace(".csv", "")
                if tbl == "state_events" and f.record_id in evt_ms:
                    findings_by_ms.setdefault(evt_ms[f.record_id], []).append(f)
                elif tbl == "production_counts" and f.record_id in cnt_ms:
                    findings_by_ms.setdefault(cnt_ms[f.record_id], []).append(f)
                elif tbl == "quality_inspections" and f.record_id in qc_ms:
                    findings_by_ms.setdefault(qc_ms[f.record_id], []).append(f)
                elif tbl == "production_orders" and f.record_id in order_ms_map:
                    for target_ms in order_ms_map[f.record_id]:
                        findings_by_ms.setdefault(target_ms, []).append(f)
                elif ":" in f.record_id:
                    parts = f.record_id.split(":")
                    if len(parts) == 2:
                        findings_by_ms.setdefault((parts[0], parts[1]), []).append(f)

        aggregates: List[OEEAggregate] = []
        equivalence_checks: List[Dict[str, Any]] = []
        total_inspected_units = 0
        total_production_units = 0
        qc_sample_sizes: List[int] = []

        # Iterate over all (Shift, Machine) pairs
        shift_rows = list(shifts_df.iter_rows(named=True))

        for shift in shift_rows:
            shift_id = shift["shift_id"]
            start_dt = datetime.fromisoformat(shift["start_time"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(shift["end_time"].replace("Z", "+00:00"))
            shift_duration_sec = int((end_dt - start_dt).total_seconds())

            for machine in machines_df.iter_rows(named=True):
                machine_id = machine["machine_id"]
                line_id = machine_line.get(machine_id, "LINE-01")
                ms_key = (machine_id, shift_id)

                # 1. State Event Durations (Decision EC-01 & EC-05)
                m_events = events_df.filter(
                    (pl.col("shift_id") == shift_id) & (pl.col("machine_id") == machine_id)
                )

                # Sort chronologically by start_time, prioritizing planned downtime when start times coincide
                m_ev_list = sorted(
                    list(m_events.iter_rows(named=True)),
                    key=lambda e: (e["start_time"], 0 if e["state"] == MachineState.PLANNED_DOWNTIME.value else 1),
                )

                # Identify scheduled breaks in this machine-shift
                break_intervals = [
                    (
                        datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00")),
                        datetime.fromisoformat(ev["end_time"].replace("Z", "+00:00")),
                    )
                    for ev in m_ev_list
                    if ev["state"] == MachineState.PLANNED_DOWNTIME.value
                ]

                running_sec = 0
                planned_dt_sec = 0
                unplanned_dt_sec = 0

                for i, ev in enumerate(m_ev_list):
                    if ev["event_id"] in excluded_events:
                        continue  # EXCLUDE decision applied

                    st = ev["state"]
                    s_dt = datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00"))
                    e_dt = datetime.fromisoformat(ev["end_time"].replace("Z", "+00:00"))

                    # Decision EC-01: Truncate the earlier event at next start if overlapping
                    # Applies when an earlier event (s_dt < next_s_dt) overlaps into the next event (e_dt > next_s_dt).
                    # Planned break events must not be truncated by overlapping breakdowns (handled via EC-05 clipping).
                    if i < len(m_ev_list) - 1:
                        next_ev = m_ev_list[i + 1]
                        next_s_dt = datetime.fromisoformat(next_ev["start_time"].replace("Z", "+00:00"))
                        if s_dt < next_s_dt and e_dt > next_s_dt:
                            if not (st == MachineState.PLANNED_DOWNTIME.value and next_ev["state"] == MachineState.UNPLANNED_DOWNTIME.value):
                                e_dt = next_s_dt

                    dur = max(0, int((e_dt - s_dt).total_seconds()))

                    # Decision EC-05: Clip breakdown at break boundary
                    if st == MachineState.UNPLANNED_DOWNTIME.value:
                        overlap_sec = 0
                        for b_s, b_e in break_intervals:
                            o_s = max(s_dt, b_s)
                            o_e = min(e_dt, b_e)
                            if o_e > o_s:
                                overlap_sec += int((o_e - o_s).total_seconds())
                        dur = max(0, dur - overlap_sec)

                    if st == MachineState.RUNNING.value:
                        running_sec += dur
                    elif st == MachineState.PLANNED_DOWNTIME.value:
                        planned_dt_sec += dur
                    elif st in (
                        MachineState.UNPLANNED_DOWNTIME.value,
                        MachineState.CHANGEOVER.value,
                        MachineState.STARVED.value,
                        MachineState.BLOCKED.value,
                    ):
                        unplanned_dt_sec += dur

                # DERIVE PPT directly from planned-break events in telemetry (not a constant)
                planned_prod_time_sec = max(0, shift_duration_sec - planned_dt_sec)
                operating_time_sec = int(calculate_operating_time(running_sec))

                # 2. Production Counts: total_count = sum of count_delta, never final cumulative (Decision EC-02)
                m_counts = counts_df.filter(
                    (pl.col("shift_id") == shift_id) & (pl.col("machine_id") == machine_id)
                )
                valid_counts = [
                    r for r in m_counts.iter_rows(named=True)
                    if r["count_id"] not in excluded_counts and (r["count_delta"] >= 0 or r["is_correction"])
                ]
                total_count = sum(int(r["count_delta"]) for r in valid_counts)
                if total_count < 0:
                    total_count = 0

                # 3. Quality Inspections: Exclude invalid inspection from Q and flag it (not Q=0) (Decision EC-03)
                m_qc = qc_df.filter(
                    (pl.col("shift_id") == shift_id) & (pl.col("machine_id") == machine_id)
                )
                valid_qc = [
                    r for r in m_qc.iter_rows(named=True)
                    if r["inspection_id"] not in excluded_qc
                    and r["scrap_qty"] <= r["inspected_qty"]
                    and (r["passed_qty"] + r["scrap_qty"] + r["rework_qty"] == r["inspected_qty"])
                ]

                sampled_inspected = sum(int(r["inspected_qty"]) for r in valid_qc)
                sampled_passed = sum(int(r["passed_qty"]) for r in valid_qc)
                sampled_scrap = sum(int(r["scrap_qty"]) for r in valid_qc)
                sampled_rework = sum(int(r["rework_qty"]) for r in valid_qc)

                # Quality: rework is salvaged within shift unless scrapped (Section 9.4)
                if sampled_inspected > 0:
                    conforming_sampled = max(0, sampled_inspected - sampled_scrap)
                    sample_yield = min(1.0, max(0.0, float(conforming_sampled) / float(sampled_inspected)))
                else:
                    sample_yield = 1.0

                # Define integer good_count scaled from sample yield
                good_count = int(round(total_count * sample_yield))
                good_count = max(0, min(total_count, good_count))
                scrap_count = max(0, total_count - good_count)
                rework_count = (
                    int(round(total_count * (float(sampled_rework) / float(sampled_inspected))))
                    if sampled_inspected > 0
                    else 0
                )

                # Track quality sampling metrics across all machine-shifts
                total_inspected_units += sampled_inspected
                total_production_units += total_count
                if sampled_inspected > 0:
                    qc_sample_sizes.append(sampled_inspected)

                # Use the EXACT same integer Good/Total in all calculations so identity holds
                qual = float(good_count) / float(total_count) if total_count > 0 else 1.0

                # 4. Standard Cycle Time Resolution: Always use master engineering standard ICT (Decision EC-04)
                active_orders = [r["order_id"] for r in valid_counts]
                if not active_orders:
                    active_orders = [
                        ev["order_id"] for ev in m_ev_list
                        if ev.get("order_id") and str(ev["order_id"]).strip() != ""
                    ]

                product_runs = []
                for ord_id in set(active_orders):
                    prd_id = order_product.get(ord_id)
                    if prd_id:
                        ord_counts = [r for r in valid_counts if r["order_id"] == ord_id]
                        ord_cnt = sum(int(r["count_delta"]) for r in ord_counts) if ord_counts else 1
                        master_ict = std_lookup.get((machine_id, prd_id), 10.0)
                        product_runs.append((max(1, ord_cnt), master_ict))

                if product_runs:
                    effective_ict = calculate_weighted_ideal_cycle_time(product_runs)
                else:
                    effective_ict = 10.0

                # 5. OEE Component Calculations
                # Availability clamped to [0.0, 1.0]
                avail = calculate_availability(operating_time_sec, planned_prod_time_sec, clamp=True)
                perf = calculate_performance(total_count, effective_ict, operating_time_sec)
                oee = calculate_oee(avail, perf, qual)

                # Documented Decision Policy 3: FLAG
                ms_findings = findings_by_ms.get(ms_key, [])
                exception_count = len(ms_findings)
                if exception_count == 0:
                    status = AggregateStatus.CLEAN
                elif any(f.severity == Severity.ERROR for f in ms_findings):
                    status = AggregateStatus.ANOMALOUS
                else:
                    status = AggregateStatus.FLAGGED

                # 6. Analytical Equivalence Check: Approved tolerance restored to 1e-6
                # |(A * P * Q) - ((GoodCount * ICT) / PPT)| <= 1e-6
                is_equiv, delta = verify_oee_equivalence(
                    availability=avail,
                    performance=perf,
                    quality=qual,
                    good_count=good_count,
                    ideal_cycle_time_sec=effective_ict,
                    planned_prod_time_sec=planned_prod_time_sec,
                    tolerance=1e-6,
                )
                equivalence_checks.append({
                    "shift_id": shift_id,
                    "machine_id": machine_id,
                    "is_equivalent": is_equiv,
                    "delta": delta,
                })

                agg_id = f"OEE-{shift_id}-{machine_id}"
                aggregates.append(
                    OEEAggregate(
                        aggregate_id=agg_id,
                        shift_id=shift_id,
                        machine_id=machine_id,
                        line_id=line_id,
                        planned_prod_time_sec=planned_prod_time_sec,
                        operating_time_sec=operating_time_sec,
                        unplanned_downtime_sec=unplanned_dt_sec,
                        planned_downtime_sec=planned_dt_sec,
                        total_count=total_count,
                        good_count=good_count,
                        scrap_count=scrap_count,
                        rework_count=rework_count,
                        ideal_cycle_time_sec=round(effective_ict, 3),
                        availability=round(avail, 4),
                        performance=round(perf, 4),
                        quality=round(qual, 4),
                        oee=round(oee, 4),
                        status=status,
                        exception_count=exception_count,
                    )
                )

        # Sort aggregates deterministically
        aggregates.sort(key=lambda a: (a.shift_id, a.machine_id))

        # Write to CSV if path specified
        if output_csv is not None:
            output_csv.parent.mkdir(parents=True, exist_ok=True)
            self._write_csv(output_csv, [a.to_dict() for a in aggregates])

        summary_meta = {
            "total_aggregates": len(aggregates),
            "total_shifts": len(shift_rows),
            "total_machines": len(machines_df),
            "equivalence_verification": {
                "total_verified": len(equivalence_checks),
                "passed_count": sum(1 for e in equivalence_checks if e["is_equivalent"]),
                "failed_count": sum(1 for e in equivalence_checks if not e["is_equivalent"]),
                "max_delta": max(e["delta"] for e in equivalence_checks) if equivalence_checks else 0.0,
            },
            "quality_sampling": {
                "total_inspections": len(qc_df),
                "total_inspected_units": total_inspected_units,
                "total_production_units": total_production_units,
                "sampling_coverage_pct": (
                    round((float(total_inspected_units) / float(total_production_units)) * 100.0, 2)
                    if total_production_units > 0
                    else 0.0
                ),
                "sample_size_stats": {
                    "total_samples": len(qc_sample_sizes),
                    "min_sample_units": min(qc_sample_sizes) if qc_sample_sizes else 0,
                    "max_sample_units": max(qc_sample_sizes) if qc_sample_sizes else 0,
                    "mean_sample_units": (
                        round(sum(qc_sample_sizes) / len(qc_sample_sizes), 1)
                        if qc_sample_sizes
                        else 0.0
                    ),
                },
                "rework_accounting": "Salvaged within shift and conforming (Good = Passed + Rework)",
                "sample_based_q_limits": (
                    "Lot-based inspection estimates population quality. Good count is integer-quantized "
                    "from sample yield (Good = round(Total * Yield)) so integer ratio Good/Total preserves "
                    "mass-energy equivalence A * P * Q == (Good * ICT) / PPT to 1e-6."
                ),
            },
        }

        return aggregates, summary_meta

    @staticmethod
    def _write_csv(filepath: Path, records: List[Dict[str, Any]]) -> None:
        """Write list of dictionaries to CSV deterministically."""
        if not records:
            filepath.write_text("", encoding="utf-8")
            return
        headers = list(records[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)
