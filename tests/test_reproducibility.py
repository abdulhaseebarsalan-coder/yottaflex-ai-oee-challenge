"""Tests for deterministic reproducibility and cryptographic checksum verification."""

from pathlib import Path
import pytest

from yotta_oee.generator.engine import DataGenerationEngine


class TestReproducibility:
    def test_identical_seed_produces_identical_checksums(self, tmp_path: Path):
        """Run starter generation twice with same seed; assert bitwise-identical outputs."""
        dir1 = tmp_path / "run_seed_42_a"
        dir2 = tmp_path / "run_seed_42_b"

        engine1 = DataGenerationEngine(profile="starter", seed=20261022, output_dir=dir1)
        res1 = engine1.generate_and_export()

        engine2 = DataGenerationEngine(profile="starter", seed=20261022, output_dir=dir2)
        res2 = engine2.generate_and_export()

        # Row counts must match exactly
        assert res1.row_counts == res2.row_counts

        # Checksums must match bitwise on all files
        checksums1 = res1.manifest["checksums_sha256"]
        checksums2 = res2.manifest["checksums_sha256"]

        for filename, hash1 in checksums1.items():
            hash2 = checksums2.get(filename)
            assert hash1 == hash2, f"SHA-256 mismatch on {filename}: {hash1} != {hash2}"

        # Manifest itself must be bitwise identical across runs (timestamps moved to run_metadata.json)
        manifest1_text = (dir1 / "manifest.json").read_text(encoding="utf-8")
        manifest2_text = (dir2 / "manifest.json").read_text(encoding="utf-8")
        assert manifest1_text == manifest2_text, "manifest.json differed across runs with identical seed!"
        assert (dir1 / "run_metadata.json").exists()
        assert (dir2 / "run_metadata.json").exists()


    def test_different_seeds_produce_different_data(self, tmp_path: Path):
        """Run starter generation with two distinct seeds; assert distinct telemetry."""
        dir1 = tmp_path / "run_seed_100"
        dir2 = tmp_path / "run_seed_200"

        engine1 = DataGenerationEngine(profile="starter", seed=100, output_dir=dir1)
        res1 = engine1.generate_and_export()

        engine2 = DataGenerationEngine(profile="starter", seed=200, output_dir=dir2)
        res2 = engine2.generate_and_export()

        # Telemetry counts and events should differ
        hash1 = res1.manifest["checksums_sha256"]["state_events.csv"]
        hash2 = res2.manifest["checksums_sha256"]["state_events.csv"]
        assert hash1 != hash2
