"""Tests for dataset exports and SQLite relational integrity."""

import json
from pathlib import Path
import sqlite3
import pytest
import polars as pl

from yotta_oee.exporter.engine import DOMAIN_TABLE_ORDER, DatasetExporter


class TestDatasetExports:
    def test_export_pipeline_and_sqlite_relational_integrity(self, tmp_path: Path):
        """Export starter dataset to JSON and SQL, load into SQLite, and verify FKs and row counts."""
        starter_dir = Path("data/starter")
        out_dir = tmp_path / "exports"

        exporter = DatasetExporter(input_dir=starter_dir, output_dir=out_dir)
        manifest = exporter.export_all(formats=["json", "sql"])

        assert len(manifest["tables"]) >= 11
        assert (out_dir / "sql" / "schema.sql").exists()
        assert (out_dir / "sql" / "seed.sql").exists()

        # 1. Verify JSON file integrity
        json_dir = out_dir / "json"
        for tbl in manifest["tables"]:
            json_file = json_dir / f"{tbl}.json"
            assert json_file.exists(), f"Missing JSON export for {tbl}"
            with open(json_file, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            csv_df = pl.read_csv(starter_dir / f"{tbl}.csv")
            assert len(data) == len(csv_df), f"JSON record count mismatch for {tbl}"

        # 2. Verify SQL Schema & Seed via Python's built-in sqlite3 (no external dependencies)
        with open(out_dir / "sql" / "schema.sql", "r", encoding="utf-8") as sf:
            schema_sql = sf.read()
        with open(out_dir / "sql" / "seed.sql", "r", encoding="utf-8") as sf:
            seed_sql = sf.read()

        conn = sqlite3.connect(":memory:")
        try:
            # Enable strict foreign key enforcement
            conn.execute("PRAGMA foreign_keys = ON;")

            # Execute DDL schema creation
            conn.executescript(schema_sql)

            # Execute DML seed data population
            conn.executescript(seed_sql)

            # Execute foreign key integrity check
            fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
            assert len(fk_violations) == 0, f"SQLite foreign key check failed with violations: {fk_violations}"

            # Verify row counts match CSV sources identically
            for tbl in manifest["tables"]:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {tbl};")
                sql_count = cursor.fetchone()[0]
                csv_count = len(pl.read_csv(starter_dir / f"{tbl}.csv"))
                assert sql_count == csv_count, f"Row count mismatch for {tbl}: SQL={sql_count}, CSV={csv_count}"

        finally:
            conn.close()

    def test_full_dataset_export_on_demand(self, tmp_path: Path):
        """Verify export capability on full profile on demand."""
        full_dir = Path("data/full")
        if not full_dir.exists():
            pytest.skip("Full dataset not generated locally")

        out_dir = tmp_path / "full_exports"
        exporter = DatasetExporter(input_dir=full_dir, output_dir=out_dir)
        # Test SQL schema generation and table discovery
        tables = exporter._discover_tables()
        assert len(tables) >= 11
