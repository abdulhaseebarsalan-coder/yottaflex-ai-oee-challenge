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
    DefectCode,
    GroundTruthAnomaly,
    MachineProductStandard,
    MachineState,
    ProductionCount,
    ProductionOrder,
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
        orders: List[ProductionOrder],
        standards: List[MachineProductStandard],
        shifts: List[Shift],
    ) -> Tuple[
        List[StateEvent],
        List[ProductionCount],
        List[QualityInspection],
        List[ProductionOrder],
        List[MachineProductStandard],
        List[GroundTruthAnomaly],
    ]:
        """Execute all 5 edge case injections across distinct machine-shifts and return ground truth."""
        ground_truth: List[GroundTruthAnomaly] = []
        n = self.config.anomalies_per_type
        used_machine_shifts: set[Tuple[str, str]] = set()

        # 1. EC-01: Overlapping Machine States
        state_events, ec01_gt = self._inject_overlapping_states(state_events, count=n, used_ms=used_machine_shifts)
        ground_truth.extend(ec01_gt)

        # 2. EC-02: Count Decrease Without Correction Event
        counts, ec02_gt = self._inject_unexplained_count_drops(counts, count=n, used_ms=used_machine_shifts)
        ground_truth.extend(ec02_gt)

        # 3. EC-03: Scrap Exceeds Total
        inspections, ec03_gt = self._inject_scrap_overflows(inspections, count=n, used_ms=used_machine_shifts)
        ground_truth.extend(ec03_gt)

        # 4. EC-04: Order Planned Cycle Time Inconsistency (Master standard kept intact)
        orders, ec04_gt = self._inject_invalid_cycle_times(orders, count=n)
        ground_truth.extend(ec04_gt)

        # 5. EC-05: Downtime Overlaps Planned Break (Realistic sequential ID)
        state_events, ec05_gt = self._inject_breakdown_overlaps_break(
            state_events, shifts, count=n, used_ms=used_machine_shifts
        )
        ground_truth.extend(ec05_gt)

        return state_events, counts, inspections, orders, standards, ground_truth

    def _next_anomaly_id(self) -> str:
        anom_id = f"ANOM-{self.anomaly_counter:06d}"
        self.anomaly_counter += 1
        return anom_id

    def _inject_overlapping_states(
        self, state_events: List[StateEvent], count: int, used_ms: set[Tuple[str, str]]
    ) -> Tuple[List[StateEvent], List[GroundTruthAnomaly]]:
        """EC-01: Force event[i+1] to start before event[i] finishes on distinct machine-shifts."""
        ground_truth = []
        events_copy = list(state_events)

        # Find eligible consecutive pairs on the same machine and distinct machine-shift
        selected = []
        for i in range(len(events_copy) - 1):
            e1 = events_copy[i]
            e2 = events_copy[i + 1]
            if e1.machine_id == e2.machine_id and e1.shift_id == e2.shift_id:
                ms_key = (e1.machine_id, e1.shift_id)
                if ms_key not in used_ms and e1.duration_sec >= 1200:
                    selected.append(i)
                    used_ms.add(ms_key)
                    if len(selected) >= count:
                        break

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
        self, counts: List[ProductionCount], count: int, used_ms: set[Tuple[str, str]]
    ) -> Tuple[List[ProductionCount], List[GroundTruthAnomaly]]:
        """EC-02: Decrease cumulative count without is_correction=True on distinct machine-shifts."""
        ground_truth = []
        counts_copy = list(counts)

        selected = []
        for i, c in enumerate(counts_copy):
            if i > 5 and c.cumulative_count > 200 and not c.is_correction:
                ms_key = (c.machine_id, c.shift_id)
                if ms_key not in used_ms:
                    selected.append(i)
                    used_ms.add(ms_key)
                    if len(selected) >= count:
                        break
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
        self, inspections: List[QualityInspection], count: int, used_ms: set[Tuple[str, str]]
    ) -> Tuple[List[QualityInspection], List[GroundTruthAnomaly]]:
        """EC-03: Set scrap_qty > inspected_qty on distinct machine-shifts."""
        ground_truth = []
        inspections_copy = list(inspections)

        selected = []
        for i, qc in enumerate(inspections_copy):
            ms_key = (qc.machine_id, qc.shift_id)
            if ms_key not in used_ms:
                selected.append(i)
                used_ms.add(ms_key)
                if len(selected) >= count:
                    break

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
                defect_code=DefectCode.BURR_CONTAMINATION,
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
        self, orders: List[ProductionOrder], count: int
    ) -> Tuple[List[ProductionOrder], List[GroundTruthAnomaly]]:
        """EC-04: Inject an erroneous planned cycle time on production order (e.g. 0.35s)."""
        ground_truth = []
        orders_copy = list(orders)

        eligible_indices = list(range(len(orders_copy)))
        selected = eligible_indices[:count]

        for idx in selected:
            order = orders_copy[idx]
            orig_pct = order.planned_cycle_time_sec
            # Set to 0.35s (yielding massive discrepancy against master engineering standard)
            injected_pct = 0.350

            mutated_order = ProductionOrder(
                order_id=order.order_id,
                product_id=order.product_id,
                line_id=order.line_id,
                target_quantity=order.target_quantity,
                scheduled_start=order.scheduled_start,
                scheduled_end=order.scheduled_end,
                status=order.status,
                planned_cycle_time_sec=injected_pct,
            )
            orders_copy[idx] = mutated_order

            ground_truth.append(
                GroundTruthAnomaly(
                    anomaly_id=self._next_anomaly_id(),
                    anomaly_type=AnomalyType.INVALID_CYCLE_TIME,
                    table_name="production_orders",
                    record_id=order.order_id,
                    related_record_id=None,
                    field_name="planned_cycle_time_sec",
                    injected_value=str(injected_pct),
                    expected_value=str(orig_pct),
                    detection_rule_id=ValidationRuleId.VAL_PERF_001,
                )
            )

        return orders_copy, ground_truth

    def _inject_breakdown_overlaps_break(
        self,
        state_events: List[StateEvent],
        shifts: List[Shift],
        count: int,
        used_ms: set[Tuple[str, str]],
    ) -> Tuple[List[StateEvent], List[GroundTruthAnomaly]]:
        """EC-05: Inject an unplanned breakdown spanning across a planned shift break on distinct machine-shifts."""
        ground_truth = []
        events_copy = list(state_events)

        # Find planned break events (lunch breaks: 30 minutes) on distinct machine-shifts
        lunch_events = [
            (i, e) for i, e in enumerate(events_copy)
            if e.state == MachineState.PLANNED_DOWNTIME and e.duration_sec == 1800
        ]

        selected = []
        for i, e in lunch_events:
            ms_key = (e.machine_id, e.shift_id)
            if ms_key not in used_ms:
                selected.append((i, e))
                used_ms.add(ms_key)
                if len(selected) >= count:
                    break
        for idx, break_evt in selected:
            # Overlapping breakdown: coincides with the planned lunch break window
            colliding_start = break_evt.start_time
            colliding_end = break_evt.end_time
            colliding_dur = int((colliding_end - colliding_start).total_seconds())

            # Realistic sequential event ID matching standard generator pattern (no giveaway 999905 IDs)
            mch_seqs = [
                int(e.event_id.split("-")[-1])
                for e in events_copy
                if e.machine_id == break_evt.machine_id and e.event_id.split("-")[-1].isdigit()
            ]
            next_seq = (max(mch_seqs) + 1) if mch_seqs else 1
            new_evt_id = f"EVT-{break_evt.machine_id}-{next_seq:06d}"

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

