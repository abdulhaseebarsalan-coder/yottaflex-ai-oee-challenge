"""Configuration classes for the synthetic data generator profiles."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class GeneratorProfileConfig:
    """Parameters defining a generation run scale."""
    profile_name: str
    num_plants: int
    num_lines: int
    machines_per_line: int
    num_products: int
    num_days: int
    start_date: datetime
    shifts_per_day: int = 3
    shift_duration_hours: int = 8
    planned_break_minutes: int = 60
    anomalies_per_type: int = 1
    # Telemetry pulse frequency in seconds
    pulse_interval_sec: int = 300  # 5 minutes


# Starter Profile: fast iteration, ~3 days, 2 lines, 6 machines, 4 products
STARTER_CONFIG = GeneratorProfileConfig(
    profile_name="starter",
    num_plants=1,
    num_lines=2,
    machines_per_line=3,
    num_products=4,
    num_days=3,
    start_date=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    shifts_per_day=3,
    shift_duration_hours=8,
    planned_break_minutes=60,
    anomalies_per_type=1,  # 1 of each of the 5 edge cases = 5 total anomalies
    pulse_interval_sec=300,
)

# Full Profile: challenge scale, 90 days, 5 lines, 30 machines, 20 products
FULL_CONFIG = GeneratorProfileConfig(
    profile_name="full",
    num_plants=1,
    num_lines=5,
    machines_per_line=6,
    num_products=20,
    num_days=90,
    start_date=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    shifts_per_day=3,
    shift_duration_hours=8,
    planned_break_minutes=60,
    anomalies_per_type=10,  # 10 of each of the 5 edge cases = 50 total anomalies
    pulse_interval_sec=180,  # 3 minutes for high density
)


def get_profile_config(profile: str) -> GeneratorProfileConfig:
    """Retrieve profile configuration by name."""
    p = profile.strip().lower()
    if p == "starter":
        return STARTER_CONFIG
    elif p == "full":
        return FULL_CONFIG
    raise ValueError(f"Unknown generation profile: '{profile}'. Must be 'starter' or 'full'.")
