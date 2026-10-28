"""Measure exact execution times for all CLI commands and run fresh clone test."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def measure_cmd(label: str, cmd: list[str]) -> dict:
    print(f"--> Measuring: {label} ({' '.join(cmd)})")
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    duration = round(time.perf_counter() - t0, 2)
    print(f"    Finished in {duration}s with exit code {proc.returncode}")
    if proc.returncode != 0:
        print(f"    STDERR: {proc.stderr[:500]}")
    return {
        "label": label,
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "duration_sec": duration,
        "stdout_snippet": proc.stdout[:300].strip(),
    }


def main():
    py = sys.executable
    runtimes = []

    # --- STARTER PIPELINE ---
    runtimes.append(measure_cmd(
        "Starter generate",
        [py, "-m", "yotta_oee", "generate", "--profile", "starter", "--seed", "20261022", "-o", "data/starter"]
    ))
    runtimes.append(measure_cmd(
        "Starter validate",
        [py, "-m", "yotta_oee", "validate", "-i", "data/starter", "-o", "reports/validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Starter calculate-oee",
        [py, "-m", "yotta_oee", "calculate-oee", "-i", "data/starter", "-f", "reports/validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Starter recompute-oee",
        [py, "-m", "yotta_oee", "recompute-oee", "-i", "data/starter", "-f", "reports/validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Starter benchmark",
        [py, "-m", "yotta_oee", "benchmark", "-i", "data/starter", "-f", "reports/validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Starter export",
        [py, "-m", "yotta_oee", "export", "-i", "data/starter", "-o", "data/starter/exports", "-f", "json,sql"]
    ))
    runtimes.append(measure_cmd(
        "Starter verify",
        [py, "-m", "yotta_oee", "verify", "--profile", "starter", "--seed", "20261022"]
    ))

    # --- FULL PIPELINE ---
    # Remove stale full OEE aggregates so validator runs on raw full data cleanly
    stale_agg = Path("data/full/oee_aggregates.csv")
    if stale_agg.exists():
        stale_agg.unlink()
    stale_dec = Path("data/full/oee_decisions.csv")
    if stale_dec.exists():
        stale_dec.unlink()

    runtimes.append(measure_cmd(
        "Full generate",
        [py, "-m", "yotta_oee", "generate", "--profile", "full", "--seed", "20261022", "-o", "data/full"]
    ))
    runtimes.append(measure_cmd(
        "Full validate",
        [py, "-m", "yotta_oee", "validate", "-i", "data/full", "-o", "reports/full_validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Full calculate-oee",
        [py, "-m", "yotta_oee", "calculate-oee", "-i", "data/full", "-f", "reports/full_validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Full recompute-oee",
        [py, "-m", "yotta_oee", "recompute-oee", "-i", "data/full", "-f", "reports/full_validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Full benchmark",
        [py, "-m", "yotta_oee", "benchmark", "-i", "data/full", "-f", "reports/full_validation_findings.json"]
    ))
    runtimes.append(measure_cmd(
        "Full export",
        [py, "-m", "yotta_oee", "export", "-i", "data/full", "-o", "data/full/exports", "-f", "json,sql"]
    ))

    # Write runtimes JSON
    out_runtimes = Path("docs/evidence/measured_runtimes.json")
    with open(out_runtimes, "w", encoding="utf-8") as f:
        json.dump(runtimes, f, indent=2)
    print(f"\nMeasured runtimes written to: {out_runtimes}")

    # Re-compute distributions now that full dataset is fresh
    import subprocess
    subprocess.run([py, "scripts/compute_distributions.py"], check=True)

    # Re-copy fresh full manifest to docs
    shutil.copy("data/full/manifest.json", "docs/full_dataset_manifest.json")

    # --- FRESH CLONE TEST ---
    print("\n--> Starting Fresh Clone & Multi-Python Environment Test...")
    run_fresh_clone_test(py)


def run_fresh_clone_test(primary_python: str):
    repo_root = Path.cwd().resolve()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        clone_dir = temp_path / "yotta_clone"
        
        # Copy repo files (excluding .venv, .git, .pytest_cache, __pycache__)
        print(f"    Copying repository to clean sandbox: {clone_dir}")
        shutil.copytree(
            repo_root,
            clone_dir,
            ignore=shutil.ignore_patterns(".venv", ".git", ".pytest_cache", "__pycache__", "data/full"),
        )

        steps = []
        venv_dir = clone_dir / ".venv"
        venv_py = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

        # 1. Create fresh virtualenv
        t0 = time.perf_counter()
        p1 = subprocess.run([primary_python, "-m", "venv", str(venv_dir)], capture_output=True, text=True)
        steps.append({
            "step": "1_create_venv",
            "command": f"{primary_python} -m venv <CLONE_DIR>\\.venv",
            "returncode": p1.returncode,
            "duration_sec": round(time.perf_counter() - t0, 2),
            "stdout_summary": p1.stdout.strip()[:200],
            "stderr_summary": p1.stderr.strip()[:200],
        })

        # 2. Install editable package and dependencies
        t0 = time.perf_counter()
        p2 = subprocess.run([str(venv_py), "-m", "pip", "install", "-e", "."], cwd=clone_dir, capture_output=True, text=True)
        steps.append({
            "step": "2_pip_install_editable",
            "command": "<CLONE_DIR>\\.venv\\Scripts\\python.exe -m pip install -e .",
            "returncode": p2.returncode,
            "duration_sec": round(time.perf_counter() - t0, 2),
            "stdout_summary": p2.stdout.strip()[-200:],
            "stderr_summary": p2.stderr.strip()[:200],
        })

        # 3. Run pytest in cloned environment
        p_pytest = subprocess.run([str(venv_py), "-m", "pip", "install", "pytest"], cwd=clone_dir, capture_output=True, text=True)
        t0 = time.perf_counter()
        p3 = subprocess.run([str(venv_py), "-m", "pytest", "tests"], cwd=clone_dir, capture_output=True, text=True)
        steps.append({
            "step": "3_run_pytest",
            "command": "<CLONE_DIR>\\.venv\\Scripts\\python.exe -m pytest tests",
            "returncode": p3.returncode,
            "duration_sec": round(time.perf_counter() - t0, 2),
            "stdout_summary": p3.stdout.strip()[-300:],
            "stderr_summary": p3.stderr.strip()[:200],
        })

        # 4. Run starter verification in clone
        t0 = time.perf_counter()
        p4 = subprocess.run([str(venv_py), "-m", "yotta_oee", "verify", "--profile", "starter", "--seed", "20261022"], cwd=clone_dir, capture_output=True, text=True)
        steps.append({
            "step": "4_verify_starter_reproducibility",
            "command": "<CLONE_DIR>\\.venv\\Scripts\\python.exe -m yotta_oee verify --profile starter --seed 20261022",
            "returncode": p4.returncode,
            "duration_sec": round(time.perf_counter() - t0, 2),
            "stdout_summary": p4.stdout.strip()[-200:],
            "stderr_summary": p4.stderr.strip()[:200],
        })

        all_passed = all(s["returncode"] == 0 for s in steps)
        clone_report = {
            "status": "PASSED" if all_passed else "FAILED",
            "test_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "steps": steps,
        }

        out_clone = Path("docs/evidence/fresh_clone_test_report.json")
        with open(out_clone, "w", encoding="utf-8") as f:
            json.dump(clone_report, f, indent=2)
        print(f"Fresh clone test report written to: {out_clone} (Status: {clone_report['status']})")


if __name__ == "__main__":
    main()
