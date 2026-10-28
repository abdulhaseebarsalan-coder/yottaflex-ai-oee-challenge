"""Independent verification runner executing two-process bitwise reproducibility checks."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


def compute_file_sha256(filepath: Path) -> str:
    """Compute deterministic SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class VerificationRunner:
    """Runs generation, validation, and OEE calculation across two separate processes."""

    def __init__(
        self,
        profile: str = "starter",
        seed: int = 20261022,
        reports_dir: Optional[Path] = None,
    ) -> None:
        self.profile = profile.strip().lower()
        self.seed = seed
        self.reports_dir = Path(reports_dir) if reports_dir else Path("reports")

    def run_two_process_verification(self) -> Dict[str, Any]:
        """Execute end-to-end pipeline in two separate processes and produce deterministic reports."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            p1_dir = Path(tmp1) / "run1"
            p2_dir = Path(tmp2) / "run2"

            p1_findings = p1_dir / "validation_findings.json"
            p2_findings = p2_dir / "validation_findings.json"
            p1_oee = p1_dir / "oee_aggregates.csv"
            p2_oee = p2_dir / "oee_aggregates.csv"

            # ---------------------------------------------------------------
            # 1. Process 1 Execution
            # ---------------------------------------------------------------
            res_gen1 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "generate", "--profile", self.profile, "--seed", str(self.seed), "--output-dir", str(p1_dir)],
                capture_output=True, text=True
            )
            assert res_gen1.returncode == 0, f"Process 1 generate failed: {res_gen1.stderr}"

            res_val1 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "validate", "-i", str(p1_dir), "-o", str(p1_findings)],
                capture_output=True, text=True
            )
            assert res_val1.returncode == 0, f"Process 1 validate failed: {res_val1.stderr}"

            res_oee1 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "calculate-oee", "-i", str(p1_dir), "-f", str(p1_findings), "-o", str(p1_oee)],
                capture_output=True, text=True
            )
            assert res_oee1.returncode == 0, f"Process 1 calculate-oee failed: {res_oee1.stderr}"

            res_rec1 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "recompute-oee", "-i", str(p1_dir), "-a", str(p1_oee), "-f", str(p1_findings)],
                capture_output=True, text=True
            )
            assert res_rec1.returncode == 0, f"Process 1 recompute-oee failed: {res_rec1.stderr}\n{res_rec1.stdout}"

            # ---------------------------------------------------------------
            # 2. Process 2 Execution (Independent Subprocess)
            # ---------------------------------------------------------------
            res_gen2 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "generate", "--profile", self.profile, "--seed", str(self.seed), "--output-dir", str(p2_dir)],
                capture_output=True, text=True
            )
            assert res_gen2.returncode == 0, f"Process 2 generate failed: {res_gen2.stderr}"

            res_val2 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "validate", "-i", str(p2_dir), "-o", str(p2_findings)],
                capture_output=True, text=True
            )
            assert res_val2.returncode == 0, f"Process 2 validate failed: {res_val2.stderr}"

            res_oee2 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "calculate-oee", "-i", str(p2_dir), "-f", str(p2_findings), "-o", str(p2_oee)],
                capture_output=True, text=True
            )
            assert res_oee2.returncode == 0, f"Process 2 calculate-oee failed: {res_oee2.stderr}"

            res_rec2 = subprocess.run(
                [sys.executable, "-m", "yotta_oee", "recompute-oee", "-i", str(p2_dir), "-a", str(p2_oee), "-f", str(p2_findings)],
                capture_output=True, text=True
            )
            assert res_rec2.returncode == 0, f"Process 2 recompute-oee failed: {res_rec2.stderr}\n{res_rec2.stdout}"

            # ---------------------------------------------------------------
            # 3. Discover Files & Compare SHA-256 Hashes
            # ---------------------------------------------------------------
            # Collect all files in p1_dir excluding metadata containing timestamps
            files_to_compare: List[str] = []
            for p in sorted(p1_dir.rglob("*")):
                if p.is_file() and p.name != "run_metadata.json":
                    rel = p.relative_to(p1_dir)
                    files_to_compare.append(str(rel))

            comparisons: List[Dict[str, Any]] = []
            all_matched = True

            for rel_str in sorted(files_to_compare):
                f1 = p1_dir / rel_str
                f2 = p2_dir / rel_str
                h1 = compute_file_sha256(f1)
                h2 = compute_file_sha256(f2) if f2.exists() else "MISSING"
                match = (h1 == h2)
                if not match:
                    all_matched = False
                comparisons.append({
                    "file_name": rel_str.replace("\\", "/"),
                    "process_1_sha256": h1,
                    "process_2_sha256": h2,
                    "match": match,
                })

            # ---------------------------------------------------------------
            # 4. Generate Deterministic Reports (No Timestamps)
            # ---------------------------------------------------------------
            reproducibility_report = {
                "profile": self.profile,
                "seed": self.seed,
                "status": "PASS" if all_matched else "FAIL",
                "total_files_compared": len(comparisons),
                "all_matched": all_matched,
                "comparisons": comparisons,
            }
            repro_path = self.reports_dir / "reproducibility_report.json"
            with open(repro_path, "w", encoding="utf-8") as rf:
                json.dump(reproducibility_report, rf, indent=2)

            # Parse findings for deterministic validation summary
            with open(p1_findings, "r", encoding="utf-8") as vf:
                findings_raw = json.load(vf)
            findings_list = findings_raw.get("findings", [])

            findings_by_rule: Dict[str, int] = {}
            findings_by_severity: Dict[str, int] = {}
            findings_by_table: Dict[str, int] = {}

            for f in findings_list:
                r_id = f.get("rule_id", "UNKNOWN")
                sev = f.get("severity", "UNKNOWN")
                tbl = f.get("table_name", "UNKNOWN")
                findings_by_rule[r_id] = findings_by_rule.get(r_id, 0) + 1
                findings_by_severity[sev] = findings_by_severity.get(sev, 0) + 1
                findings_by_table[tbl] = findings_by_table.get(tbl, 0) + 1

            validation_summary_json = {
                "profile": self.profile,
                "seed": self.seed,
                "total_findings": len(findings_list),
                "findings_by_rule": {k: findings_by_rule[k] for k in sorted(findings_by_rule.keys())},
                "findings_by_severity": {k: findings_by_severity[k] for k in sorted(findings_by_severity.keys())},
                "findings_by_table": {k: findings_by_table[k] for k in sorted(findings_by_table.keys())},
            }
            val_json_path = self.reports_dir / "validation_summary.json"
            with open(val_json_path, "w", encoding="utf-8") as vjf:
                json.dump(validation_summary_json, vjf, indent=2)

            # Generate validation_summary.md (No timestamps)
            md_lines = [
                f"# Validation Summary Report ({self.profile.capitalize()} Profile)",
                "",
                f"- **Profile**: `{self.profile}`",
                f"- **Seed**: `{self.seed}`",
                f"- **Total Violations Detected**: `{len(findings_list)}`",
                f"- **Reproducibility Verdict**: `{'PASS (100% Bitwise Identical)' if all_matched else 'FAIL'}`",
                "",
                "## Findings Breakdown by Validation Rule",
                "",
                "| Rule ID | Severity | Table | Findings Count |",
                "| :--- | :--- | :--- | :---: |",
            ]
            for r_id in sorted(findings_by_rule.keys()):
                cnt = findings_by_rule[r_id]
                # Find severity and table from first matching finding
                sample = next((f for f in findings_list if f.get("rule_id") == r_id), {})
                sev = sample.get("severity", "ERROR")
                tbl = sample.get("table_name", "multiple")
                md_lines.append(f"| `{r_id}` | `{sev}` | `{tbl}` | {cnt:,} |")

            md_lines.extend([
                "",
                "## Findings Breakdown by Table",
                "",
                "| Table Name | Violations |",
                "| :--- | :---: |",
            ])
            for tbl in sorted(findings_by_table.keys()):
                md_lines.append(f"| `{tbl}` | {findings_by_table[tbl]:,} |")

            val_md_path = self.reports_dir / "validation_summary.md"
            with open(val_md_path, "w", encoding="utf-8") as vmf:
                vmf.write("\n".join(md_lines) + "\n")

            return {
                "reproducibility_report": reproducibility_report,
                "validation_summary": validation_summary_json,
                "reproducibility_file": str(repro_path),
                "validation_json_file": str(val_json_path),
                "validation_md_file": str(val_md_path),
            }
