"""Command Line Interface (CLI) for the YottaFlex Industrial OEE Analytics Engine."""

import json
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from yotta_oee.calculator.aggregator import OEECalculatorEngine
from yotta_oee.domain.enums import Severity, ValidationRuleId
from yotta_oee.evaluator.benchmark import GroundTruthBenchmark
from yotta_oee.exporter.engine import DatasetExporter
from yotta_oee.generator.engine import DataGenerationEngine
from yotta_oee.validator.base import RuleFinding
from yotta_oee.validator.engine import ValidationEngine
from yotta_oee.verifier.engine import VerificationRunner

console = Console(safe_box=True)



@click.group()
@click.version_option(version="0.1.0", prog_name="yotta-oee")
def main() -> None:
    """YottaFlex Industrial OEE Analytics Engine, Validator & Benchmark Suite."""
    pass


# ---------------------------------------------------------------------------
# 1. Dataset Generation Command
# ---------------------------------------------------------------------------
@main.command("generate")
@click.option(
    "--profile",
    "-p",
    type=click.Choice(["starter", "full"], case_sensitive=False),
    default="starter",
    show_default=True,
    help="Data volume profile: 'starter' (fast, ~3 days) or 'full' (90 days, 600k+ records).",
)
@click.option(
    "--seed",
    "-s",
    type=int,
    default=42,
    show_default=True,
    help="Random seed for 100% deterministic reproducibility.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Directory where generated CSV files and manifest will be written.",
)
def generate_command(profile: str, seed: int, output_dir: Optional[Path]) -> None:
    """Generate synthetic manufacturing telemetry datasets and inject challenge anomalies."""
    console.print(
        Panel.fit(
            f"[bold cyan]YottaFlex OEE Dataset Generator[/bold cyan]\n"
            f"Profile: [yellow]{profile.upper()}[/yellow] | Seed: [green]{seed}[/green]",
            border_style="cyan",
        )
    )

    engine = DataGenerationEngine(profile=profile, seed=seed, output_dir=output_dir)
    with console.status(f"[bold green]Generating {profile} dataset...", spinner="dots"):
        result = engine.generate_and_export()

    console.print(f"[bold green][SUCCESS][/bold green] Dataset successfully generated at: [bold]{result.output_dir}[/bold]\n")

    # Display Row Counts Table
    table = Table(title=f"Generated Tables Summary ({profile.capitalize()} Profile)", border_style="dim")
    table.add_column("Table / File", style="cyan", no_wrap=True)
    table.add_column("Row Count", justify="right", style="green")
    table.add_column("SHA-256 Checksum (first 12 chars)", justify="left", style="dim")

    for filename, count in result.row_counts.items():
        sha = result.manifest["checksums_sha256"].get(filename, "N/A")[:12] + "..."
        table.add_row(filename, f"{count:,}", sha)

    console.print(table)
    console.print(f"Manifest written to: [bold]{result.output_dir / 'manifest.json'}[/bold]\n")


# ---------------------------------------------------------------------------
# 2. Multi-Rule Validation Command
# ---------------------------------------------------------------------------
@main.command("validate")
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/starter"),
    show_default=True,
    help="Directory containing dataset CSV files to validate.",
)
@click.option(
    "--output-report",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=Path("reports/validation_findings.json"),
    show_default=True,
    help="Output JSON path for detailed findings report.",
)
def validate_command(input_dir: Path, output_report: Path) -> None:
    """Run the multi-rule validation engine to discover data-quality and integrity violations."""
    console.print(
        Panel.fit(
            f"[bold cyan]YottaFlex Multi-Rule Validation Engine[/bold cyan]\n"
            f"Target Directory: [yellow]{input_dir}[/yellow]",
            border_style="cyan",
        )
    )

    engine = ValidationEngine()
    with console.status("[bold green]Executing validation rule suite...", spinner="dots"):
        summary = engine.validate_directory(input_dir, output_report=output_report)

    # Display Findings Table
    table = Table(title="Validation Execution Summary", border_style="dim")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total Rules Evaluated", str(summary.total_rules_evaluated))
    table.add_row("Passed Rules", str(summary.passed_rules))
    table.add_row("Failed Rules", str(summary.failed_rules))
    table.add_row("Total Findings", str(summary.total_findings))

    console.print(table)

    if summary.total_findings > 0:
        findings_table = Table(title="Discovered Rule Violations", border_style="red")
        findings_table.add_column("Rule ID", style="bold red")
        findings_table.add_column("Table", style="cyan")
        findings_table.add_column("Record ID", style="yellow")
        findings_table.add_column("Message", style="white")

        for finding in summary.findings:
            findings_table.add_row(
                finding.rule_id.value,
                finding.table_name,
                finding.record_id,
                finding.message,
            )

        console.print(findings_table)

    console.print(f"[bold green][SUCCESS][/bold green] Findings report written to: [bold]{output_report}[/bold]\n")


# ---------------------------------------------------------------------------
# 3. OEE Calculation Command
# ---------------------------------------------------------------------------
@main.command("calculate-oee")
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/starter"),
    show_default=True,
    help="Directory containing source telemetry CSV files.",
)
@click.option(
    "--output-csv",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Output CSV path for Shift x Machine OEE aggregates.",
)
@click.option(
    "--findings-report",
    "-f",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("reports/validation_findings.json"),
    show_default=True,
    help="Optional path to validation findings report to consume.",
)
def calculate_oee_command(input_dir: Path, output_csv: Optional[Path], findings_report: Optional[Path]) -> None:
    """Compute shift-level Availability, Performance, Quality, and OEE metrics."""
    console.print(
        Panel.fit(
            f"[bold cyan]YottaFlex Shift-Level OEE Calculation Engine[/bold cyan]\n"
            f"Source Directory: [yellow]{input_dir}[/yellow]",
            border_style="cyan",
        )
    )

    loaded_findings = None
    if findings_report and findings_report.exists():
        try:
            with open(findings_report, "r", encoding="utf-8") as f:
                raw_summary = json.load(f)
                loaded_findings = [
                    RuleFinding(
                        rule_id=ValidationRuleId(rf["rule_id"]),
                        severity=Severity(rf["severity"]),
                        table_name=rf["table_name"],
                        record_id=rf["record_id"],
                        message=rf.get("message", ""),
                        field_name=rf.get("field_name"),
                        observed_value=rf.get("observed_value", ""),
                        expected_condition=rf.get("expected_condition", ""),
                        details=rf.get("details", {}),
                    )
                    for rf in raw_summary.get("findings", [])
                ]
            console.print(f"[bold cyan]Consumed {len(loaded_findings)} validator findings for decision-policy application.[/bold cyan]")
        except Exception as err:
            console.print(f"[dim]Could not parse findings report: {err}[/dim]")

    target_csv = output_csv or (input_dir / "oee_aggregates.csv")
    engine = OEECalculatorEngine(input_dir)

    with console.status("[bold green]Calculating OEE metrics and verifying analytical equivalence...", spinner="dots"):
        aggregates, summary_meta = engine.calculate_all(output_csv=target_csv, findings=loaded_findings)

    console.print(f"[bold green][SUCCESS][/bold green] Computed [bold]{len(aggregates)}[/bold] OEE aggregates.\n")

    # Display sample aggregates table
    table = Table(title=f"Sample OEE Aggregates (First 6 of {len(aggregates)})", border_style="dim")
    table.add_column("Shift", style="cyan")
    table.add_column("Machine", style="yellow")
    table.add_column("Total Units", justify="right")
    table.add_column("Good Units", justify="right")
    table.add_column("Availability", justify="right", style="green")
    table.add_column("Performance", justify="right", style="green")
    table.add_column("Quality", justify="right", style="green")
    table.add_column("OEE", justify="right", style="bold cyan")
    table.add_column("Status", justify="center")
    table.add_column("Exceptions", justify="right")

    for agg in aggregates[:6]:
        st_style = "green" if agg.status.value == "CLEAN" else ("red" if agg.status.value == "ANOMALOUS" else "yellow")
        table.add_row(
            agg.shift_id,
            agg.machine_id,
            f"{agg.total_count:,}",
            f"{agg.good_count:,}",
            f"{agg.availability:.2%}",
            f"{agg.performance:.2%}",
            f"{agg.quality:.2%}",
            f"{agg.oee:.2%}",
            f"[{st_style}]{agg.status.value}[/{st_style}]",
            str(agg.exception_count),
        )

    console.print(table)

    eq_info = summary_meta["equivalence_verification"]
    console.print(
        f"Analytical Equivalence Identity Check:\n"
        f"Verified: [bold]{eq_info['total_verified']}[/bold] | "
        f"Passed: [bold green]{eq_info['passed_count']}[/bold green] | "
        f"Failed: [bold red]{eq_info['failed_count']}[/bold red] | "
        f"Max Delta: [dim]{eq_info['max_delta']:.2e}[/dim]\n"
    )

    if "quality_sampling" in summary_meta:
        qs = summary_meta["quality_sampling"]
        console.print(
            f"Quality Sampling & Inspection Statistics:\n"
            f"  Inspected Units: [bold]{qs['total_inspected_units']:,}[/bold] units across [bold]{qs['total_inspections']}[/bold] inspections "
            f"(Coverage: [bold green]{qs['sampling_coverage_pct']}%[/bold green] of {qs['total_production_units']:,} total production units)\n"
            f"  Sample Sizes per Shift-Machine: Mean=[bold]{qs['sample_size_stats']['mean_sample_units']}[/bold], "
            f"Min=[bold]{qs['sample_size_stats']['min_sample_units']}[/bold], Max=[bold]{qs['sample_size_stats']['max_sample_units']}[/bold]\n"
            f"  Rework Treatment: [cyan]{qs['rework_accounting']}[/cyan]\n"
        )

    console.print(f"Aggregates exported to: [bold]{target_csv}[/bold]\n")



# ---------------------------------------------------------------------------
# 4. Ground Truth Benchmark Command
# ---------------------------------------------------------------------------
@main.command("benchmark")
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/starter"),
    show_default=True,
    help="Directory containing ground_truth.json.",
)
@click.option(
    "--findings",
    "-f",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("reports/validation_findings.json"),
    show_default=True,
    help="Path to validator findings JSON report.",
)
def benchmark_command(input_dir: Path, findings: Path) -> None:
    """Evaluate validator anomaly detection performance against ground truth labels."""
    console.print(
        Panel.fit(
            f"[bold cyan]YottaFlex Anomaly Detection Benchmark Evaluator[/bold cyan]\n"
            f"Ground Truth: [yellow]{input_dir / 'ground_truth.json'}[/yellow]\n"
            f"Findings Report: [yellow]{findings}[/yellow]",
            border_style="cyan",
        )
    )

    with open(findings, "r", encoding="utf-8") as f:
        findings_data = json.load(f)
    findings_list = findings_data.get("findings", [])

    gt_file = input_dir / "ground_truth" / "ground_truth.json"
    if not gt_file.exists():
        gt_file = input_dir / "ground_truth.json"
    bench = GroundTruthBenchmark(gt_file)
    result = bench.evaluate(findings_list)

    # Display Metrics Table
    table = Table(title="Detection Performance Benchmark", border_style="dim")
    table.add_column("Metric", style="cyan")
    table.add_column("Score", style="bold green", justify="right")

    table.add_row("Total Ground Truth Anomalies", str(result.total_ground_truth_anomalies))
    table.add_row("True Positives (TP)", str(result.true_positives))
    table.add_row("False Positives (FP)", str(result.false_positives))
    table.add_row("False Negatives (FN)", str(result.false_negatives))
    table.add_row("Precision", f"{result.precision:.2%}")
    table.add_row("Recall", f"{result.recall:.2%}")
    table.add_row("F1-Score", f"{result.f1_score:.2%}")

    console.print(table)

    # Detailed Anomaly Type Detection Table
    type_table = Table(title="Detection Breakdown by Challenge Edge Case", border_style="dim")
    type_table.add_column("Anomaly Type", style="cyan")
    type_table.add_column("Total Injected", justify="right")
    type_table.add_column("Detected", justify="right", style="green")
    type_table.add_column("Detection Rate", justify="right", style="bold green")

    for atype, stats in result.detection_by_type.items():
        rate = stats["detected"] / stats["total"] if stats["total"] > 0 else 0.0
        type_table.add_row(
            atype,
            str(stats["total"]),
            str(stats["detected"]),
            f"{rate:.0%}",
        )

    console.print(type_table)
    console.print("[bold green][SUCCESS][/bold green] Benchmark evaluation completed successfully.\n")


# ---------------------------------------------------------------------------
# 5. Dataset Export Command
# ---------------------------------------------------------------------------
@main.command("export")
@click.option(
    "--input-dir",
    "-i",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=Path("data/starter"),
    show_default=True,
    help="Directory containing dataset CSV files to export.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Directory to write export artifacts (default: <input-dir>/exports).",
)
@click.option(
    "--formats",
    "-f",
    type=str,
    default="json,sql",
    show_default=True,
    help="Comma-separated export formats: 'json', 'sql', or 'json,sql'.",
)
def export_command(input_dir: Path, output_dir: Optional[Path], formats: str) -> None:
    """Export manufacturing dataset tables into JSON and SQL relational bundles."""
    format_list = [fmt.strip().lower() for fmt in formats.split(",") if fmt.strip()]
    exporter = DatasetExporter(input_dir=input_dir, output_dir=output_dir)

    console.print(
        Panel.fit(
            f"[bold cyan]YottaFlex Dataset Exporter[/bold cyan]\n"
            f"Source: [yellow]{input_dir}[/yellow] | Formats: [green]{', '.join(format_list)}[/green]",
            border_style="cyan",
        )
    )

    with console.status("[bold green]Generating exports...", spinner="dots"):
        manifest = exporter.export_all(formats=format_list)

    console.print(f"[bold green][SUCCESS][/bold green] Export completed to: [bold]{manifest['output_dir']}[/bold]\n")
    console.print(f"Generated [cyan]{len(manifest['files_generated'])}[/cyan] artifact files across [cyan]{len(manifest['tables'])}[/cyan] domain tables.\n")


# ---------------------------------------------------------------------------
# 6. Two-Process Verification & Reproducibility Command
# ---------------------------------------------------------------------------
@main.command("verify")
@click.option(
    "--profile",
    "-p",
    type=click.Choice(["starter", "full"], case_sensitive=False),
    default="starter",
    show_default=True,
    help="Generation profile to verify: 'starter' (default) or 'full'.",
)
@click.option(
    "--seed",
    "-s",
    type=int,
    default=20261022,
    show_default=True,
    help="Random seed for deterministic multi-process verification.",
)
@click.option(
    "--reports-dir",
    "-r",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path("reports"),
    show_default=True,
    help="Directory to write reproducibility and validation summary reports.",
)
def verify_command(profile: str, seed: int, reports_dir: Path) -> None:
    """Run two-process bitwise reproducibility verification and generate deterministic reports."""
    import sys
    console.print(
        Panel.fit(
            f"[bold cyan]YottaFlex Reproducibility & Validation Verifier[/bold cyan]\n"
            f"Profile: [yellow]{profile.upper()}[/yellow] | Seed: [green]{seed}[/green] | Reports: [dim]{reports_dir}[/dim]",
            border_style="cyan",
        )
    )

    verifier = VerificationRunner(profile=profile, seed=seed, reports_dir=reports_dir)
    with console.status(f"[bold green]Running two-process verification for {profile} profile...", spinner="dots"):
        result = verifier.run_two_process_verification()

    repro = result["reproducibility_report"]
    all_matched = repro["all_matched"]

    # Display Reproducibility Table
    table = Table(title=f"Bitwise Reproducibility Comparison ({profile.upper()} Profile)", border_style="dim")
    table.add_column("File / Artifact", style="cyan")
    table.add_column("Process 1 SHA-256", justify="left", style="dim")
    table.add_column("Process 2 SHA-256", justify="left", style="dim")
    table.add_column("Status", justify="center", style="bold")

    for comp in repro["comparisons"]:
        status_str = "[green]MATCH[/green]" if comp["match"] else "[red]MISMATCH[/red]"
        table.add_row(
            comp["file_name"],
            comp["process_1_sha256"][:16] + "...",
            comp["process_2_sha256"][:16] + "...",
            status_str,
        )

    console.print(table)

    verdict_color = "green" if all_matched else "red"
    console.print(f"\n[{verdict_color}][VERDICT] Two-Process Reproducibility: {repro['status']} ({repro['total_files_compared']} files evaluated)[/{verdict_color}]")
    console.print("Reports written to:")
    console.print(f"  - [bold]{result['reproducibility_file']}[/bold]")
    console.print(f"  - [bold]{result['validation_json_file']}[/bold]")
    console.print(f"  - [bold]{result['validation_md_file']}[/bold]\n")

    if not all_matched:
        sys.exit(1)


if __name__ == "__main__":
    main()
