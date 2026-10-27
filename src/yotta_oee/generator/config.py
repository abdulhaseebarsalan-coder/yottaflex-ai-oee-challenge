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
    # Explicit telemetry and state density profile parameters
    target_events_per_shift_machine: int = 12
    pulse_interval_sec: int = 300
    qc_samples_per_shift_machine: int = 2

    @property
    def total_machines(self) -> int:
        """Total machines across all lines."""
        return self.num_lines * self.machines_per_line

    @property
    def total_shifts(self) -> int:
        """Total scheduled shifts across the calendar horizon."""
        return self.num_days * self.shifts_per_day

    @property
    def total_machine_shifts(self) -> int:
        """Total Machine x Shift operational windows."""
        return self.total_machines * self.total_shifts

    def compute_expected_state_events(self) -> int:
        """Calculate estimated total state events generated under this profile."""
        return self.total_machine_shifts * self.target_events_per_shift_machine

    def compute_expected_count_records(self) -> int:
        """Calculate estimated total production count pulse records."""
        net_operating_sec = (self.shift_duration_hours * 3600) - (self.planned_break_minutes * 60)
        pulses_per_machine_shift = net_operating_sec // self.pulse_interval_sec
        return self.total_machine_shifts * pulses_per_machine_shift

    def compute_expected_qc_records(self) -> int:
        """Calculate estimated total quality inspection records."""
        return self.total_machine_shifts * self.qc_samples_per_shift_machine

    def compute_expected_count_plus_qc(self) -> int:
        """Calculate combined telemetry volume (counts + QC samples)."""
        return self.compute_expected_count_records() + self.compute_expected_qc_records()

    def compute_analytic_counts(self) -> dict[str, int]:
        """Compute expected analytic row counts across all domain entities."""
        return {
            "plants": self.num_plants,
            "lines": self.num_lines,
            "machines": self.total_machines,
            "products": self.num_products,
            "shifts": self.total_shifts,
            "machine_product_standards": self.total_machines * self.num_products,
            "downtime_reasons": 9,
            "state_events": self.compute_expected_state_events(),
            "production_counts": self.compute_expected_count_records(),
            "quality_inspections": self.compute_expected_qc_records(),
            "count_plus_qc": self.compute_expected_count_plus_qc(),
            "ground_truth_anomalies": self.anomalies_per_type * 5,
        }


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
    target_events_per_shift_machine=12,
    pulse_interval_sec=300,
    qc_samples_per_shift_machine=2,
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
    target_events_per_shift_machine=15,  # 8,100 * 15 = 121,500 state events (>= 100k)
    pulse_interval_sec=310,              # 8,100 * ~71.6 = 579,900 counts
    qc_samples_per_shift_machine=2,      # 8,100 * 2 = 16,200 QC samples -> 596,100 count+QC (~500k-600k)
)


def get_profile_config(profile: str) -> GeneratorProfileConfig:
    """Retrieve profile configuration by name."""
    p = profile.strip().lower()
    if p == "starter":
        return STARTER_CONFIG
    elif p == "full":
        return FULL_CONFIG
    raise ValueError(f"Unknown generation profile: '{profile}'. Must be 'starter' or 'full'.")

