"""Domain enums for the YottaFlex OEE Analytics Engine."""

from enum import Enum


class ShiftCode(str, Enum):
    """Designation for standard 8-hour shift windows."""
    SHIFT_A = "SHIFT_A"  # 06:00 - 14:00 UTC
    SHIFT_B = "SHIFT_B"  # 14:00 - 22:00 UTC
    SHIFT_C = "SHIFT_C"  # 22:00 - 06:00 UTC


class LineType(str, Enum):
    """Functional classification of production lines."""
    MACHINING = "MACHINING"
    ASSEMBLY = "ASSEMBLY"
    PACKAGING = "PACKAGING"


class MachineCriticality(str, Enum):
    """Operational criticality of a machine station."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OrderStatus(str, Enum):
    """Lifecycle state of a production order."""
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MachineState(str, Enum):
    """Physical operational state of an individual machine.
    
    A machine is in exactly one state at any given point in time.
    """
    RUNNING = "RUNNING"
    UNPLANNED_DOWNTIME = "UNPLANNED_DOWNTIME"
    PLANNED_DOWNTIME = "PLANNED_DOWNTIME"
    CHANGEOVER = "CHANGEOVER"
    STARVED = "STARVED"
    BLOCKED = "BLOCKED"
    OFF = "OFF"


class DowntimeCategory(str, Enum):
    """High-level classification of downtime reasons."""
    PLANNED = "PLANNED"        # Scheduled breaks, maintenance (excluded from PPT)
    UNPLANNED = "UNPLANNED"    # Breakdowns, tool failures (penalizes Availability)
    CHANGEOVER = "CHANGEOVER"  # Tooling setup / die swaps (penalizes Availability)
    LINE_STOP = "LINE_STOP"    # Starvation or downstream blockage (penalizes Availability)


class InspectionType(str, Enum):
    """Milestone types for quality control audits."""
    FIRST_PIECE = "FIRST_PIECE"
    IN_PROCESS = "IN_PROCESS"
    FINAL = "FINAL"


class AnomalyType(str, Enum):
    """The five mandatory challenge edge cases deterministically injected."""
    OVERLAPPING_STATE = "OVERLAPPING_STATE"                   # EC-01
    UNEXPLAINED_COUNT_DROP = "UNEXPLAINED_COUNT_DROP"         # EC-02
    SCRAP_EXCEEDS_TOTAL = "SCRAP_EXCEEDS_TOTAL"               # EC-03
    INVALID_CYCLE_TIME = "INVALID_CYCLE_TIME"                 # EC-04
    BREAKDOWN_OVERLAPS_BREAK = "BREAKDOWN_OVERLAPS_BREAK"     # EC-05


class ValidationRuleId(str, Enum):
    """Unique identifiers for the 15 system integrity validation rules."""
    VAL_REL_001 = "VAL-REL-001"    # PK uniqueness
    VAL_REL_002 = "VAL-REL-002"    # FK referential integrity
    VAL_REL_003 = "VAL-REL-003"    # Enum domain enforcement
    VAL_TIME_001 = "VAL-TIME-001"  # Chronological monotonicity
    VAL_TIME_002 = "VAL-TIME-002"  # State mutual exclusivity / overlaps
    VAL_TIME_003 = "VAL-TIME-003"  # Break collision with unplanned downtime
    VAL_COUNT_001 = "VAL-COUNT-001" # Monotonic count progression
    VAL_COUNT_002 = "VAL-COUNT-002" # Running state authorization for counts
    VAL_QUAL_001 = "VAL-QUAL-001"  # Quality mass-balance & scrap <= inspected
    VAL_PERF_001 = "VAL-PERF-001"  # Standard cycle time adherence
    VAL_PERF_002 = "VAL-PERF-002"  # Performance ratio plausibility
    VAL_OEE_001 = "VAL-OEE-001"    # OEE mathematical consistency (A * P * Q)
    VAL_OEE_002 = "VAL-OEE-002"    # Direct mass-energy equivalence check
    VAL_OEE_003 = "VAL-OEE-003"    # Metric range sanity
    VAL_DUP_001 = "VAL-DUP-001"    # Exact record de-duplication


class Severity(str, Enum):
    """Severity classification of validation findings."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
