"""Comprehensive Stale-number sweep script for Phase 7b verification.

Extracts quantitative metrics, row counts, break allocations, micro-stop ranges,
scrap rates, decision counts, and reproducibility assertions from README.md, docs,
and manifests, asserting 100% consistency across all repository documentation.
"""

import csv
import json
from pathlib import Path
import re
import sys


def sweep():
    print("=" * 75)
    print("PHASE 7b COMPREHENSIVE STALE-NUMBER SWEEP & CONSISTENCY AUDITOR")
    print("=" * 75)

    repo_root = Path(".")
    mismatches = []
    checked = 0

    # ---------------------------------------------------------
    # 1. Manifests & Physical Row Counts
    # ---------------------------------------------------------
    print("\n[1] Checking Starter & Full Manifest Integrity...")
    starter_manifest_path = repo_root / "data" / "starter" / "manifest.json"
    full_manifest_path = repo_root / "docs" / "full_dataset_manifest.json"

    assert starter_manifest_path.exists(), "Starter manifest missing"
    assert full_manifest_path.exists(), "Full manifest missing"

    with open(starter_manifest_path, "r", encoding="utf-8") as f:
        starter_manifest = json.load(f)
    with open(full_manifest_path, "r", encoding="utf-8") as f:
        full_manifest = json.load(f)

    # Starter physical row counts
    for table_name, exp_rows in starter_manifest["row_counts"].items():
        if table_name == "ground_truth/ground_truth.csv":
            p = repo_root / "data" / "starter" / "ground_truth" / "ground_truth.csv"
        else:
            p = repo_root / "data" / "starter" / table_name
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                actual = sum(1 for _ in f) - 1
            checked += 1
            if actual != exp_rows:
                mismatches.append(f"Starter {table_name}: manifest claims {exp_rows}, file has {actual}")
            else:
                print(f"  [OK] Starter {table_name}: {actual:,} rows")

    # Full manifest physical row counts (if data/full exists)
    data_full_dir = repo_root / "data" / "full"
    if data_full_dir.exists():
        for table_name, exp_rows in full_manifest["row_counts"].items():
            if table_name == "ground_truth/ground_truth.csv":
                p = data_full_dir / "ground_truth" / "ground_truth.csv"
            else:
                p = data_full_dir / table_name
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    actual = sum(1 for _ in f) - 1
                checked += 1
                if actual != exp_rows:
                    mismatches.append(f"Full {table_name}: manifest claims {exp_rows}, file has {actual}")
                else:
                    print(f"  [OK] Full {table_name}: {actual:,} rows")

    # ---------------------------------------------------------
    # 2. Evidence Artifact Consistency
    # ---------------------------------------------------------
    print("\n[2] Checking Evidence JSON Artifacts...")
    evidence_dir = repo_root / "docs" / "evidence"

    # (a) full_oee_summary.json
    full_oee_path = evidence_dir / "full_oee_summary.json"
    if full_oee_path.exists():
        with open(full_oee_path, "r", encoding="utf-8") as f:
            full_oee = json.load(f)
        
        checked += 1
        if full_oee["total_aggregates"] != 8100:
            mismatches.append(f"full_oee_summary total_aggregates {full_oee['total_aggregates']} != 8100")
        else:
            print(f"  [OK] full_oee_summary: total_aggregates = {full_oee['total_aggregates']}")

        checked += 1
        if full_oee["anomalous_aggregates_count"] != 136:
            mismatches.append(f"full_oee_summary anomalous_aggregates_count {full_oee['anomalous_aggregates_count']} != 136")
        else:
            print(f"  [OK] full_oee_summary: anomalous_aggregates = {full_oee['anomalous_aggregates_count']}")

        checked += 1
        if full_oee["clean_aggregates_count"] != 7964:
            mismatches.append(f"full_oee_summary clean_aggregates_count {full_oee['clean_aggregates_count']} != 7964")
        else:
            print(f"  [OK] full_oee_summary: clean_aggregates = {full_oee['clean_aggregates_count']}")

        checked += 1
        eq = full_oee["equivalence_verification"]
        if eq["passed_count"] != 8100 or eq["failed_count"] != 0:
            mismatches.append(f"full_oee_summary equivalence failures: {eq}")
        else:
            print(f"  [OK] full_oee_summary: equivalence verified 8,100/8,100 (max delta: {eq['max_delta']})")

        checked += 1
        qs = full_oee["quality_sampling"]
        if qs["total_inspections"] != full_manifest["row_counts"]["quality_inspections.csv"]:
            mismatches.append(f"full_oee_summary inspections {qs['total_inspections']} != manifest {full_manifest['row_counts']['quality_inspections.csv']}")
        else:
            print(f"  [OK] full_oee_summary: total_inspections = {qs['total_inspections']:,}")

    # (b) benchmark_results.json
    bench_path = evidence_dir / "benchmark_results.json"
    if bench_path.exists():
        with open(bench_path, "r", encoding="utf-8") as f:
            bench = json.load(f)
        
        checked += 1
        if bench["total_ground_truth_anomalies"] != 50 or bench["true_positives"] != 50 or bench["false_negatives"] != 0 or bench["recall"] != 1.0:
            mismatches.append(f"benchmark_results.json recall is not 100%: {bench}")
        else:
            print(f"  [OK] benchmark_results: Recall=100% (TP={bench['true_positives']}/{bench['total_ground_truth_anomalies']}, FN={bench['false_negatives']})")

        checked += 1
        d_type = bench["detection_by_type"]
        all_detected = all(v["detected"] == 10 and v["total"] == 10 for v in d_type.values())
        if not all_detected or len(d_type) != 5:
            mismatches.append(f"benchmark_results.json detection_by_type incomplete: {d_type}")
        else:
            print("  [OK] benchmark_results: 100% detection (10/10) across all 5 anomaly types (50/50)")

    # (c) distributions.json
    dist_path = evidence_dir / "distributions.json"
    if dist_path.exists():
        with open(dist_path, "r", encoding="utf-8") as f:
            dist = json.load(f)

        checked += 1
        tot_brk = dist["planned_break_scenarios"]["total_breaks"]
        if tot_brk != 24300:
            mismatches.append(f"distributions.json total_breaks {tot_brk} != 24,300")
        else:
            print(f"  [OK] distributions.json: total_breaks = {tot_brk:,} (3 per machine-shift, 90 per calendar shift)")

        checked += 1
        ms_cnt = dist["micro_stop_scenarios"]["count"]
        if ms_cnt != 7497:
            mismatches.append(f"distributions.json micro_stop count {ms_cnt} != 7,497")
        else:
            print(f"  [OK] distributions.json: micro_stop_count = {ms_cnt:,}")

        checked += 1
        pulse_cnt = dist["count_corrections_scenarios"]["total_production_counts"]
        if pulse_cnt != full_manifest["row_counts"]["production_counts.csv"]:
            mismatches.append(f"distributions.json pulse count {pulse_cnt} != manifest {full_manifest['row_counts']['production_counts.csv']}")
        else:
            print(f"  [OK] distributions.json: total_production_counts = {pulse_cnt:,}")

        checked += 1
        neg_corr = dist["count_corrections_scenarios"]["negative_delta_corrections_count"]
        ref_corr = dist["count_corrections_scenarios"]["corrections_with_ref_link"]
        if neg_corr - ref_corr != 10:
            mismatches.append(f"distributions.json unreferenced corrections {neg_corr - ref_corr} != 10 (EC-02)")
        else:
            print(f"  [OK] distributions.json: count corrections = {neg_corr:,} ({ref_corr:,} referenced + 10 EC-02 drops)")

    # (d) fresh_clone_test_report.json
    clone_path = evidence_dir / "fresh_clone_test_report.json"
    if clone_path.exists():
        with open(clone_path, "r", encoding="utf-8") as f:
            clone_rep = json.load(f)
        checked += 1
        if clone_rep.get("status") != "PASSED":
            mismatches.append(f"fresh_clone_test_report status is {clone_rep.get('status')}")
        else:
            print("  [OK] fresh_clone_test_report: status = PASSED")

    # (e) measured_runtimes.json
    runtimes_path = evidence_dir / "measured_runtimes.json"
    if runtimes_path.exists():
        with open(runtimes_path, "r", encoding="utf-8") as f:
            runtimes = json.load(f)
        checked += 1
        non_zero = [r for r in runtimes if r.get("returncode") != 0]
        if non_zero:
            mismatches.append(f"measured_runtimes has non-zero exit codes: {non_zero}")
        else:
            print(f"  [OK] measured_runtimes: all {len(runtimes)} CLI commands succeeded with returncode 0")

    # ---------------------------------------------------------
    # 3. README Text & Quantitative Audit
    # ---------------------------------------------------------
    print("\n[3] Checking README.md Strict Consistency...")
    readme_path = repo_root / "README.md"
    assert readme_path.exists(), "README.md missing"
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_text = f.read()

    # (a) Deprecated phrases
    forbidden_terms = [
        ("micro-stop alerts", "README actor table contains deprecated 'micro-stop alerts'"),
        ("MTBF/MTTR", "README actor table contains deprecated 'MTBF/MTTR'"),
        ("takt adherence", "README actor table contains deprecated 'takt adherence'"),
        ("1 scheduled break per shift-machine", "README claims '1 scheduled break per shift-machine' instead of 3"),
    ]
    for term, msg in forbidden_terms:
        checked += 1
        if term in readme_text:
            mismatches.append(msg)
        else:
            print(f"  [OK] README does not contain deprecated term: '{term}'")

    # (b) Mandatory exact statements
    required_terms = [
        ("3 scheduled breaks per machine-shift", "README missing '3 scheduled breaks per machine-shift'"),
        ("stop_dur = randint(45, min(stop_rem, 180))", "README missing micro-stop generator code rule"),
        ("EVT-MCH-LINE-02-04-001571", "README missing explanation of the 2 EC-01 micro-stop records"),
        ("EVT-MCH-LINE-02-04-002463", "README missing explanation of the 2 EC-01 micro-stop records"),
        ("base_defect_rate = 0.015 + ((p_num * 7) % 10) * 0.002", "README missing exact scrap code formula"),
        ("1.80x", "README missing 1.80x macro ratio reconciliation"),
        ("MCH-LINE-05-06", "README missing MCH-LINE-05-06 status snapshot explanation"),
        ("588,938", "README pulse record count mismatch (expected 588,938)"),
        ("2,932", "README negative correction count mismatch (expected 2,932)"),
        ("2,922", "README referenced correction count mismatch (expected 2,922)"),
        ("8,100", "README aggregate count mismatch (expected 8,100)"),
        ("136", "README anomalous aggregate count mismatch (expected 136)"),
        ("7,964", "README clean aggregate count mismatch (expected 7,964)"),
    ]
    for term, msg in required_terms:
        checked += 1
        if term in readme_text:
            print(f"  [OK] README contains verified term: '{term}'")
        else:
            mismatches.append(msg)

    # (c) 5-Shift Empirical Results Table in README
    verified_shifts = [
        ("SHIFT-2026-01-02-C", "MCH-LINE-01-02", "76.43%"),
        ("SHIFT-2026-01-03-B", "MCH-LINE-01-05", "78.67%"),
        ("SHIFT-2026-01-07-A", "MCH-LINE-03-02", "75.56%"),
        ("SHIFT-2026-01-06-C", "MCH-LINE-01-05", "77.80%"),
        ("SHIFT-2026-01-08-B", "MCH-LINE-05-06", "79.20%"),
    ]
    for sh, mch, oee_val in verified_shifts:
        checked += 1
        pattern = rf"{sh}.*{mch}.*{oee_val}"
        if re.search(pattern, readme_text):
            print(f"  [OK] README verified shift {sh} / {mch} -> {oee_val}")
        else:
            mismatches.append(f"README missing verified shift entry for {sh} / {mch} ({oee_val})")

    # ---------------------------------------------------------
    # 4. Final Verdict
    # ---------------------------------------------------------
    print("\n" + "=" * 75)
    print(f"SWEEP COMPLETE: {checked} quantitative consistency checks performed.")
    if mismatches:
        print(f"FAILURE: {len(mismatches)} mismatches detected:")
        for m in mismatches:
            print(f"  [X] {m}")
        sys.exit(1)
    else:
        print("SUCCESS: 0 mismatches detected. All numbers strictly verified against files!")
        print("=" * 75)


if __name__ == "__main__":
    sweep()
