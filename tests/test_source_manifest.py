"""Tests for source_manifest.json verifying provenance, standards, and licensing."""

import json
from pathlib import Path


def test_source_manifest_structure_and_provenance():
    manifest_path = Path("source_manifest.json")
    assert manifest_path.exists(), "source_manifest.json must exist in project root"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["data_provenance"]["external_data_used"] is False
    assert data["data_provenance"]["is_synthetic"] is True
    assert len(data["standards_and_references"]) >= 3
    assert "licensing" in data
    assert data["licensing"]["software_license"] == "MIT License"
