"""Dataset export engine generating multi-format JSON and SQL relational bundles."""

import csv
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import polars as pl

# Canonical dependency order for relational referential integrity
DOMAIN_TABLE_ORDER = [
    "plants",
    "lines",
    "machines",
    "products",
    "shifts",
    "machine_product_standards",
    "downtime_reasons",
    "production_orders",
    "state_events",
    "production_counts",
    "quality_inspections",
    "oee_aggregates",
]

# Canonical DDL Schema with PK, FK, and Enum CHECK Constraints
SQL_SCHEMA_DDL = """-- YottaFlex Industrial OEE Relational Schema (SQLite 3.x / ANSI SQL)
-- Strict primary keys, referential foreign keys, and domain enumeration constraints.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS plants (
    plant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lines (
    line_id TEXT PRIMARY KEY,
    plant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    line_type TEXT NOT NULL CHECK (line_type IN ('MACHINING', 'ASSEMBLY', 'PACKAGING')),
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);

CREATE TABLE IF NOT EXISTS machines (
    machine_id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL,
    name TEXT NOT NULL,
    sequence_order INTEGER NOT NULL,
    criticality TEXT NOT NULL CHECK (criticality IN ('HIGH', 'MEDIUM', 'LOW')),
    FOREIGN KEY (line_id) REFERENCES lines(line_id)
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    family TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shifts (
    shift_id TEXT PRIMARY KEY,
    plant_id TEXT NOT NULL,
    shift_code TEXT NOT NULL CHECK (shift_code IN ('SHIFT_A', 'SHIFT_B', 'SHIFT_C')),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    planned_break_sec INTEGER NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);

CREATE TABLE IF NOT EXISTS machine_product_standards (
    standard_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    ideal_cycle_time_sec REAL NOT NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS downtime_reasons (
    reason_code TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('PLANNED', 'UNPLANNED', 'CHANGEOVER', 'LINE_STOP')),
    description TEXT NOT NULL,
    affects_availability INTEGER NOT NULL CHECK (affects_availability IN (0, 1))
);

CREATE TABLE IF NOT EXISTS production_orders (
    order_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    target_quantity INTEGER NOT NULL,
    scheduled_start TEXT NOT NULL,
    scheduled_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PLANNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    planned_cycle_time_sec REAL NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (line_id) REFERENCES lines(line_id)
);

CREATE TABLE IF NOT EXISTS state_events (
    event_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    order_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('RUNNING', 'UNPLANNED_DOWNTIME', 'PLANNED_DOWNTIME', 'CHANGEOVER', 'STARVED', 'BLOCKED', 'OFF')),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    reason_code TEXT,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id),
    FOREIGN KEY (order_id) REFERENCES production_orders(order_id)
);

CREATE TABLE IF NOT EXISTS production_counts (
    count_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    count_delta INTEGER NOT NULL,
    cumulative_count INTEGER NOT NULL,
    is_correction INTEGER NOT NULL CHECK (is_correction IN (0, 1)),
    correction_ref_id TEXT,
    FOREIGN KEY (order_id) REFERENCES production_orders(order_id),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id),
    FOREIGN KEY (correction_ref_id) REFERENCES production_counts(count_id)
);

CREATE TABLE IF NOT EXISTS quality_inspections (
    inspection_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    inspection_type TEXT NOT NULL CHECK (inspection_type IN ('FIRST_PIECE', 'IN_PROCESS', 'FINAL')),
    inspected_qty INTEGER NOT NULL,
    passed_qty INTEGER NOT NULL,
    scrap_qty INTEGER NOT NULL,
    rework_qty INTEGER NOT NULL,
    defect_code TEXT CHECK (defect_code IS NULL OR defect_code = '' OR defect_code IN ('DIMENSIONAL_OUT_OF_SPEC', 'SURFACE_SCRATCH', 'BURR_CONTAMINATION', 'MATERIAL_VOIDS', 'PACKAGING_DAMAGE', 'TOOL_MARKING')),
    FOREIGN KEY (order_id) REFERENCES production_orders(order_id),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id)
);

CREATE TABLE IF NOT EXISTS oee_aggregates (
    aggregate_id TEXT PRIMARY KEY,
    shift_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    planned_prod_time_sec INTEGER NOT NULL,
    operating_time_sec INTEGER NOT NULL,
    unplanned_downtime_sec INTEGER NOT NULL,
    planned_downtime_sec INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    good_count INTEGER NOT NULL,
    scrap_count INTEGER NOT NULL,
    rework_count INTEGER NOT NULL,
    ideal_cycle_time_sec REAL NOT NULL,
    availability REAL NOT NULL,
    performance REAL NOT NULL,
    quality REAL NOT NULL,
    oee REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('CLEAN', 'FLAGGED', 'ANOMALOUS')),
    exception_count INTEGER NOT NULL,
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (line_id) REFERENCES lines(line_id)
);
"""


class DatasetExporter:
    """Exports raw manufacturing CSV datasets into structured JSON and SQL bundles."""

    def __init__(self, input_dir: Path, output_dir: Optional[Path] = None) -> None:
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir) if output_dir else (self.input_dir / "exports")

    def _discover_tables(self) -> List[Tuple[str, Path]]:
        """Identify available domain tables in dependency order, strictly ignoring ground truth."""
        tables = []
        for tbl in DOMAIN_TABLE_ORDER:
            csv_path = self.input_dir / f"{tbl}.csv"
            if csv_path.exists():
                tables.append((tbl, csv_path))
        return tables

    def export_all(self, formats: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute requested exports (json, sql) and write to output_dir."""
        if formats is None:
            formats = ["json", "sql"]

        fmt_set = {f.strip().lower() for f in formats}
        tables = self._discover_tables()
        manifest: Dict[str, Any] = {
            "input_dir": str(self.input_dir.resolve()),
            "output_dir": str(self.output_dir.resolve()),
            "formats": sorted(list(fmt_set)),
            "tables": [t[0] for t in tables],
            "files_generated": [],
        }

        self.output_dir.mkdir(parents=True, exist_ok=True)

        if "json" in fmt_set:
            json_dir = self.output_dir / "json"
            json_dir.mkdir(parents=True, exist_ok=True)
            for tbl_name, csv_path in tables:
                df = pl.read_csv(csv_path)
                records = df.to_dicts()
                # Clean null representations
                cleaned_records = []
                for rec in records:
                    cleaned = {}
                    for k, v in rec.items():
                        if v == "":
                            cleaned[k] = None
                        elif isinstance(v, str) and v.lower() == "true":
                            cleaned[k] = True
                        elif isinstance(v, str) and v.lower() == "false":
                            cleaned[k] = False
                        else:
                            cleaned[k] = v
                    cleaned_records.append(cleaned)

                out_json = json_dir / f"{tbl_name}.json"
                with open(out_json, "w", encoding="utf-8") as f:
                    json.dump(cleaned_records, f, indent=2)
                manifest["files_generated"].append(str(out_json))

        if "sql" in fmt_set:
            sql_dir = self.output_dir / "sql"
            sql_dir.mkdir(parents=True, exist_ok=True)

            schema_path = sql_dir / "schema.sql"
            with open(schema_path, "w", encoding="utf-8") as f:
                f.write(SQL_SCHEMA_DDL)
            manifest["files_generated"].append(str(schema_path))

            # Also write schema.sql directly in output_dir for convenience
            root_schema = self.output_dir / "schema.sql"
            with open(root_schema, "w", encoding="utf-8") as f:
                f.write(SQL_SCHEMA_DDL)

            # Generate seed.sql with batched INSERT statements
            seed_path = sql_dir / "seed.sql"
            with open(seed_path, "w", encoding="utf-8") as f:
                f.write("-- YottaFlex Manufacturing Telemetry Seed Data\n")
                f.write("PRAGMA foreign_keys = OFF;\nBEGIN TRANSACTION;\n\n")

                for tbl_name, csv_path in tables:
                    df = pl.read_csv(csv_path)
                    if len(df) == 0:
                        continue
                    cols = df.columns
                    f.write(f"-- Table: {tbl_name} ({len(df):,} records)\n")

                    batch_size = 500
                    for chunk_idx in range(0, len(df), batch_size):
                        chunk = df.slice(chunk_idx, batch_size)
                        f.write(f"INSERT INTO {tbl_name} ({', '.join(cols)}) VALUES\n")
                        rows_sql = []
                        for row in chunk.iter_rows():
                            vals_sql = []
                            for v in row:
                                if v is None or v == "":
                                    vals_sql.append("NULL")
                                elif isinstance(v, bool):
                                    vals_sql.append("1" if v else "0")
                                elif isinstance(v, (int, float)):
                                    vals_sql.append(str(v))
                                else:
                                    s_val = str(v)
                                    if s_val.lower() == "true":
                                        vals_sql.append("1")
                                    elif s_val.lower() == "false":
                                        vals_sql.append("0")
                                    else:
                                        escaped = s_val.replace("'", "''")
                                        vals_sql.append(f"'{escaped}'")
                            rows_sql.append(f"({', '.join(vals_sql)})")
                        f.write(",\n".join(rows_sql) + ";\n")
                    f.write("\n")

                f.write("COMMIT;\nPRAGMA foreign_keys = ON;\n")
            manifest["files_generated"].append(str(seed_path))

            # Also write seed.sql directly in output_dir
            root_seed = self.output_dir / "seed.sql"
            with open(root_seed, "w", encoding="utf-8") as f:
                with open(seed_path, "r", encoding="utf-8") as sf:
                    f.write(sf.read())

        return manifest
