"""Telemetry generator for production counts and quality inspections."""

from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional, Tuple

from yotta_oee.domain import (
    InspectionType,
    MachineProductStandard,
    MachineState,
    ProductionCount,
    ProductionOrder,
    QualityInspection,
    StateEvent,
)
from yotta_oee.generator.config import GeneratorProfileConfig


class TelemetryGenerator:
    """Generates discrete production counts and quality control inspections."""

    def __init__(self, config: GeneratorProfileConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng

    def generate_counts_and_inspections(
        self,
        state_events: List[StateEvent],
        orders: List[ProductionOrder],
        standards: List[MachineProductStandard],
    ) -> Tuple[List[ProductionCount], List[QualityInspection]]:
        """Synthesize production count increments and quality inspection samples."""
        counts: List[ProductionCount] = []
        inspections: List[QualityInspection] = []

        # Index standards by (machine_id, product_id)
        std_lookup: Dict[Tuple[str, str], float] = {
            (s.machine_id, s.product_id): s.ideal_cycle_time_sec for s in standards
        }
        # Index orders by order_id
        order_lookup: Dict[str, ProductionOrder] = {o.order_id: o for o in orders}

        # Track cumulative counts per (order_id, machine_id)
        cumulative_counts: Dict[Tuple[str, str], int] = {}
        count_seq_counters: Dict[str, int] = {}
        qc_seq_counter = 1

        # Track quality inspections already created per order/shift to avoid flooding
        inspected_orders_shifts: set[Tuple[str, str]] = set()

        # Filter only RUNNING events with an assigned order
        running_events = [
            e for e in state_events
            if e.state == MachineState.RUNNING and e.order_id
        ]
        running_events.sort(key=lambda e: e.start_time)

        year = self.config.start_date.year
        pulse_interval = timedelta(seconds=self.config.pulse_interval_sec)

        for event in running_events:
            order = order_lookup.get(event.order_id)
            if not order:
                continue

            order_key = (event.order_id, event.machine_id)
            cum_count = cumulative_counts.get(order_key, 0)
            seq_num = count_seq_counters.get(event.order_id, 1)

            ict = std_lookup.get((event.machine_id, order.product_id), 10.0)

            curr_pulse_time = event.start_time + pulse_interval
            prev_count_id: Optional[str] = None

            while curr_pulse_time <= event.end_time:
                # Realistic speed factor with micro-stops: 85% to 98% nominal
                speed_factor = self.rng.uniform(0.85, 0.98)
                pulse_duration_sec = self.config.pulse_interval_sec

                # Delta count during this pulse
                delta = max(1, int(pulse_duration_sec / (ict / speed_factor)))
                cum_count += delta

                count_id = f"CNT-{event.order_id}-{seq_num:06d}"
                seq_num += 1

                counts.append(
                    ProductionCount(
                        count_id=count_id,
                        order_id=event.order_id,
                        machine_id=event.machine_id,
                        shift_id=event.shift_id,
                        timestamp=curr_pulse_time,
                        count_delta=delta,
                        cumulative_count=cum_count,
                        is_correction=False,
                        correction_ref_id=None,
                    )
                )

                # Occasionally inject a legitimate audit correction event (0.5% chance)
                if self.rng.random() < 0.005 and cum_count > 50:
                    corr_delta = -self.rng.randint(2, 8)
                    cum_count += corr_delta
                    corr_count_id = f"CNT-{event.order_id}-{seq_num:06d}"
                    seq_num += 1

                    counts.append(
                        ProductionCount(
                            count_id=corr_count_id,
                            order_id=event.order_id,
                            machine_id=event.machine_id,
                            shift_id=event.shift_id,
                            timestamp=curr_pulse_time + timedelta(seconds=5),
                            count_delta=corr_delta,
                            cumulative_count=cum_count,
                            is_correction=True,
                            correction_ref_id=count_id,
                        )
                    )

                prev_count_id = count_id
                curr_pulse_time += pulse_interval

            # Update state counters
            cumulative_counts[order_key] = cum_count
            count_seq_counters[event.order_id] = seq_num

            # Trigger quality inspections once or twice per shift window
            shift_order_key = (event.shift_id, event.order_id, event.machine_id)
            if shift_order_key not in inspected_orders_shifts and cum_count > 30:
                inspected_orders_shifts.add(shift_order_key)

                # First piece inspection early in order, or in-process
                itype = InspectionType.FIRST_PIECE if cum_count < 100 else InspectionType.IN_PROCESS
                sample_size = 20 if itype == InspectionType.FIRST_PIECE else self.rng.choice([30, 50])

                # Typical discrete yield: 96% - 99%
                scrap = self.rng.choices([0, 1, 2], weights=[0.80, 0.15, 0.05])[0]
                rework = self.rng.choices([0, 1], weights=[0.90, 0.10])[0]
                passed = sample_size - (scrap + rework)

                qc_id = f"QC-{year}-{qc_seq_counter:06d}"
                qc_seq_counter += 1

                inspections.append(
                    QualityInspection(
                        inspection_id=qc_id,
                        order_id=event.order_id,
                        machine_id=event.machine_id,
                        shift_id=event.shift_id,
                        timestamp=event.start_time + timedelta(minutes=45),
                        inspection_type=itype,
                        inspected_qty=sample_size,
                        passed_qty=passed,
                        scrap_qty=scrap,
                        rework_qty=rework,
                        defect_code="DT-UNPLANNED-JAM" if scrap > 0 else None,
                    )
                )

        return counts, inspections
