"""Independent OEE Recomputation Engine.

Recomputes PPT, operating time, availability, performance, quality and OEE
for every aggregate directly from raw CSVs and validator findings (ignoring ground truth),
using plain standard-library csv and dicts, with zero calculator code.
"""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def _parse_iso(ts_str: str) -> datetime:
    """Parse UTC ISO-8601 timestamp string into timezone-aware datetime."""
    clean = ts_str.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(clean)


class IndependentOEERecomputer:
    """Recomputes manufacturing OEE metrics using pure Python dicts and standard csv."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        tables: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else None
        self._tables = tables or {}

    def _read_csv(self, filename: str) -> List[Dict[str, Any]]:
        """Read a CSV file or retrieve from in-memory tables."""
        if filename in self._tables:
            return self._tables[filename]
        if self.data_dir is None:
            return []
        filepath = self.data_dir / filename
        if not filepath.exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def recompute_all(
        self,
        findings_path: Optional[Path] = None,
        findings_data: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Recompute OEE aggregates directly from raw CSVs and validator findings."""
        shifts = self._read_csv("shifts.csv")
        machines = self._read_csv("machines.csv")
        events = self._read_csv("state_events.csv")
        counts = self._read_csv("production_counts.csv")
        qc_inspections = self._read_csv("quality_inspections.csv")
        standards = self._read_csv("machine_product_standards.csv")
        orders = self._read_csv("production_orders.csv")

        # Standards lookup: (machine_id, product_id) -> ideal_cycle_time_sec
        std_lookup: Dict[Tuple[str, str], float] = {
            (r["machine_id"], r["product_id"]): float(r["ideal_cycle_time_sec"])
            for r in standards
        }

        # Order to product lookup: order_id -> product_id
        order_product: Dict[str, str] = {
            r["order_id"]: r["product_id"] for r in orders
        }

        # Machine to line lookup: machine_id -> line_id
        machine_line: Dict[str, str] = {
            r["machine_id"]: r["line_id"] for r in machines
        }

        # Load findings if provided
        raw_findings: List[Dict[str, Any]] = []
        if findings_data is not None:
            raw_findings = findings_data
        elif findings_path is not None and Path(findings_path).exists():
            with open(findings_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                raw_findings = content.get("findings", [])
        elif self.data_dir is not None:
            default_findings = self.data_dir / "validation_findings.json"
            if default_findings.exists():
                with open(default_findings, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    raw_findings = content.get("findings", [])

        # Index validator findings and exclusions
        excluded_events: Set[str] = set()
        excluded_counts: Set[str] = set()
        excluded_qc: Set[str] = set()
        findings_by_ms: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        # Mappings for routing findings to (machine_id, shift_id)
        evt_ms: Dict[str, Tuple[str, str]] = {}
        for r in events:
            evt_ms[r["event_id"]] = (r["machine_id"], r["shift_id"])

        cnt_ms: Dict[str, Tuple[str, str]] = {}
        order_ms_map: Dict[str, Set[Tuple[str, str]]] = {}
        for r in counts:
            cnt_ms[r["count_id"]] = (r["machine_id"], r["shift_id"])
            order_ms_map.setdefault(r["order_id"], set()).add((r["machine_id"], r["shift_id"]))

        qc_ms: Dict[str, Tuple[str, str]] = {}
        for r in qc_inspections:
            qc_ms[r["inspection_id"]] = (r["machine_id"], r["shift_id"])

        for f in raw_findings:
            rule_id = str(f.get("rule_id", ""))
            table = str(f.get("table_name", "")).replace(".csv", "")
            rec_id = str(f.get("record_id", ""))

            # Exclusion policies
            if rule_id in ("VAL-TIME-001", "VAL-REL-004") and table == "state_events":
                excluded_events.add(rec_id)
            elif rule_id == "VAL-COUNT-001" and table == "production_counts":
                excluded_counts.add(rec_id)
            elif rule_id == "VAL-QUAL-001" and table == "quality_inspections":
                excluded_qc.add(rec_id)

            # Route finding to machine-shift
            if table == "state_events" and rec_id in evt_ms:
                findings_by_ms.setdefault(evt_ms[rec_id], []).append(f)
            elif table == "production_counts" and rec_id in cnt_ms:
                findings_by_ms.setdefault(cnt_ms[rec_id], []).append(f)
            elif table == "quality_inspections" and rec_id in qc_ms:
                findings_by_ms.setdefault(qc_ms[rec_id], []).append(f)
            elif table == "production_orders" and rec_id in order_ms_map:
                for target_ms in order_ms_map[rec_id]:
                    findings_by_ms.setdefault(target_ms, []).append(f)
            elif ":" in rec_id:
                parts = rec_id.split(":")
                if len(parts) == 2:
                    findings_by_ms.setdefault((parts[0], parts[1]), []).append(f)

        # Pre-group telemetry records by (shift_id, machine_id)
        events_by_ms: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
        for r in events:
            events_by_ms.setdefault((r["shift_id"], r["machine_id"]), []).append(r)

        counts_by_ms: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
        for r in counts:
            counts_by_ms.setdefault((r["shift_id"], r["machine_id"]), []).append(r)

        qc_by_ms: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
        for r in qc_inspections:
            qc_by_ms.setdefault((r["shift_id"], r["machine_id"]), []).append(r)

        recomputed: List[Dict[str, Any]] = []

        # Iterate over all (Shift, Machine) combinations
        for shift in shifts:
            shift_id = shift["shift_id"]
            start_dt = _parse_iso(shift["start_time"])
            end_dt = _parse_iso(shift["end_time"])
            shift_duration_sec = int((end_dt - start_dt).total_seconds())

            for machine in machines:
                machine_id = machine["machine_id"]
                line_id = machine_line.get(machine_id, "LINE-01")
                ms_key = (machine_id, shift_id)

                # 1. State Events and Triage Policies
                m_events = events_by_ms.get((shift_id, machine_id), [])

                # Sort chronologically, prioritizing planned downtime when start times match
                m_sorted_ev = sorted(
                    m_events,
                    key=lambda e: (e["start_time"], 0 if e["state"] == "PLANNED_DOWNTIME" else 1),
                )

                break_intervals = [
                    (_parse_iso(ev["start_time"]), _parse_iso(ev["end_time"]))
                    for ev in m_sorted_ev
                    if ev["state"] == "PLANNED_DOWNTIME"
                ]

                running_sec = 0
                planned_dt_sec = 0
                unplanned_dt_sec = 0
                prev_event_end: Optional[datetime] = None

                for ev in m_sorted_ev:
                    if ev["event_id"] in excluded_events:
                        continue

                    st = ev["state"]
                    s_dt = _parse_iso(ev["start_time"])
                    e_dt = _parse_iso(ev["end_time"])

                    # Decision EC-01: Clip later event's start to previous event's end
                    if prev_event_end is not None and s_dt < prev_event_end:
                        s_dt = prev_event_end

                    dur = max(0, int((e_dt - s_dt).total_seconds()))

                    # Decision EC-05: Clip breakdown at break boundary
                    if st == "UNPLANNED_DOWNTIME":
                        overlap_sec = 0
                        for b_s, b_e in break_intervals:
                            o_s = max(s_dt, b_s)
                            o_e = min(e_dt, b_e)
                            if o_e > o_s:
                                overlap_sec += int((o_e - o_s).total_seconds())
                        dur = max(0, dur - overlap_sec)

                    if e_dt > (prev_event_end or datetime.min.replace(tzinfo=timezone.utc)):
                        prev_event_end = e_dt

                    if st == "RUNNING":
                        running_sec += dur
                    elif st == "PLANNED_DOWNTIME":
                        planned_dt_sec += dur
                    elif st in ("UNPLANNED_DOWNTIME", "CHANGEOVER", "STARVED", "BLOCKED"):
                        unplanned_dt_sec += dur

                planned_prod_time_sec = max(0, shift_duration_sec - planned_dt_sec)
                operating_time_sec = running_sec

                # 2. Production Counts (Decision EC-02)
                m_counts = counts_by_ms.get((shift_id, machine_id), [])
                valid_counts = [
                    r for r in m_counts
                    if r["count_id"] not in excluded_counts
                    and (int(r["count_delta"]) >= 0 or r.get("is_correction") in (True, "True", "true", "1"))
                ]
                total_count = max(0, sum(int(r["count_delta"]) for r in valid_counts))

                # 3. Quality Inspections (Decision EC-03)
                m_qc = qc_by_ms.get((shift_id, machine_id), [])
                valid_qc = [
                    r for r in m_qc
                    if r["inspection_id"] not in excluded_qc
                    and int(r["scrap_qty"]) <= int(r["inspected_qty"])
                    and (int(r["passed_qty"]) + int(r["scrap_qty"]) + int(r["rework_qty"]) == int(r["inspected_qty"]))
                ]

                sampled_inspected = sum(int(r["inspected_qty"]) for r in valid_qc)
                sampled_passed = sum(int(r["passed_qty"]) for r in valid_qc)
                sampled_scrap = sum(int(r["scrap_qty"]) for r in valid_qc)
                sampled_rework = sum(int(r["rework_qty"]) for r in valid_qc)

                if sampled_inspected > 0:
                    conforming_sampled = max(0, sampled_inspected - sampled_scrap)
                    sample_yield = min(1.0, max(0.0, float(conforming_sampled) / float(sampled_inspected)))
                else:
                    sample_yield = 1.0

                good_count = int(round(total_count * sample_yield))
                good_count = max(0, min(total_count, good_count))
                scrap_count = max(0, total_count - good_count)
                rework_count = (
                    int(round(total_count * (float(sampled_rework) / float(sampled_inspected))))
                    if sampled_inspected > 0
                    else 0
                )
                quality = float(good_count) / float(total_count) if total_count > 0 else 1.0

                # 4. Standard Cycle Time Resolution (Decision EC-04)
                active_orders = [r["order_id"] for r in valid_counts]
                if not active_orders:
                    active_orders = [
                        ev["order_id"] for ev in m_sorted_ev
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
                    tot_units = sum(c for c, _ in product_runs)
                    weighted_time = sum(c * ict for c, ict in product_runs)
                    effective_ict = weighted_time / float(tot_units)
                else:
                    effective_ict = 10.0

                # 5. OEE Components
                if planned_prod_time_sec > 0:
                    avail = min(1.0, max(0.0, float(operating_time_sec) / float(planned_prod_time_sec)))
                else:
                    avail = 0.0

                if operating_time_sec > 0:
                    perf = (float(total_count) * effective_ict) / float(operating_time_sec)
                else:
                    perf = 0.0

                oee = avail * perf * quality

                # 6. Lifecycle Status & Exception Count
                ms_findings = findings_by_ms.get(ms_key, [])
                exception_count = len(ms_findings)
                if exception_count == 0:
                    status = "CLEAN"
                elif any(str(f.get("severity", "")).upper() in ("ERROR", "SEVERITY.ERROR") for f in ms_findings):
                    status = "ANOMALOUS"
                else:
                    status = "FLAGGED"

                agg_id = f"OEE-{shift_id}-{machine_id}"
                recomputed.append({
                    "aggregate_id": agg_id,
                    "shift_id": shift_id,
                    "machine_id": machine_id,
                    "line_id": line_id,
                    "planned_prod_time_sec": planned_prod_time_sec,
                    "operating_time_sec": operating_time_sec,
                    "unplanned_downtime_sec": unplanned_dt_sec,
                    "planned_downtime_sec": planned_dt_sec,
                    "total_count": total_count,
                    "good_count": good_count,
                    "scrap_count": scrap_count,
                    "rework_count": rework_count,
                    "ideal_cycle_time_sec": round(effective_ict, 3),
                    "availability": round(avail, 4),
                    "performance": round(perf, 4),
                    "quality": round(quality, 4),
                    "oee": round(oee, 4),
                    "status": status,
                    "exception_count": exception_count,
                })

        recomputed.sort(key=lambda a: (a["shift_id"], a["machine_id"]))
        return recomputed

    def compare_against_file(
        self,
        aggregates_csv: Path,
        findings_path: Optional[Path] = None,
        tolerance: float = 1e-6,
    ) -> Dict[str, Any]:
        """Compare independent recomputation against an existing oee_aggregates.csv."""
        recomputed = self.recompute_all(findings_path=findings_path)
        recomp_map = {r["aggregate_id"]: r for r in recomputed}

        target_csv = Path(aggregates_csv)
        if not target_csv.exists():
            return {
                "matched": False,
                "total_rows": 0,
                "mismatches": [{"error": f"File not found: {target_csv}"}],
            }

        with open(target_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            file_rows = list(reader)

        mismatches: List[Dict[str, Any]] = []
        compared_count = 0

        for row in file_rows:
            agg_id = row["aggregate_id"]
            if agg_id not in recomp_map:
                mismatches.append({
                    "aggregate_id": agg_id,
                    "field": "aggregate_id",
                    "reason": "Missing in recomputed aggregates",
                })
                continue

            rec = recomp_map[agg_id]
            compared_count += 1

            # Compare integer metrics
            for int_field in (
                "planned_prod_time_sec",
                "operating_time_sec",
                "unplanned_downtime_sec",
                "planned_downtime_sec",
                "total_count",
                "good_count",
                "scrap_count",
                "rework_count",
                "exception_count",
            ):
                file_val = int(row[int_field])
                rec_val = int(rec[int_field])
                if file_val != rec_val:
                    mismatches.append({
                        "aggregate_id": agg_id,
                        "field": int_field,
                        "file_value": file_val,
                        "recomputed_value": rec_val,
                        "diff": abs(file_val - rec_val),
                    })

            # Compare float metrics within tolerance
            for float_field in ("ideal_cycle_time_sec", "availability", "performance", "quality", "oee"):
                file_val = float(row[float_field])
                rec_val = float(rec[float_field])
                delta = abs(file_val - rec_val)
                if delta > tolerance:
                    mismatches.append({
                        "aggregate_id": agg_id,
                        "field": float_field,
                        "file_value": file_val,
                        "recomputed_value": rec_val,
                        "diff": delta,
                        "tolerance": tolerance,
                    })

            # Compare status string
            if row["status"] != rec["status"]:
                mismatches.append({
                    "aggregate_id": agg_id,
                    "field": "status",
                    "file_value": row["status"],
                    "recomputed_value": rec["status"],
                })

        return {
            "matched": len(mismatches) == 0 and compared_count == len(recomputed),
            "total_recomputed": len(recomputed),
            "total_file_rows": len(file_rows),
            "compared_count": compared_count,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches[:50],  # cap reporting
            "tolerance": tolerance,
        }
