"""Orchestration engine for synthetic data generation, export, and checksumming."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Dict, List, Optional

import polars as pl

from yotta_oee.domain import (
    DowntimeReason,
    GroundTruthAnomaly,
    Line,
    Machine,
    MachineProductStandard,
    Plant,
    Product,
    ProductionCount,
    ProductionOrder,
    QualityInspection,
    Shift,
    StateEvent,
)
from yotta_oee.generator.anomaly_injector import AnomalyInjector
from yotta_oee.generator.config import GeneratorProfileConfig, get_profile_config
from yotta_oee.generator.master_data import MasterDataGenerator
from yotta_oee.generator.orders import OrderGenerator
from yotta_oee.generator.state_events import StateEventGenerator
from yotta_oee.generator.telemetry import TelemetryGenerator


@dataclass
class GenerationResult:
    """Summary metadata of a completed generation run."""
    profile_name: str
    seed: int
    output_dir: Path
    row_counts: Dict[str, int]
    manifest: Dict[str, Any]


class DataGenerationEngine:
    """Top-level controller for reproducible synthetic manufacturing data generation."""

    def __init__(
        self,
        profile: str = "starter",
        seed: int = 42,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.config = get_profile_config(profile)
        self.seed = seed
        self.output_dir = Path(output_dir) if output_dir else Path("data") / profile
        self.rng = random.Random(seed)

    def generate_and_export(self, skip_anomalies: bool = False) -> GenerationResult:
        """Execute end-to-end generation, inject anomalies, serialize CSVs, and write manifest."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Master Data Generation
        master_gen = MasterDataGenerator(self.config, self.rng)
        plants = master_gen.generate_plants()
        lines = master_gen.generate_lines(plants)
        machines = master_gen.generate_machines(lines)
        products = master_gen.generate_products()
        shifts = master_gen.generate_shifts(plants[0])
        standards = master_gen.generate_standards(machines, products)
        downtime_reasons = master_gen.get_downtime_reasons()

        # 2. Production Orders Scheduling
        order_gen = OrderGenerator(self.config, self.rng)
        orders = order_gen.generate_orders(lines, products, shifts, standards)

        # 3. State Events Timeline
        state_gen = StateEventGenerator(self.config, self.rng)
        state_events = state_gen.generate_state_events(machines, shifts, orders)

        # 4. Telemetry Counts & Quality Inspections
        telemetry_gen = TelemetryGenerator(self.config, self.rng)
        counts, inspections = telemetry_gen.generate_counts_and_inspections(
            state_events, orders, standards, machines=machines
        )

        # 5. Anomaly Injection & Ground Truth Logging (bypassed if clean baseline requested)
        if skip_anomalies:
            ground_truth = []
        else:
            injector = AnomalyInjector(self.config, self.rng)
            (
                state_events,
                counts,
                inspections,
                orders,
                standards,
                ground_truth,
            ) = injector.inject_all(state_events, counts, inspections, orders, standards, shifts)

        # 6. Deterministic Pre-Sorting
        plants.sort(key=lambda p: p.plant_id)
        lines.sort(key=lambda l: l.line_id)
        machines.sort(key=lambda m: m.machine_id)
        products.sort(key=lambda pr: pr.product_id)
        shifts.sort(key=lambda s: s.start_time)
        standards.sort(key=lambda st: st.standard_id)
        downtime_reasons.sort(key=lambda dr: dr.reason_code)
        orders.sort(key=lambda o: (o.scheduled_start, o.order_id))
        state_events.sort(key=lambda e: (e.machine_id, e.start_time, e.event_id))
        counts.sort(key=lambda c: (c.order_id, c.timestamp, c.count_id))
        inspections.sort(key=lambda i: (i.order_id, i.timestamp, i.inspection_id))
        ground_truth.sort(key=lambda g: g.anomaly_id)

        # 7. Write Datasets to Disk
        row_counts = {}
        tables = [
            ("plants.csv", [p.to_dict() for p in plants]),
            ("lines.csv", [l.to_dict() for l in lines]),
            ("machines.csv", [m.to_dict() for m in machines]),
            ("products.csv", [pr.to_dict() for pr in products]),
            ("shifts.csv", [s.to_dict() for s in shifts]),
            ("machine_product_standards.csv", [st.to_dict() for st in standards]),
            ("downtime_reasons.csv", [dr.to_dict() for dr in downtime_reasons]),
            ("production_orders.csv", [o.to_dict() for o in orders]),
            ("state_events.csv", [e.to_dict() for e in state_events]),
            ("production_counts.csv", [c.to_dict() for c in counts]),
            ("quality_inspections.csv", [i.to_dict() for i in inspections]),
        ]

        checksums = {}
        for filename, records in tables:
            filepath = self.output_dir / filename
            row_counts[filename] = len(records)
            self._write_csv(filepath, records)
            checksums[filename] = self._compute_sha256(filepath)

        # Ground truth files written into dedicated ground_truth/ subfolder
        # GOVERNANCE: Isolates ground truth from automated telemetry scanning
        gt_dir = self.output_dir / "ground_truth"
        gt_dir.mkdir(parents=True, exist_ok=True)

        gt_csv_path = gt_dir / "ground_truth.csv"
        self._write_csv(gt_csv_path, [g.to_dict() for g in ground_truth])
        gt_json_path = gt_dir / "ground_truth.json"
        with open(gt_json_path, "w", encoding="utf-8") as f:
            json.dump([g.to_dict() for g in ground_truth], f, indent=2)

        row_counts["ground_truth/ground_truth.csv"] = len(ground_truth)
        checksums["ground_truth/ground_truth.csv"] = self._compute_sha256(gt_csv_path)
        checksums["ground_truth/ground_truth.json"] = self._compute_sha256(gt_json_path)

        # Clean up legacy top-level ground truth files if they exist from older runs
        legacy_csv = self.output_dir / "ground_truth.csv"
        if legacy_csv.exists():
            legacy_csv.unlink()
        legacy_json = self.output_dir / "ground_truth.json"
        if legacy_json.exists():
            legacy_json.unlink()

        # Write execution timestamp to separate run_metadata.json (not used for reproducibility comparison)
        run_metadata = {
            "profile": self.config.profile_name,
            "seed": self.seed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "output_directory": str(self.output_dir.resolve()),
        }
        with open(self.output_dir / "run_metadata.json", "w", encoding="utf-8") as f:
            json.dump(run_metadata, f, indent=2)

        # 8. Manifest Generation (purely deterministic for bitwise verification across runs)
        manifest = {
            "profile": self.config.profile_name,
            "seed": self.seed,
            "row_counts": row_counts,
            "checksums_sha256": checksums,
        }

        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)


        return GenerationResult(
            profile_name=self.config.profile_name,
            seed=self.seed,
            output_dir=self.output_dir,
            row_counts=row_counts,
            manifest=manifest,
        )

    @staticmethod
    def _write_csv(filepath: Path, records: List[Dict[str, Any]]) -> None:
        """Write list of dicts to CSV deterministically."""
        if not records:
            filepath.write_text("", encoding="utf-8")
            return

        headers = list(records[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)

    @staticmethod
    def _compute_sha256(filepath: Path) -> str:
        """Compute SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
