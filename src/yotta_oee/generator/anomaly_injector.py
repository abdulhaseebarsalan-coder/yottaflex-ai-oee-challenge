"""Deterministic anomaly injection engine for required challenge edge cases.

Injected Edge Cases:
- EC-01: OVERLAPPING_STATE (overlapping machine state events)
- EC-02: UNEXPLAINED_COUNT_DROP (cumulative count decreases without correction event)
- EC-03: SCRAP_EXCEEDS_TOTAL (scrap quantity > total inspected quantity)
- EC-04: INVALID_CYCLE_TIME (order-of-magnitude erroneous cycle time standard)
- EC-05: BREAKDOWN_OVERLAPS_BREAK (unplanned downtime collision with scheduled break)
"""

from datetime import datetime, timedelta
import random
from typing import List, Tuple

from yotta_oee.domain import (
    AnomalyType,
    GroundTruthAnomaly,
    MachineProductStandard,
    MachineState,
    ProductionCount,
    QualityInspection,
    Shift,
    StateEvent,
    ValidationRuleId,
    format_iso,
)
from yotta_oee.generator.config import GeneratorProfileConfig


class AnomalyInjector:
    """Deterministically mutates transactional records and records ground truth."""

    def __init__(self, config: GeneratorProfileConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng
        self.anomaly_counter = 1

    def inject_all(
        self,
        state_events: List[StateEvent],
        counts: List[ProductionCount],
        inspections: List[QualityInspection],
        standards: List[MachineProductStandard],
        shifts: List[Shift],
    ) -> Tuple[
        List[StateEvent],
        List[ProductionCount],
        List[QualityInspection],
        List[MachineProductStandard],
        List[GroundTruthAnomaly],
    ]:
        """Execute all 5 edge case injections and return modified datasets + ground truth."""
        ground_truth: List[GroundTruthAnomaly] = []
        n = self.config.anomalies_per_type

        # 1. EC-01: Overlapping Machine States
        state_events, ec01_gt = self._inject_overlapping_states(state_events, count=n)
        ground_truth.extend(ec01_gt)

        # 2. EC-02: Count Decrease Without Correction Event
        counts, ec02_gt = self._inject_unexplained_count_drops(counts, count=n)
        ground_truth.extend(ec02_gt)

        # 3. EC-03: Scrap Exceeds Total
        inspections, ec03_gt = self._inject_scrap_overflows(inspections, count=n)
        ground_truth.extend(ec03_gt)

        # 4. EC-04: Wrong Ideal Cycle Time Standard
        standards, ec04_gt = self._inject_invalid_cycle_times(standards, count=n)
        ground_truth.extend(ec04_gt)

        # 5. EC-05: Downtime Overlaps Planned Break
        state_events, ec05_gt = self._inject_breakdown_overlaps_break(state_events, shifts, count=n)
        ground_truth.extend(ec05_gt)

        return state_events, counts, inspections, standards, ground_truth

    def _next_anomaly_id(self) -> str:
        anom_id = f"ANOM-{self.anomaly_counter:06d}"
        self.anomaly_counter += 1
        return anom_id

    def _inject_overlapping_states(
        self, state_events: List[StateEvent], count: int
    ) -> Tuple[List[StateEvent], List[GroundTruthAnomaly]]:
        """EC-01: Force event[i+1] to start before event[i] finishes."""
        ground_truth = []
        events_copy = list(state_events)

        # Find eligible consecutive pairs on the same machine
        eligible_indices = []
        for i in range(len(events_copy) - 1):
            if events_copy[i].machine_id == events_copy[i + 1].machine_id:
                if events_copy[i].duration_sec >= 1200:
                    eligible_indices.append(i)

        selected = eligible_indices[:count]
        for idx in selected:
            e_prior = events_copy[idx]
            e_next = events_copy[idx + 1]

            # Shift next start_time 15 minutes before prior end_time
            overlap_delta = timedelta(minutes=15)
            new_start = e_prior.end_time - overlap_delta
            orig_start = e_next.start_time

            mutated_next = StateEvent(
                event_id=e_next.event_id,
                machine_id=e_next.machine_id,
                shift_id=e_next.shift_id,
                order_id=e_next.order_id,
                state=e_next.state,
                start_time=new_start,
                end_time=e_next.end_time,
                duration_sec=int((e_next.end_time - new_start).total_seconds()),
                reason_code=e_next.reason_code,
            )
            events_copy[idx + 1] = mutated_next

            ground_truth.append(
                GroundTruthAnomaly(
                    anomaly_id=self._next_anomaly_id(),
                    anomaly_type=AnomalyType.OVERLAPPING_STATE,
                    table_name="state_events",
                    record_id=e_next.event_id,
                    related_record_id=e_prior.event_id,
                    field_name="start_time",
                    injected_value=format_iso(new_start),
                    expected_value=format_iso(orig_start),
                    detection_rule_id=ValidationRuleId.VAL_TIME_002,
                )
            )

        return events_copy, ground_truth

    def _inject_unexplained_count_drops(
        self, counts: List[ProductionCount], count: int
    ) -> Tuple[List[ProductionCount], List[GroundTruthAnomaly]]:
        """EC-02: Decrease cumulative count without is_correction=True."""
        ground_truth = []
        counts_copy = list(counts)

        # Find count records with cumulative_count > 200 and not already a correction
        eligible_indices = [
            i for i, c in enumerate(counts_copy)
            if i > 5 and c.cumulative_count > 200 and not c.is_correction
        ]

        selected = eligible_indices[:count]
        for idx in selected:
            c_curr = counts_copy[idx]
            c_prev = counts_copy[idx - 1]

            # Drop cumulative count by 120 units
            orig_val = c_curr.cumulative_count
            injected_val = max(1, c_prev.cumulative_count - 120)
            drop_amount = orig_val - injected_val

            mutated_count = ProductionCount(
                count_id=c_curr.count_id,
                order_id=c_curr.order_id,
                machine_id=c_curr.machine_id,
                shift_id=c_curr.shift_id,
                timestamp=c_curr.timestamp,
                count_delta=-120,
                cumulative_count=injected_val,
                is_correction=False,           # Intentionally False!
                correction_ref_id=None,         # Intentionally None!
            )
            counts_copy[idx] = mutated_count

            # Adjust subsequent records for this (order_id, machine_id) so arithmetic
            # reconciliation (cum[t] = cum[t-1] + delta[t]) is preserved for all t > idx.
            target_order = c_curr.order_id
            target_machine = c_curr.machine_id
            for k in range(idx + 1, len(counts_copy)):
                if counts_copy[k].order_id == target_order and counts_copy[k].machine_id == target_machine:
                    sub = counts_copy[k]
                    counts_copy[k] = ProductionCount(
                        count_id=sub.count_id,
                        order_id=sub.order_id,
                        machine_id=sub.machine_id,
                        shift_id=sub.shift_id,
                        timestamp=sub.timestamp,
                        count_delta=sub.count_delta,
                        cumulative_count=max(0, sub.cumulative_count - drop_amount),
                        is_correction=sub.is_correction,
                        correction_ref_id=sub.correction_ref_id,
                    )

            ground_truth.append(
                GroundTruthAnomaly(
                    anomaly_id=self._next_anomaly_id(),
                    anomaly_type=AnomalyType.UNEXPLAINED_COUNT_DROP,
                    table_name="production_counts",
                    record_id=c_curr.count_id,
                    related_record_id=c_prev.count_id,
                    field_name="cumulative_count",
                    injected_value=str(injected_val),
                    expected_value=str(orig_val),
                    detection_rule_id=ValidationRuleId.VAL_COUNT_001,
                )
            )

        return counts_copy, ground_truth

    def _inject_scrap_overflows(
        self, inspections: List[QualityInspection], count: int
    ) -> Tuple[List[QualityInspection], List[GroundTruthAnomaly]]:
        """EC-03: Set scrap_qty > inspected_qty."""
        ground_truth = []
        inspections_copy = list(inspections)

        eligible_indices = list(range(len(inspections_copy)))
        selected = eligible_indices[:count]

        for idx in selected:
            qc = inspections_copy[idx]
            orig_scrap = qc.scrap_qty
            injected_scrap = qc.inspected_qty + 15  # Impossible scrap count

            mutated_qc = QualityInspection(
                inspection_id=qc.inspection_id,
                order_id=qc.order_id,
                machine_id=qc.machine_id,
                shift_id=qc.shift_id,
                timestamp=qc.timestamp,
                inspection_type=qc.inspection_type,
                inspected_qty=qc.inspected_qty,
                passed_qty=qc.passed_qty,
                scrap_qty=injected_scrap,
                rework_qty=qc.rework_qty,
                defect_code="DT-UNPLANNED-JAM",
            )
            inspections_copy[idx] = mutated_qc

            ground_truth.append(
                GroundTruthAnomaly(
                    anomaly_id=self._next_anomaly_id(),
                    anomaly_type=AnomalyType.SCRAP_EXCEEDS_TOTAL,
                    table_name="quality_inspections",
                    record_id=qc.inspection_id,
                    related_record_id=None,
                    field_name="scrap_qty",
                    injected_value=str(injected_scrap),
                    expected_value=str(orig_scrap),
                    detection_rule_id=ValidationRuleId.VAL_QUAL_001,
                )
            )

        return inspections_copy, ground_truth

    def _inject_invalid_cycle_times(
        self, standards: List[MachineProductStandard], count: int
    ) -> Tuple[List[MachineProductStandard], List[GroundTruthAnomaly]]:
        """EC-04: Inject an erroneous standard cycle time (order of magnitude wrong)."""
        ground_truth = []
        standards_copy = list(standards)

        eligible_indices = list(range(len(standards_copy)))
        selected = eligible_indices[:count]

        for idx in selected:
            std = standards_copy[idx]
            orig_ict = std.ideal_cycle_time_sec
            # Set to 0.35s (yielding > 2000% speed calculation)
            injected_ict = 0.350

            mutated_std = MachineProductStandard(
                standard_id=std.standard_id,
                machine_id=std.machine_id,
                product_id=std.product_id,
                ideal_cycle_time_sec=injected_ict,
            )
            standards_copy[idx] = mutated_std

            ground_truth.append(
                GroundTruthAnomaly(
                    anomaly_id=self._next_anomaly_id(),
                    anomaly_type=AnomalyType.INVALID_CYCLE_TIME,
                    table_name="machine_product_standards",
                    record_id=std.standard_id,
                    related_record_id=None,
                    field_name="ideal_cycle_time_sec",
                    injected_value=str(injected_ict),
                    expected_value=str(orig_ict),
                    detection_rule_id=ValidationRuleId.VAL_PERF_001,
                )
            )

        return standards_copy, ground_truth

    def _inject_breakdown_overlaps_break(
        self,
        state_events: List[StateEvent],
        shifts: List[Shift],
        count: int,
    ) -> Tuple[List[StateEvent], List[GroundTruthAnomaly]]:
        """EC-05: Inject an unplanned breakdown spanning across a planned shift break."""
        ground_truth = []
        events_copy = list(state_events)

        # Find planned break events (lunch breaks: 30 minutes) on distinct machines from EC-01
        machines = sorted(list({e.machine_id for e in events_copy}))
        target_machines = machines[1:] if len(machines) > 1 else machines
        lunch_events = [
            (i, e) for i, e in enumerate(events_copy)
            if e.state == MachineState.PLANNED_DOWNTIME and e.duration_sec == 1800 and e.machine_id in target_machines
        ]

        selected = lunch_events[:count]
        for idx, break_evt in selected:
            # Overlapping breakdown: coincides with the planned lunch break window
            colliding_start = break_evt.start_time
            colliding_end = break_evt.end_time
            colliding_dur = int((colliding_end - colliding_start).total_seconds())

            new_evt_id = f"EVT-{break_evt.machine_id}-9999{self.anomaly_counter:02d}"

            colliding_event = StateEvent(
                event_id=new_evt_id,
                machine_id=break_evt.machine_id,
                shift_id=break_evt.shift_id,
                order_id=None,
                state=MachineState.UNPLANNED_DOWNTIME,
                start_time=colliding_start,
                end_time=colliding_end,
                duration_sec=colliding_dur,
                reason_code="DT-UNPLANNED-JAM",
            )
            # Insert conflicting event
            events_copy.append(colliding_event)

            ground_truth.append(
                GroundTruthAnomaly(
                    anomaly_id=self._next_anomaly_id(),
                    anomaly_type=AnomalyType.BREAKDOWN_OVERLAPS_BREAK,
                    table_name="state_events",
                    record_id=new_evt_id,
                    related_record_id=break_evt.event_id,
                    field_name="start_time",
                    injected_value=format_iso(colliding_start),
                    expected_value=format_iso(break_evt.start_time),
                    detection_rule_id=ValidationRuleId.VAL_TIME_003,
                )
            )

        return events_copy, ground_truth
