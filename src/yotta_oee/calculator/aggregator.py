"""Shift-level OEE calculation and aggregation engine."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import polars as pl
from rich.console import Console
from rich.table import Table

from yotta_oee.domain.enums import MachineState
from yotta_oee.domain.models import OEEAggregate
from yotta_oee.domain.oee_math import (
    calculate_availability,
    calculate_oee,
    calculate_operating_time,
    calculate_performance,
    calculate_planned_production_time,
    calculate_quality,
    calculate_weighted_ideal_cycle_time,
    verify_oee_equivalence,
)

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
        self, output_csv: Optional[Path] = None
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

        aggregates: List[OEEAggregate] = []
        equivalence_checks: List[Dict[str, Any]] = []

        # Iterate over all (Shift, Machine) pairs
        shift_rows = list(shifts_df.iter_rows(named=True))

        for shift in shift_rows:
            shift_id = shift["shift_id"]
            # Shift planned break duration (default 3600s / 60 min)
            planned_break_sec = int(shift.get("planned_break_sec", 3600))

            # Calculate shift total planned production time: 28,800s - 3,600s = 25,200s
            # (or exact duration between start and end)
            start_dt = datetime.fromisoformat(shift["start_time"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(shift["end_time"].replace("Z", "+00:00"))
            shift_duration_sec = int((end_dt - start_dt).total_seconds())
            planned_prod_time_sec = int(calculate_planned_production_time(shift_duration_sec, planned_break_sec))

            for machine in machines_df.iter_rows(named=True):
                machine_id = machine["machine_id"]
                line_id = machine_line.get(machine_id, "LINE-01")

                # 1. State Event Durations
                m_events = events_df.filter(
                    (pl.col("shift_id") == shift_id) & (pl.col("machine_id") == machine_id)
                )

                running_sec = 0
                planned_dt_sec = 0
                unplanned_dt_sec = 0

                for ev in m_events.iter_rows(named=True):
                    dur = int(ev["duration_sec"])
                    st = ev["state"]
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

                operating_time_sec = int(calculate_operating_time(running_sec))

                # 2. Production Counts
                m_counts = counts_df.filter(
                    (pl.col("shift_id") == shift_id) & (pl.col("machine_id") == machine_id)
                )
                total_count = int(m_counts["count_delta"].sum()) if len(m_counts) > 0 else 0
                if total_count is None or total_count < 0:
                    total_count = 0

                # 3. Quality Inspections
                m_qc = qc_df.filter(
                    (pl.col("shift_id") == shift_id) & (pl.col("machine_id") == machine_id)
                )
                scrap_count = int(m_qc["scrap_qty"].sum()) if len(m_qc) > 0 else 0
                rework_count = int(m_qc["rework_qty"].sum()) if len(m_qc) > 0 else 0
                if scrap_count is None:
                    scrap_count = 0
                if rework_count is None:
                    rework_count = 0

                good_count = max(0, total_count - scrap_count)

                # 4. Standard Cycle Time Resolution
                # Find active orders on this machine in this shift
                active_orders = m_counts["order_id"].unique().to_list() if len(m_counts) > 0 else []
                if not active_orders:
                    # Look in events
                    active_orders = [
                        ev["order_id"] for ev in m_events.iter_rows(named=True)
                        if ev.get("order_id") and str(ev["order_id"]).strip() != ""
                    ]

                product_runs = []
                for ord_id in set(active_orders):
                    prd_id = order_product.get(ord_id)
                    if prd_id:
                        ord_counts = m_counts.filter(pl.col("order_id") == ord_id)
                        ord_cnt = int(ord_counts["count_delta"].sum()) if len(ord_counts) > 0 else 1
                        ict = std_lookup.get((machine_id, prd_id), 10.0)
                        product_runs.append((max(1, ord_cnt), ict))

                if product_runs:
                    effective_ict = calculate_weighted_ideal_cycle_time(product_runs)
                else:
                    # Default fallback cycle time for machine
                    effective_ict = 10.0

                # 5. OEE Component Calculations
                avail = calculate_availability(operating_time_sec, planned_prod_time_sec, clamp=False)
                perf = calculate_performance(total_count, effective_ict, operating_time_sec)
                qual = calculate_quality(total_count, scrap_count, clamp=True)
                oee = calculate_oee(avail, perf, qual)

                # 6. Analytical Equivalence Check
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
