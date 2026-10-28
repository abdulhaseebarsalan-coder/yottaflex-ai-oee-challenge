"""Deterministic generator for Production Orders dispatched across lines and shifts."""

from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional, Tuple

from yotta_oee.domain import Line, MachineProductStandard, OrderStatus, Product, ProductionOrder, Shift
from yotta_oee.generator.config import GeneratorProfileConfig


class OrderGenerator:
    """Dispatches and schedules production orders across lines and time windows."""

    def __init__(self, config: GeneratorProfileConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng

    def generate_orders(
        self,
        lines: List[Line],
        products: List[Product],
        shifts: List[Shift],
        standards: Optional[List[MachineProductStandard]] = None,
    ) -> List[ProductionOrder]:
        """Generate contiguous sequence of production orders for each line."""
        orders: List[ProductionOrder] = []
        order_counter = 1
        year = self.config.start_date.year

        std_map: Dict[Tuple[str, str], float] = {}
        if standards:
            for s in standards:
                std_map[(s.machine_id, s.product_id)] = s.ideal_cycle_time_sec

        # Sort shifts chronologically
        sorted_shifts = sorted(shifts, key=lambda s: s.start_time)
        first_shift_start = sorted_shifts[0].start_time
        last_shift_end = sorted_shifts[-1].end_time

        is_full = getattr(self.config, "num_days", 3) >= 30
        for line in lines:
            current_time = first_shift_start
            prod_idx = self.rng.randint(0, len(products) - 1)
            lead_machine = f"MCH-{line.line_id}-01"

            while current_time < last_shift_end:
                # Filter candidate products active at current_time respecting effective dates
                active_prods = [
                    p for p in products
                    if p.effective_from <= current_time and (p.effective_to is None or current_time < p.effective_to)
                ]
                if not active_prods:
                    active_prods = products

                product = active_prods[prod_idx % len(active_prods)]
                order_id = f"PO-{year}-{order_counter:06d}"
                order_counter += 1

                # Order duration typically spans 1 to 3 shifts (8 to 24 hours)
                duration_shifts = self.rng.choice([1, 2, 3])
                order_duration = timedelta(hours=duration_shifts * 8)
                order_end = min(current_time + order_duration, last_shift_end)
                if product.effective_to is not None and order_end > product.effective_to:
                    order_end = product.effective_to

                if order_end <= current_time:
                    current_time += timedelta(hours=8)
                    continue

                actual_hours = (order_end - current_time).total_seconds() / 3600.0
                actual_shifts = max(1, int(round(actual_hours / 8.0)))
                target_qty = actual_shifts * self.rng.randint(1200, 2200)

                # Determine lifecycle status
                if is_full and order_counter == 50:
                    status = OrderStatus.CANCELLED
                elif current_time >= last_shift_end - timedelta(hours=8):
                    status = OrderStatus.IN_PROGRESS
                else:
                    status = OrderStatus.COMPLETED

                planned_cycle_time = std_map.get((lead_machine, product.product_id), 10.0)

                orders.append(
                    ProductionOrder(
                        order_id=order_id,
                        product_id=product.product_id,
                        line_id=line.line_id,
                        target_quantity=target_qty,
                        scheduled_start=current_time,
                        scheduled_end=order_end,
                        status=status,
                        planned_cycle_time_sec=planned_cycle_time,
                    )
                )

                current_time = order_end
                prod_idx += 1  # rotate product

        return orders

