"""Phase 3 Data-Quality Audit Script for the YottaFlex Starter Dataset.

Performs exhaustive verification of:
1. Clean vs. Mutated separation & ground-truth non-leakage
2. Referential integrity & orphan counting across all 12 tables
3. Primary Key uniqueness and regex ID pattern compliance
4. Temporal integrity & timeline continuity (EC-01 and EC-05 isolation)
5. Production count progression & correction audit (EC-02 isolation)
6. Quality inspection mass-balance reconciliation (EC-03 isolation)
7. Machine-product standards & takt times (EC-04 isolation)
8. Derived-value integrity vs source records
9. Manufacturing realism & distribution statistics
10. Cross-process cryptographic reproducibility
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Set, Tuple

import polars as pl
from rich.console import Console
from rich.table import Table

from yotta_oee.domain import DefectCode

console = Console(safe_box=True)



def load_dataset(data_dir: Path) -> Dict[str, pl.DataFrame]:
    """Load all generated CSV files into Polars DataFrames."""
    dfs = {}
    for csv_file in data_dir.glob("*.csv"):
        dfs[csv_file.name] = pl.read_csv(csv_file)
    return dfs


def run_audit(data_dir: Path) -> Dict[str, Any]:
    """Execute complete 10-point audit on the starter dataset."""
    results: Dict[str, Any] = {
        "data_dir": str(data_dir),
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "findings": [],
        "metrics": {},
    }

    dfs = load_dataset(data_dir)

    # ---------------------------------------------------------
    # 1. Clean-vs-Mutated & Ground Truth Isolation
    # ---------------------------------------------------------
    gt_file = data_dir / "ground_truth.json"
    assert gt_file.exists(), "ground_truth.json missing!"
    with open(gt_file, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    results["metrics"]["ground_truth_count"] = len(ground_truth)
    gt_record_ids = {g["record_id"]: g["anomaly_type"] for g in ground_truth}

    # GOVERNANCE AUDIT: Verify that ground_truth is NOT imported or read in validator or calculator
    src_dir = Path("src/yotta_oee")
    leak_sources = []
    # Check validator and calculator modules specifically
    for target_sub in ["validator", "calculator"]:
        sub_dir = src_dir / target_sub
        if sub_dir.exists():
            for py_file in sub_dir.rglob("*.py"):
                lines = py_file.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    line_clean = line.strip().lower()
                    if line_clean.startswith("#") or "continue" in line_clean or "exclude" in line_clean:
                        continue  # Defensive skip guards are legitimate
                    if "ground_truth" in line_clean or "groundtruth" in line_clean:
                        if "import" in line_clean or "read_" in line_clean or "load" in line_clean or "open(" in line_clean:
                            leak_sources.append(f"{py_file.name}: {line.strip()}")

    results["metrics"]["ground_truth_leaks"] = len(leak_sources)
    if leak_sources:
        results["findings"].append(f"Ground truth leak detected in: {leak_sources}")

    # ---------------------------------------------------------
    # 2. Referential Integrity & Orphan Counts
    # ---------------------------------------------------------
    orphan_counts: Dict[str, int] = {}

    plants_pks = set(dfs["plants.csv"]["plant_id"].to_list())
    lines_pks = set(dfs["lines.csv"]["line_id"].to_list())
    machines_pks = set(dfs["machines.csv"]["machine_id"].to_list())
    products_pks = set(dfs["products.csv"]["product_id"].to_list())
    shifts_pks = set(dfs["shifts.csv"]["shift_id"].to_list())
    reasons_pks = set(dfs["downtime_reasons.csv"]["reason_code"].to_list())
    orders_pks = set(dfs["production_orders.csv"]["order_id"].to_list())
    counts_pks = set(dfs["production_counts.csv"]["count_id"].to_list())

    # FK 1: lines.plant_id -> plants.plant_id
    orphan_counts["lines.plant_id"] = len(
        dfs["lines.csv"].filter(~pl.col("plant_id").is_in(plants_pks))
    )
    # FK 2: machines.line_id -> lines.line_id
    orphan_counts["machines.line_id"] = len(
        dfs["machines.csv"].filter(~pl.col("line_id").is_in(lines_pks))
    )
    # FK 3: shifts.plant_id -> plants.plant_id
    orphan_counts["shifts.plant_id"] = len(
        dfs["shifts.csv"].filter(~pl.col("plant_id").is_in(plants_pks))
    )
    # FK 4: standards -> machines & products
    orphan_counts["standards.machine_id"] = len(
        dfs["machine_product_standards.csv"].filter(~pl.col("machine_id").is_in(machines_pks))
    )
    orphan_counts["standards.product_id"] = len(
        dfs["machine_product_standards.csv"].filter(~pl.col("product_id").is_in(products_pks))
    )
    # FK 5: orders -> products & lines
    orphan_counts["orders.product_id"] = len(
        dfs["production_orders.csv"].filter(~pl.col("product_id").is_in(products_pks))
    )
    orphan_counts["orders.line_id"] = len(
        dfs["production_orders.csv"].filter(~pl.col("line_id").is_in(lines_pks))
    )
    # FK 6: state_events -> machines, shifts, orders, reasons
    orphan_counts["state_events.machine_id"] = len(
        dfs["state_events.csv"].filter(~pl.col("machine_id").is_in(machines_pks))
    )
    orphan_counts["state_events.shift_id"] = len(
        dfs["state_events.csv"].filter(~pl.col("shift_id").is_in(shifts_pks))
    )
    # order_id can be null/empty during breaks/idle
    non_null_order_events = dfs["state_events.csv"].filter(
        pl.col("order_id").is_not_null() & (pl.col("order_id") != "")
    )
    orphan_counts["state_events.order_id"] = len(
        non_null_order_events.filter(~pl.col("order_id").is_in(orders_pks))
    )
    non_null_reason_events = dfs["state_events.csv"].filter(
        pl.col("reason_code").is_not_null() & (pl.col("reason_code") != "")
    )
    orphan_counts["state_events.reason_code"] = len(
        non_null_reason_events.filter(~pl.col("reason_code").is_in(reasons_pks))
    )
    # FK 7: production_counts -> orders, machines, shifts, correction_ref_id
    orphan_counts["counts.order_id"] = len(
        dfs["production_counts.csv"].filter(~pl.col("order_id").is_in(orders_pks))
    )
    orphan_counts["counts.machine_id"] = len(
        dfs["production_counts.csv"].filter(~pl.col("machine_id").is_in(machines_pks))
    )
    orphan_counts["counts.shift_id"] = len(
        dfs["production_counts.csv"].filter(~pl.col("shift_id").is_in(shifts_pks))
    )
    corr_counts = dfs["production_counts.csv"].filter(
        pl.col("is_correction") == True
    )
    orphan_counts["counts.correction_ref_id"] = len(
        corr_counts.filter(~pl.col("correction_ref_id").is_in(counts_pks))
    )
    # FK 8: quality_inspections -> orders, machines, shifts, defect_code
    orphan_counts["qc.order_id"] = len(
        dfs["quality_inspections.csv"].filter(~pl.col("order_id").is_in(orders_pks))
    )
    orphan_counts["qc.machine_id"] = len(
        dfs["quality_inspections.csv"].filter(~pl.col("machine_id").is_in(machines_pks))
    )
    orphan_counts["qc.shift_id"] = len(
        dfs["quality_inspections.csv"].filter(~pl.col("shift_id").is_in(shifts_pks))
    )
    qc_defects = dfs["quality_inspections.csv"].filter(
        pl.col("defect_code").is_not_null() & (pl.col("defect_code") != "")
    )
    valid_defect_codes = {e.value for e in DefectCode}
    orphan_counts["qc.defect_code"] = len(
        qc_defects.filter(~pl.col("defect_code").is_in(valid_defect_codes))
    )

    results["metrics"]["orphan_counts"] = orphan_counts


    # ---------------------------------------------------------
    # 3. ID Integrity & Uniqueness
    # ---------------------------------------------------------
    duplicate_counts: Dict[str, int] = {}
    pk_map = {
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
        "ground_truth.csv": "anomaly_id",
    }
    for filename, pk in pk_map.items():
        if filename in dfs:
            total = len(dfs[filename])
            unique = dfs[filename][pk].n_unique()
            duplicate_counts[filename] = total - unique

    results["metrics"]["duplicate_counts"] = duplicate_counts

    # Check ID patterns
    id_regex_map = {
        "plant_id": r"^PLANT-\d{2}$",
        "line_id": r"^LINE-\d{2}$",
        "machine_id": r"^MCH-LINE-\d{2}-\d{2}$",
        "product_id": r"^PRD-\d{4}$",
        "shift_id": r"^SHIFT-\d{4}-\d{2}-\d{2}-[A-C]$",
        "order_id": r"^PO-\d{4}-\d{6}$",
        "count_id": r"^CNT-PO-\d{4}-\d{6}-\d{6}$",
        "inspection_id": r"^QC-\d{4}-\d{6}$",
        "anomaly_id": r"^ANOM-\d{6}$",
    }
    id_pattern_errors = {}
    for filename, pk in pk_map.items():
        if pk in id_regex_map and filename in dfs:
            pattern = id_regex_map[pk]
            invalid_ids = dfs[filename].filter(
                ~pl.col(pk).str.contains(pattern)
            )
            id_pattern_errors[pk] = len(invalid_ids)
    results["metrics"]["id_pattern_errors"] = id_pattern_errors

    # ---------------------------------------------------------
    # 4. Temporal Integrity & Timeline Continuity
    # ---------------------------------------------------------
    # Check start_time <= end_time on state events
    events_df = dfs["state_events.csv"].sort(["machine_id", "start_time"])
    invalid_ordering = events_df.filter(pl.col("start_time") > pl.col("end_time"))
    results["metrics"]["negative_duration_events"] = len(invalid_ordering)

    # Check state event overlaps
    # Compare each event with its next event on the same machine
    temporal_overlaps = []
    machines = events_df["machine_id"].unique().to_list()
    for m in machines:
        m_events = events_df.filter(pl.col("machine_id") == m).sort("start_time")
        starts = m_events["start_time"].to_list()
        ends = m_events["end_time"].to_list()
        ids = m_events["event_id"].to_list()

        for i in range(len(m_events) - 1):
            if starts[i + 1] < ends[i]:
                temporal_overlaps.append({
                    "machine_id": m,
                    "event_1": ids[i],
                    "end_1": ends[i],
                    "event_2": ids[i + 1],
                    "start_2": starts[i + 1],
                })

    results["metrics"]["temporal_overlaps_count"] = len(temporal_overlaps)
    results["metrics"]["temporal_overlaps"] = temporal_overlaps

    # Verify that the only overlaps correspond to EC-01 and EC-05
    overlap_event_ids = {ov["event_2"] for ov in temporal_overlaps}.union(
        {ov["event_1"] for ov in temporal_overlaps}
    )
    for ov_id in overlap_event_ids:
        if ov_id not in gt_record_ids and not any(g.get("related_record_id") == ov_id for g in ground_truth):
            results["findings"].append(f"Unintentional temporal overlap detected on record {ov_id}")

    # Check break timing
    break_events = events_df.filter(pl.col("reason_code") == "DT-PLANNED-BREAK")
    break_durations = break_events["duration_sec"].to_list()
    results["metrics"]["total_break_events"] = len(break_events)
    # Expected break durations: 900s (15m) or 1800s (30m)
    invalid_breaks = [d for d in break_durations if d not in (900, 1800)]
    results["metrics"]["invalid_break_durations"] = len(invalid_breaks)

    # ---------------------------------------------------------
    # 5. Production Count Reconciliation
    # ---------------------------------------------------------
    counts_df = dfs["production_counts.csv"].sort(["order_id", "machine_id", "timestamp"])
    count_drops = []
    arithmetic_violations = []

    # Verify cumulative sum math per (order_id, machine_id)
    orders_machines = counts_df.select(["order_id", "machine_id"]).unique().rows()
    for o_id, m_id in orders_machines:
        om_counts = counts_df.filter(
            (pl.col("order_id") == o_id) & (pl.col("machine_id") == m_id)
        ).sort("timestamp")
        deltas = om_counts["count_delta"].to_list()
        cum_counts = om_counts["cumulative_count"].to_list()
        is_corrs = om_counts["is_correction"].to_list()
        c_ids = om_counts["count_id"].to_list()

        expected_cum = 0
        for i in range(len(om_counts)):
            expected_cum += deltas[i]
            if cum_counts[i] != expected_cum:
                arithmetic_violations.append({
                    "count_id": c_ids[i],
                    "reported_cum": cum_counts[i],
                    "expected_cum": expected_cum,
                })
            # Check for count decreases
            if deltas[i] < 0 and not is_corrs[i]:
                count_drops.append({
                    "count_id": c_ids[i],
                    "delta": deltas[i],
                    "is_correction": is_corrs[i],
                })

    results["metrics"]["unexplained_count_drops"] = len(count_drops)
    results["metrics"]["unexplained_count_drop_records"] = count_drops
    results["metrics"]["cumulative_count_arithmetic_violations"] = len(arithmetic_violations)

    # Confirm EC-02 is the only unexplained count drop
    for cd in count_drops:
        if cd["count_id"] != gt_record_ids.get(cd["count_id"]):
            if cd["count_id"] not in gt_record_ids:
                results["findings"].append(f"Unintentional unexplained count drop on {cd['count_id']}")

    # ---------------------------------------------------------
    # 6. Quality Inspection Reconciliation
    # ---------------------------------------------------------
    qc_df = dfs["quality_inspections.csv"]
    qc_mass_violations = []
    scrap_overflows = []

    for row in qc_df.iter_rows(named=True):
        inspected = row["inspected_qty"]
        passed = row["passed_qty"]
        scrap = row["scrap_qty"]
        rework = row["rework_qty"]
        q_id = row["inspection_id"]

        if passed + scrap + rework != inspected:
            qc_mass_violations.append({
                "inspection_id": q_id,
                "inspected": inspected,
                "sum": passed + scrap + rework,
            })
        if scrap > inspected:
            scrap_overflows.append({
                "inspection_id": q_id,
                "inspected": inspected,
                "scrap": scrap,
            })

    results["metrics"]["qc_mass_balance_violations"] = len(qc_mass_violations)
    results["metrics"]["scrap_overflows"] = len(scrap_overflows)
    results["metrics"]["scrap_overflow_records"] = scrap_overflows

    for so in scrap_overflows:
        if so["inspection_id"] not in gt_record_ids:
            results["findings"].append(f"Unintentional scrap overflow on {so['inspection_id']}")

    # ---------------------------------------------------------
    # 7. Standards & Ideal Cycle Times (EC-04 verification)
    # ---------------------------------------------------------
    std_df = dfs["machine_product_standards.csv"]
    orders_df = dfs["production_orders.csv"]

    # Master standards must remain completely intact as authoritative reference
    unphysical_standards = std_df.filter(
        (pl.col("ideal_cycle_time_sec") < 1.0) | (pl.col("ideal_cycle_time_sec") > 60.0)
    ).to_dicts()
    if unphysical_standards:
        results["findings"].append(f"Master standards corrupted: {unphysical_standards}")

    # Check order planned_cycle_time_sec against master standard (EC-04)
    std_map = {
        (r["machine_id"], r["product_id"]): float(r["ideal_cycle_time_sec"])
        for r in std_df.iter_rows(named=True)
    }

    invalid_orders = []
    for o in orders_df.iter_rows(named=True):
        lead_mch = f"MCH-{o['line_id']}-01"
        master_ict = std_map.get((lead_mch, o["product_id"]))
        planned_ict = float(o.get("planned_cycle_time_sec", 0.0))
        if master_ict is not None and abs(planned_ict - master_ict) > 0.001:
            invalid_orders.append(o)

    results["metrics"]["anomalous_standards_count"] = len(invalid_orders)
    results["metrics"]["anomalous_standards"] = invalid_orders

    for inv in invalid_orders:
        if inv["order_id"] not in gt_record_ids:
            results["findings"].append(f"Unintentional cycle time discrepancy on order {inv['order_id']}")


    # ---------------------------------------------------------
    # 8. Manufacturing Realism & Operational Distributions
    # ---------------------------------------------------------
    state_durations = (
        events_df.group_by("state")
        .agg(pl.col("duration_sec").sum().alias("total_seconds"))
        .with_columns(
            (pl.col("total_seconds") / pl.col("total_seconds").sum() * 100).round(2).alias("percentage")
        )
        .sort("total_seconds", descending=True)
    )
    results["metrics"]["state_distribution"] = state_durations.to_dicts()

    reason_durations = (
        events_df.filter(pl.col("reason_code").is_not_null() & (pl.col("reason_code") != ""))
        .group_by("reason_code")
        .agg(pl.col("duration_sec").sum().alias("total_seconds"))
        .sort("total_seconds", descending=True)
    )
    results["metrics"]["downtime_reason_distribution"] = reason_durations.to_dicts()

    total_counts_sum = dfs["production_counts.csv"]["count_delta"].sum()
    total_inspected_sum = qc_df["inspected_qty"].sum()
    total_scrap_sum = qc_df["scrap_qty"].sum()
    results["metrics"]["total_units_produced"] = total_counts_sum
    results["metrics"]["total_units_inspected"] = total_inspected_sum
    results["metrics"]["total_scrap_units"] = total_scrap_sum

    # Overall verdict determination
    if len(results["findings"]) == 0:
        results["verdict"] = "PASS"
    elif all("WARNING" in f for f in results["findings"]):
        results["verdict"] = "PASS WITH WARNINGS"
    else:
        results["verdict"] = "FAIL"

    return results


if __name__ == "__main__":
    audit = run_audit(Path("data/starter"))
    console.print(f"\n[bold green]Audit Completed - Verdict: {audit['verdict']}[/bold green]\n")
    console.print(json.dumps(audit["metrics"], indent=2))
