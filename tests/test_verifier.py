"""Tests for two-process bitwise verification runner and CLI verify command."""

import json
from pathlib import Path
import pytest
from click.testing import CliRunner

from yotta_oee.cli import main
from yotta_oee.verifier.engine import VerificationRunner


class TestVerificationRunner:
    def test_two_process_verification_starter_deterministic(self, tmp_path: Path):
        """Run verification runner on starter profile and assert 100% bitwise matching and deterministic reports."""
        reports_dir = tmp_path / "reports"
        verifier = VerificationRunner(profile="starter", seed=20261022, reports_dir=reports_dir)
        result = verifier.run_two_process_verification()

        repro = result["reproducibility_report"]
        assert repro["status"] == "PASS"
        assert repro["all_matched"] is True
        assert repro["total_files_compared"] >= 15

        # Check deterministic reports exist
        repro_file = Path(result["reproducibility_file"])
        val_json_file = Path(result["validation_json_file"])
        val_md_file = Path(result["validation_md_file"])

        assert repro_file.exists()
        assert val_json_file.exists()
        assert val_md_file.exists()

        with open(val_json_file, "r", encoding="utf-8") as vf:
            v_data = json.load(vf)
        assert v_data["profile"] == "starter"
        assert v_data["seed"] == 20261022
        assert "findings_by_rule" in v_data
        # Ensure no timestamps exist in the report output
        assert "timestamp" not in v_data
        assert "generated_at" not in v_data

    def test_cli_verify_command(self, tmp_path: Path):
        """Test verify CLI command execution."""
        runner = CliRunner()
        reports_dir = tmp_path / "cli_reports"
        result = runner.invoke(
            main,
            ["verify", "--profile", "starter", "--seed", "20261022", "--reports-dir", str(reports_dir)],
        )
        assert result.exit_code == 0, f"CLI verify failed: {result.output}"
        assert "Two-Process Reproducibility: PASS" in result.output
        assert (reports_dir / "reproducibility_report.json").exists()
        assert (reports_dir / "validation_summary.json").exists()
        assert (reports_dir / "validation_summary.md").exists()
