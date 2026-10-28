"""Telemetry generator for production counts and quality inspections."""

from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional, Tuple

from yotta_oee.domain import (
    DefectCode,
    InspectionType,
    Machine,
    MachineCriticality,
    MachineProductStandard,
    MachineState,
    OrderStatus,
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
        machines: Optional[List[Machine]] = None,
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

        # Index machine criticalities
        machine_crit: Dict[str, MachineCriticality] = {}
        if machines:
            machine_crit = {m.machine_id: m.criticality for m in machines}

        # Index stoppage events per machine for post-changeover and post-breakdown detection
        stoppages_by_mch: Dict[str, List[Tuple[datetime, datetime, MachineState]]] = {}
        for ev in state_events:
            if ev.state in (MachineState.CHANGEOVER, MachineState.UNPLANNED_DOWNTIME):
                stoppages_by_mch.setdefault(ev.machine_id, []).append((ev.start_time, ev.end_time, ev.state))

        # Track quality inspections already created per shift/machine
        inspected_orders_shifts: Dict[Tuple[str, str], int] = {}

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

            is_cancelled = (order.status == OrderStatus.CANCELLED)
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

                if not is_cancelled:
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
                # Must have at least 5 seconds remaining in RUNNING event so correction strictly succeeds referenced count
                if self.rng.random() < 0.005 and cum_count > 50 and curr_pulse_time + timedelta(seconds=5) < event.end_time:
                    corr_delta = -self.rng.randint(2, 8)
                    cum_count += corr_delta
                    corr_count_id = f"CNT-{event.order_id}-{seq_num:06d}"
                    seq_num += 1

                    if not is_cancelled:
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

            # Trigger quality inspections per shift window according to qc_samples_per_shift_machine
            shift_mch_key = (event.shift_id, event.machine_id)
            curr_qc = inspected_orders_shifts.get(shift_mch_key, 0)
            target_qc = self.config.qc_samples_per_shift_machine

            if curr_qc < target_qc and cum_count > 25:
                trigger = False
                if curr_qc == 0:
                    trigger = True
                    itype = InspectionType.FIRST_PIECE
                    sample_size = 20
                    sample_offset = timedelta(minutes=min(30, max(5, event.duration_sec // 120)))
                elif curr_qc == 1 and cum_count > 80:
                    trigger = True
                    itype = InspectionType.IN_PROCESS
                    sample_size = self.rng.choice([30, 50])
                    sample_offset = timedelta(minutes=min(45, max(10, event.duration_sec // 120)))

                if trigger:
                    inspected_orders_shifts[shift_mch_key] = curr_qc + 1
                    qc_time = event.start_time + sample_offset

                    # Deterministic Scrap & Rework Rule:
                    # 1. Product Base Defect Rate (calibrated per product 1.5% - 3.3%)
                    prod_id = order.product_id
                    p_num = int(prod_id.split("-")[1]) if "-" in prod_id else 1
                    base_defect_rate = 0.015 + ((p_num * 7) % 10) * 0.002

                    # 2. Machine Criticality Factor (HIGH = 1.25x, MEDIUM = 1.00x, LOW = 0.80x)
                    crit = machine_crit.get(event.machine_id, MachineCriticality.MEDIUM)
                    if crit == MachineCriticality.HIGH:
                        crit_factor = 1.25
                    elif crit == MachineCriticality.LOW:
                        crit_factor = 0.80
                    else:
                        crit_factor = 1.00

                    # 3. Operational Multiplier: 2.5x within 60m of CHANGEOVER, 2.0x within 60m of BREAKDOWN
                    multiplier = 1.0
                    m_stops = stoppages_by_mch.get(event.machine_id, [])
                    recent_stops = [s for s in m_stops if s[1] <= qc_time]
                    if recent_stops:
                        last_stop = max(recent_stops, key=lambda s: s[1])
                        time_since_stop_sec = (qc_time - last_stop[1]).total_seconds()
                        if time_since_stop_sec <= 3600:
                            if last_stop[2] == MachineState.CHANGEOVER:
                                multiplier = 2.5
                            elif last_stop[2] == MachineState.UNPLANNED_DOWNTIME:
                                multiplier = 2.0

                    effective_defect_rate = min(0.25, base_defect_rate * crit_factor * multiplier)
                    p_scrap = 0.65 * effective_defect_rate
                    p_rework = 0.35 * effective_defect_rate

                    # Deterministic binomial-like draw for scrap and rework
                    scrap = 0
                    rework = 0
                    for _ in range(sample_size):
                        roll = self.rng.random()
                        if roll < p_scrap:
                            scrap += 1
                        elif roll < p_scrap + p_rework:
                            rework += 1

                    passed = sample_size - (scrap + rework)
                    qc_id = f"QC-{year}-{qc_seq_counter:06d}"
                    qc_seq_counter += 1

                    defect_code = None
                    if scrap > 0 or rework > 0:
                        defect_code = self.rng.choice(list(DefectCode))

                    if not is_cancelled:
                        inspections.append(
                            QualityInspection(
                                inspection_id=qc_id,
                                order_id=event.order_id,
                                machine_id=event.machine_id,
                                shift_id=event.shift_id,
                                timestamp=qc_time,
                                inspection_type=itype,
                                inspected_qty=sample_size,
                                passed_qty=passed,
                                scrap_qty=scrap,
                                rework_qty=rework,
                                defect_code=defect_code,
                            )
                        )


        return counts, inspections
