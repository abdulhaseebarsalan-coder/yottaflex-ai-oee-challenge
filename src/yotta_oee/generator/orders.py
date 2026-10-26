"""Deterministic generator for Production Orders dispatched across lines and shifts."""

from datetime import datetime, timedelta
import random
from typing import Dict, List, Tuple

from yotta_oee.domain import Line, OrderStatus, Product, ProductionOrder, Shift
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
    ) -> List[ProductionOrder]:
        """Generate contiguous sequence of production orders for each line."""
        orders: List[ProductionOrder] = []
        order_counter = 1
        year = self.config.start_date.year

        # Sort shifts chronologically
        sorted_shifts = sorted(shifts, key=lambda s: s.start_time)
        first_shift_start = sorted_shifts[0].start_time
        last_shift_end = sorted_shifts[-1].end_time

        for line in lines:
            current_time = first_shift_start
            prod_idx = self.rng.randint(0, len(products) - 1)

            while current_time < last_shift_end:
                product = products[prod_idx % len(products)]
                order_id = f"PO-{year}-{order_counter:06d}"
                order_counter += 1

                # Order duration typically spans 1 to 3 shifts (8 to 24 hours)
                duration_shifts = self.rng.choice([1, 2, 3])
                order_duration = timedelta(hours=duration_shifts * 8)
                order_end = min(current_time + order_duration, last_shift_end)

                # Realistic target quantity based on ~70% operating efficiency at 10s takt
                # 8h * 3600s = 28,800s -> ~2,000 units per shift
                target_qty = duration_shifts * self.rng.randint(1200, 2200)

                # Determine lifecycle status
                if order_end <= last_shift_end:
                    status = OrderStatus.COMPLETED
                else:
                    status = OrderStatus.IN_PROGRESS

                orders.append(
                    ProductionOrder(
                        order_id=order_id,
                        product_id=product.product_id,
                        line_id=line.line_id,
                        target_quantity=target_qty,
                        scheduled_start=current_time,
                        scheduled_end=order_end,
                        status=status,
                    )
                )

                current_time = order_end
                prod_idx += 1  # rotate product

        return orders
