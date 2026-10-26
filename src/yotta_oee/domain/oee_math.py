"""Pure mathematical formulas and boundary handlers for OEE calculations.

Formulas implemented:
1. Planned Production Time (PPT) = Shift Duration - Planned Break Time
2. Operating Time (OT) = Total time machine was in RUNNING state
3. Availability (A) = Operating Time / Planned Production Time
4. Performance (P) = (Total Count * Ideal Cycle Time) / Operating Time
5. Quality (Q) = Good Count / Total Count = (Total Count - Scrap Count) / Total Count
6. OEE = Availability * Performance * Quality

Equivalence Identity:
OEE = (Good Count * Ideal Cycle Time) / Planned Production Time
"""

from typing import List, Optional, Tuple


def calculate_planned_production_time(
    shift_duration_sec: float,
    planned_break_sec: float,
) -> float:
    """Calculate Planned Production Time (PPT).

    Assumption:
        Planned shift break time (e.g. lunch/tea breaks) is deducted from
        the gross shift duration to define the total time equipment was
        scheduled and expected to produce.

    Args:
        shift_duration_sec: Total duration of the shift in seconds (e.g., 28,800s for 8h).
        planned_break_sec: Scheduled non-working break time in seconds (e.g., 3,600s for 60m).

    Returns:
        Planned production time in seconds (non-negative).
    """
    return max(0.0, float(shift_duration_sec) - float(planned_break_sec))


def calculate_operating_time(running_duration_sec: float) -> float:
    """Calculate Operating Time (OT) from running state duration.

    Args:
        running_duration_sec: Sum of all RUNNING state event durations in seconds.

    Returns:
        Operating time in seconds (non-negative).
    """
    return max(0.0, float(running_duration_sec))


def calculate_availability(
    operating_time_sec: float,
    planned_prod_time_sec: float,
    clamp: bool = False,
) -> float:
    """Calculate Availability ratio (A).

    Availability is the ratio of Operating Time to Planned Production Time.

    Args:
        operating_time_sec: Duration in seconds equipment was actively operating.
        planned_prod_time_sec: Total planned operating time in seconds.
        clamp: If True, restricts result to [0.0, 1.0]. Defaults to False so
            anomalous state overlaps or over-reporting can be detected.

    Returns:
        Availability ratio as a float. Returns 1.0 if PPT is 0.
    """
    if planned_prod_time_sec <= 0.0:
        return 1.0

    raw_avail = max(0.0, float(operating_time_sec) / float(planned_prod_time_sec))
    return min(1.0, raw_avail) if clamp else raw_avail


def calculate_performance(
    total_count: int,
    ideal_cycle_time_sec: float,
    operating_time_sec: float,
    clamp_max: Optional[float] = None,
) -> float:
    """Calculate Performance ratio (P) for a single product run.

    Performance compares the actual production rate against the theoretical
    nameplate engineering design capacity (ideal cycle time).

    Args:
        total_count: Gross units produced (good + scrap + rework).
        ideal_cycle_time_sec: Theoretical minimum seconds to produce one unit.
        operating_time_sec: Actual seconds machine was operating.
        clamp_max: Optional upper bound. Defaults to None so that invalid
            cycle time anomalies (EC-04, e.g. 2000%) remain observable.

    Returns:
        Performance ratio as a float. Returns 0.0 if operating time is 0.
    """
    if operating_time_sec <= 0.0:
        return 0.0

    if total_count <= 0 or ideal_cycle_time_sec <= 0.0:
        return 0.0

    net_operating_time = float(total_count) * float(ideal_cycle_time_sec)
    raw_perf = net_operating_time / float(operating_time_sec)

    if clamp_max is not None:
        return min(clamp_max, max(0.0, raw_perf))
    return max(0.0, raw_perf)


def calculate_multi_product_performance(
    product_runs: List[Tuple[int, float]],
    operating_time_sec: float,
) -> float:
    """Calculate Performance ratio (P) across multiple products in one shift.

    Formula:
        P = sum(count_i * ideal_cycle_time_i) / operating_time_sec

    Args:
        product_runs: List of (total_count, ideal_cycle_time_sec) tuples.
        operating_time_sec: Actual seconds machine was operating.

    Returns:
        Performance ratio as a float.
    """
    if operating_time_sec <= 0.0:
        return 0.0

    total_net_operating_time = sum(
        float(count) * float(ict)
        for count, ict in product_runs
        if count > 0 and ict > 0.0
    )
    return max(0.0, total_net_operating_time / float(operating_time_sec))


def calculate_quality(
    total_count: int,
    scrap_count: int,
    clamp: bool = True,
) -> float:
    """Calculate Quality ratio (Q).

    Quality is the ratio of fully conforming, acceptable units (Good Count)
    to total units produced. Scrap units are unrecoverable defects.

    Args:
        total_count: Gross units produced.
        scrap_count: Non-conforming discarded units.
        clamp: If True, clamps ratio to [0.0, 1.0]. If False, returns raw
            ratio to allow detection of scrap > total anomalies (EC-03).

    Returns:
        Quality ratio as a float. Returns 1.0 if total_count is 0.
    """
    if total_count <= 0:
        return 1.0

    good_count = float(total_count) - float(scrap_count)
    raw_quality = good_count / float(total_count)

    if clamp:
        return max(0.0, min(1.0, raw_quality))
    return raw_quality


def calculate_oee(
    availability: float,
    performance: float,
    quality: float,
) -> float:
    """Calculate composite Overall Equipment Effectiveness (OEE).

    Formula:
        OEE = Availability * Performance * Quality

    Args:
        availability: Availability ratio (0.0 to 1.0).
        performance: Performance ratio (0.0 to 1.0+).
        quality: Quality ratio (0.0 to 1.0).

    Returns:
        Composite OEE ratio as a float.
    """
    return max(0.0, float(availability) * float(performance) * float(quality))


def verify_oee_equivalence(
    availability: float,
    performance: float,
    quality: float,
    good_count: int,
    ideal_cycle_time_sec: float,
    planned_prod_time_sec: float,
    tolerance: float = 1e-6,
) -> Tuple[bool, float]:
    """Verify analytical equivalence between A*P*Q and the direct time ratio.

    Mathematical identity:
        OEE = A * P * Q
            = (OT / PPT) * ((TotalCount * ICT) / OT) * (GoodCount / TotalCount)
            = (GoodCount * ICT) / PPT

    Args:
        availability: Availability component.
        performance: Performance component.
        quality: Quality component.
        good_count: Conforming units produced.
        ideal_cycle_time_sec: Engineering cycle time in seconds.
        planned_prod_time_sec: Planned production time in seconds.
        tolerance: Maximum allowed floating-point discrepancy (default 1e-6).

    Returns:
        Tuple of (is_equivalent: bool, absolute_delta: float).
    """
    oee_multiplied = availability * performance * quality

    if planned_prod_time_sec <= 0.0:
        direct_oee = 0.0
    else:
        direct_oee = (float(good_count) * float(ideal_cycle_time_sec)) / float(planned_prod_time_sec)

    delta = abs(oee_multiplied - direct_oee)
    return (delta <= tolerance, delta)


def calculate_weighted_ideal_cycle_time(
    product_runs: List[Tuple[int, float]],
) -> float:
    """Calculate production-weighted average ideal cycle time across runs.

    Args:
        product_runs: List of (count, ideal_cycle_time_sec) tuples.

    Returns:
        Weighted average cycle time in seconds, or 0.0 if total count is 0.
    """
    total_count = sum(count for count, _ in product_runs)
    if total_count <= 0:
        return 0.0

    total_time = sum(float(count) * float(ict) for count, ict in product_runs)
    return total_time / float(total_count)
