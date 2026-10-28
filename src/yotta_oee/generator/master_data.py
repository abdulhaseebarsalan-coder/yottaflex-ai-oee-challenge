"""Master data generation for Plant, Lines, Machines, Products, Shifts, Standards, and Downtime Reasons."""

from datetime import datetime, timedelta, timezone
import hashlib
import random
from typing import List, Tuple

from yotta_oee.domain import (
    DowntimeCategory,
    DowntimeReason,
    EntityStatus,
    Line,
    LineType,
    Machine,
    MachineCriticality,
    MachineProductStandard,
    Plant,
    Product,
    Shift,
    ShiftCode,
)
from yotta_oee.generator.config import GeneratorProfileConfig

# Standard Downtime Taxonomy
DOWNTIME_TAXONOMY: List[DowntimeReason] = [
    DowntimeReason(
        reason_code="DT-PLANNED-BREAK",
        category=DowntimeCategory.PLANNED,
        description="Scheduled Shift Rest / Meal Break",
        affects_availability=False,
    ),
    DowntimeReason(
        reason_code="DT-PLANNED-MAINT",
        category=DowntimeCategory.PLANNED,
        description="Scheduled Autonomous / Preventative Maintenance",
        affects_availability=False,
    ),
    DowntimeReason(
        reason_code="DT-UNPLANNED-JAM",
        category=DowntimeCategory.UNPLANNED,
        description="Mechanical Jam / Material Feed Obstruction",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-UNPLANNED-ELEC",
        category=DowntimeCategory.UNPLANNED,
        description="Electrical Component / Sensor Signal Failure",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-UNPLANNED-TOOL",
        category=DowntimeCategory.UNPLANNED,
        description="Spindle / Cutting Tool Fracture or Excessive Wear",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-UNPLANNED-OP",
        category=DowntimeCategory.UNPLANNED,
        description="Unscheduled Operator Absence or Safety Interlock Trip",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-UNPLANNED-MICRO",
        category=DowntimeCategory.UNPLANNED,
        description="Transient Equipment Micro-Stop / Minor Feed Jam (< 5 min)",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-CHANGEOVER-SETUP",
        category=DowntimeCategory.CHANGEOVER,
        description="Product Die / Fixture Swap and Tooling Calibration",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-STOP-STARVED",
        category=DowntimeCategory.LINE_STOP,
        description="Material Starvation from Upstream Feeder Buffer",
        affects_availability=True,
    ),
    DowntimeReason(
        reason_code="DT-STOP-BLOCKED",
        category=DowntimeCategory.LINE_STOP,
        description="Downstream Line Blockage / Output Buffer Saturation",
        affects_availability=True,
    ),
]

PRODUCT_FAMILIES = ["AEROSPACE", "AUTOMOTIVE", "MEDICAL", "ENERGY", "PRECISION_OPTICS"]
LINE_TYPES = [LineType.MACHINING, LineType.ASSEMBLY, LineType.PACKAGING]


class MasterDataGenerator:
    """Deterministic generator for all manufacturing master entities."""

    def __init__(self, config: GeneratorProfileConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng

    def generate_plants(self) -> List[Plant]:
        """Generate Plant records."""
        plants = []
        for i in range(1, self.config.num_plants + 1):
            plant_id = f"PLANT-{i:02d}"
            plants.append(
                Plant(
                    plant_id=plant_id,
                    name=f"Apex Advanced Manufacturing Facility {i}",
                    timezone="UTC",
                    country="USA",
                    effective_from=self.config.start_date,
                    effective_to=None,
                    status=EntityStatus.ACTIVE,
                )
            )
        return plants

    def generate_lines(self, plants: List[Plant]) -> List[Line]:
        """Generate Line records associated with parent plants."""
        lines = []
        primary_plant = plants[0]
        for i in range(1, self.config.num_lines + 1):
            line_id = f"LINE-{i:02d}"
            line_type = LINE_TYPES[(i - 1) % len(LINE_TYPES)]
            lines.append(
                Line(
                    line_id=line_id,
                    plant_id=primary_plant.plant_id,
                    name=f"Cell {i:02d} ({line_type.value.capitalize()})",
                    line_type=line_type,
                    effective_from=self.config.start_date,
                    effective_to=None,
                    status=EntityStatus.ACTIVE,
                )
            )
        return lines

    def generate_machines(self, lines: List[Line]) -> List[Machine]:
        """Generate Machine stations for each line."""
        machines = []
        is_full = getattr(self.config, "num_days", 3) >= 30
        for line in lines:
            for seq in range(1, self.config.machines_per_line + 1):
                machine_id = f"MCH-{line.line_id}-{seq:02d}"
                crit = MachineCriticality.HIGH if seq == 1 else (
                    MachineCriticality.MEDIUM if seq < self.config.machines_per_line else MachineCriticality.LOW
                )
                # In full profile, mark MCH-LINE-05-06 with MAINTENANCE lifecycle status
                if is_full and machine_id == "MCH-LINE-05-06":
                    m_status = EntityStatus.MAINTENANCE
                else:
                    m_status = EntityStatus.ACTIVE

                machines.append(
                    Machine(
                        machine_id=machine_id,
                        line_id=line.line_id,
                        name=f"Station {seq:02d} ({line.name})",
                        sequence_order=seq,
                        criticality=crit,
                        effective_from=self.config.start_date,
                        effective_to=None,
                        status=m_status,
                    )
                )
        return machines

    def generate_products(self) -> List[Product]:
        """Generate manufactured product master catalog."""
        products = []
        is_full = getattr(self.config, "num_days", 3) >= 30
        for i in range(1, self.config.num_products + 1):
            prod_id = f"PRD-{i:04d}"
            family = PRODUCT_FAMILIES[(i - 1) % len(PRODUCT_FAMILIES)]
            sku = f"SKU-{family[:3]}-{i:04d}"

            eff_from = self.config.start_date
            eff_to = None
            status = EntityStatus.ACTIVE

            # Minimal realistic lifecycle in full profile:
            # 1. PRD-0020 introduced mid-horizon on Day 31 (2026-02-01)
            # 2. PRD-0004 retired mid-horizon on Day 45 (2026-02-15)
            if is_full:
                if prod_id == "PRD-0020":
                    eff_from = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
                    status = EntityStatus.ACTIVE
                elif prod_id == "PRD-0004":
                    eff_from = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                    eff_to = datetime(2026, 2, 15, 23, 59, 59, tzinfo=timezone.utc)
                    status = EntityStatus.RETIRED

            products.append(
                Product(
                    product_id=prod_id,
                    sku=sku,
                    name=f"{family.capitalize()} Precision Component {i:02d}",
                    family=family,
                    effective_from=eff_from,
                    effective_to=eff_to,
                    status=status,
                )
            )
        return products

    def generate_shifts(self, plant: Plant) -> List[Shift]:
        """Generate 8-hour shift calendar across the configured number of days."""
        shifts = []
        current_date = self.config.start_date.date()
        shift_specs = [
            ("A", ShiftCode.SHIFT_A, 6, 14),   # 06:00 - 14:00
            ("B", ShiftCode.SHIFT_B, 14, 22),  # 14:00 - 22:00
            ("C", ShiftCode.SHIFT_C, 22, 6),   # 22:00 - 06:00 next day
        ]

        for day_offset in range(self.config.num_days):
            day = current_date + timedelta(days=day_offset)
            for code_letter, code_enum, start_h, end_h in shift_specs:
                shift_id = f"SHIFT-{day.isoformat()}-{code_letter}"
                start_dt = datetime(day.year, day.month, day.day, start_h, 0, 0, tzinfo=timezone.utc)
                if end_h < start_h:
                    end_dt = start_dt + timedelta(hours=8)
                else:
                    end_dt = datetime(day.year, day.month, day.day, end_h, 0, 0, tzinfo=timezone.utc)

                shifts.append(
                    Shift(
                        shift_id=shift_id,
                        plant_id=plant.plant_id,
                        shift_code=code_enum,
                        start_time=start_dt,
                        end_time=end_dt,
                        planned_break_sec=self.config.planned_break_minutes * 60,
                    )
                )
        return shifts

    def generate_standards(
        self, machines: List[Machine], products: List[Product]
    ) -> List[MachineProductStandard]:
        """Generate deterministic ideal cycle times for each (Machine, Product) pair."""
        standards = []
        for machine in machines:
            for product in products:
                std_id = f"STD-{machine.machine_id}-{product.product_id}"
                # Derive cross-process deterministic baseline from IDs using sha256
                raw_hash = hashlib.sha256(f"{machine.machine_id}:{product.product_id}".encode("utf-8")).hexdigest()
                hash_val = int(raw_hash[:8], 16) % 1000
                # Realistic takt time between 4.0s and 25.0s
                base_takt = 6.0 + (hash_val % 18) + (hash_val % 10) * 0.1

                # Standards inherit the effective dates of the product & machine
                eff_from = max(machine.effective_from, product.effective_from)
                eff_to = product.effective_to or machine.effective_to
                std_status = product.status if product.status == EntityStatus.RETIRED else machine.status

                standards.append(
                    MachineProductStandard(
                        standard_id=std_id,
                        machine_id=machine.machine_id,
                        product_id=product.product_id,
                        ideal_cycle_time_sec=round(base_takt, 3),
                        effective_from=eff_from,
                        effective_to=eff_to,
                        status=std_status,
                    )
                )
        return standards

    def get_downtime_reasons(self) -> List[DowntimeReason]:
        """Return standard downtime reasons taxonomy."""
        return DOWNTIME_TAXONOMY
