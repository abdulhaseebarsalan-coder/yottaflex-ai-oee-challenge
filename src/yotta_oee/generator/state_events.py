"""Continuous machine state timeline synthesizer."""

from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional, Tuple

from yotta_oee.domain import (
    Machine,
    MachineState,
    ProductionOrder,
    Shift,
    StateEvent,
)
from yotta_oee.generator.config import GeneratorProfileConfig


class StateEventGenerator:
    """Generates continuous, gap-free machine state event logs for all shifts."""

    def __init__(self, config: GeneratorProfileConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng

    def generate_state_events(
        self,
        machines: List[Machine],
        shifts: List[Shift],
        orders: List[ProductionOrder],
    ) -> List[StateEvent]:
        """Synthesize gap-free machine state logs tiling every shift window."""
        all_events: List[StateEvent] = []

        # Index orders by line_id for fast temporal lookup
        orders_by_line: Dict[str, List[ProductionOrder]] = {}
        for order in orders:
            orders_by_line.setdefault(order.line_id, []).append(order)
        for line_id in orders_by_line:
            orders_by_line[line_id].sort(key=lambda o: o.scheduled_start)

        # Track event counters per machine
        event_counters: Dict[str, int] = {m.machine_id: 1 for m in machines}
        last_order_by_machine: Dict[str, Optional[str]] = {m.machine_id: None for m in machines}

        sorted_shifts = sorted(shifts, key=lambda s: s.start_time)

        for shift in sorted_shifts:
            shift_start = shift.start_time
            shift_end = shift.end_time

            # Define fixed break windows (Total = 60 min = 3,600s)
            break1_start = shift_start + timedelta(hours=2)
            break1_end = break1_start + timedelta(minutes=15)

            lunch_start = shift_start + timedelta(hours=4)
            lunch_end = lunch_start + timedelta(minutes=30)

            break2_start = shift_start + timedelta(hours=6)
            break2_end = break2_start + timedelta(minutes=15)

            # Define the 7 operational segments of the 8-hour shift
            # (4 work blocks + 3 planned breaks)
            segments: List[Tuple[datetime, datetime, bool]] = [
                (shift_start, break1_start, False),  # Work block 1 (2h = 7200s)
                (break1_start, break1_end, True),    # Break 1 (15m = 900s)
                (break1_end, lunch_start, False),    # Work block 2 (1h45m = 6300s)
                (lunch_start, lunch_end, True),      # Lunch Break (30m = 1800s)
                (lunch_end, break2_start, False),    # Work block 3 (1h30m = 5400s)
                (break2_start, break2_end, True),    # Break 2 (15m = 900s)
                (break2_end, shift_end, False),      # Work block 4 (1h45m = 6300s)
            ]

            for machine in machines:
                line_orders = orders_by_line.get(machine.line_id, [])

                for seg_start, seg_end, is_break in segments:
                    if is_break:
                        # Planned break event
                        evt_id = f"EVT-{machine.machine_id}-{event_counters[machine.machine_id]:06d}"
                        event_counters[machine.machine_id] += 1
                        dur = int((seg_end - seg_start).total_seconds())

                        all_events.append(
                            StateEvent(
                                event_id=evt_id,
                                machine_id=machine.machine_id,
                                shift_id=shift.shift_id,
                                order_id=None,
                                state=MachineState.PLANNED_DOWNTIME,
                                start_time=seg_start,
                                end_time=seg_end,
                                duration_sec=dur,
                                reason_code="DT-PLANNED-BREAK",
                            )
                        )
                    else:
                        # Active work segment
                        # Identify active order for this time window
                        active_order = self._find_active_order(line_orders, seg_start)
                        active_order_id = active_order.order_id if active_order else None

                        curr_ptr = seg_start

                        # Check if product/order changeover is needed
                        prev_order_id = last_order_by_machine[machine.machine_id]
                        if active_order_id and prev_order_id and active_order_id != prev_order_id:
                            # Insert changeover event (15 to 25 mins)
                            co_dur_min = self.rng.randint(15, 25)
                            co_end = min(curr_ptr + timedelta(minutes=co_dur_min), seg_end)
                            co_dur_sec = int((co_end - curr_ptr).total_seconds())

                            if co_dur_sec > 0:
                                evt_id = f"EVT-{machine.machine_id}-{event_counters[machine.machine_id]:06d}"
                                event_counters[machine.machine_id] += 1
                                all_events.append(
                                    StateEvent(
                                        event_id=evt_id,
                                        machine_id=machine.machine_id,
                                        shift_id=shift.shift_id,
                                        order_id=active_order_id,
                                        state=MachineState.CHANGEOVER,
                                        start_time=curr_ptr,
                                        end_time=co_end,
                                        duration_sec=co_dur_sec,
                                        reason_code="DT-CHANGEOVER-SETUP",
                                    )
                                )
                                curr_ptr = co_end

                        last_order_by_machine[machine.machine_id] = active_order_id

                        # Fill remaining time in segment
                        while curr_ptr < seg_end:
                            remaining_sec = int((seg_end - curr_ptr).total_seconds())
                            if remaining_sec <= 0:
                                break

                            # Decide if an unplanned stoppage occurs in this interval
                            has_stop = (self.rng.random() < 0.20) and (remaining_sec > 900)

                            if has_stop:
                                # Run for a while before the stop
                                run_dur = self.rng.randint(300, min(remaining_sec - 300, 2400))
                                run_end = curr_ptr + timedelta(seconds=run_dur)

                                evt_id = f"EVT-{machine.machine_id}-{event_counters[machine.machine_id]:06d}"
                                event_counters[machine.machine_id] += 1
                                all_events.append(
                                    StateEvent(
                                        event_id=evt_id,
                                        machine_id=machine.machine_id,
                                        shift_id=shift.shift_id,
                                        order_id=active_order_id,
                                        state=MachineState.RUNNING,
                                        start_time=curr_ptr,
                                        end_time=run_end,
                                        duration_sec=run_dur,
                                        reason_code=None,
                                    )
                                )
                                curr_ptr = run_end

                                # Unplanned stoppage
                                stop_rem = int((seg_end - curr_ptr).total_seconds())
                                stop_dur = min(stop_rem, self.rng.randint(300, 1200))
                                stop_end = curr_ptr + timedelta(seconds=stop_dur)

                                stop_roll = self.rng.random()
                                if stop_roll < 0.65:
                                    st_type = MachineState.UNPLANNED_DOWNTIME
                                    reason = self.rng.choice([
                                        "DT-UNPLANNED-JAM",
                                        "DT-UNPLANNED-ELEC",
                                        "DT-UNPLANNED-TOOL",
                                    ])
                                elif stop_roll < 0.85:
                                    st_type = MachineState.STARVED
                                    reason = "DT-STOP-STARVED"
                                else:
                                    st_type = MachineState.BLOCKED
                                    reason = "DT-STOP-BLOCKED"

                                evt_id = f"EVT-{machine.machine_id}-{event_counters[machine.machine_id]:06d}"
                                event_counters[machine.machine_id] += 1
                                all_events.append(
                                    StateEvent(
                                        event_id=evt_id,
                                        machine_id=machine.machine_id,
                                        shift_id=shift.shift_id,
                                        order_id=active_order_id,
                                        state=st_type,
                                        start_time=curr_ptr,
                                        end_time=stop_end,
                                        duration_sec=stop_dur,
                                        reason_code=reason,
                                    )
                                )
                                curr_ptr = stop_end
                            else:
                                # Entire remaining segment is RUNNING
                                evt_id = f"EVT-{machine.machine_id}-{event_counters[machine.machine_id]:06d}"
                                event_counters[machine.machine_id] += 1
                                all_events.append(
                                    StateEvent(
                                        event_id=evt_id,
                                        machine_id=machine.machine_id,
                                        shift_id=shift.shift_id,
                                        order_id=active_order_id,
                                        state=MachineState.RUNNING,
                                        start_time=curr_ptr,
                                        end_time=seg_end,
                                        duration_sec=remaining_sec,
                                        reason_code=None,
                                    )
                                )
                                curr_ptr = seg_end

        return all_events

    def _find_active_order(
        self, orders: List[ProductionOrder], target_time: datetime
    ) -> Optional[ProductionOrder]:
        """Find the production order scheduled at target_time."""
        for order in orders:
            if order.scheduled_start <= target_time < order.scheduled_end:
                return order
        if orders:
            # Fallback to closest prior or first order
            return orders[0]
        return None
