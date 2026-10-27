"""Pydantic domain models for all 12 core manufacturing entities,

ground truth anomalies, and validation findings.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from yotta_oee.domain.enums import (
    AggregateStatus,
    AnomalyType,
    DefectCode,
    DowntimeCategory,
    InspectionType,
    LineType,
    MachineCriticality,
    MachineState,
    OrderStatus,
    Severity,
    ShiftCode,
    ValidationRuleId,
)


def format_iso(dt: datetime) -> str:
    """Format datetime as UTC ISO 8601 string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Master Data Entities
# ---------------------------------------------------------------------------

class Plant(BaseModel):
    """Manufacturing facility definition."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    plant_id: str = Field(..., pattern=r"^PLANT-\d{2}$", description="e.g. PLANT-01")
    name: str = Field(..., min_length=1, max_length=64)
    timezone: str = Field(default="UTC", max_length=32)
    country: str = Field(default="USA", min_length=2, max_length=3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plant_id": self.plant_id,
            "name": self.name,
            "timezone": self.timezone,
            "country": self.country,
        }


class Line(BaseModel):
    """Production line within a plant."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    line_id: str = Field(..., pattern=r"^LINE-\d{2}$", description="e.g. LINE-01")
    plant_id: str = Field(..., pattern=r"^PLANT-\d{2}$")
    name: str = Field(..., min_length=1, max_length=64)
    line_type: LineType = Field(default=LineType.MACHINING)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_id": self.line_id,
            "plant_id": self.plant_id,
            "name": self.name,
            "line_type": self.line_type.value,
        }


class Machine(BaseModel):
    """Individual equipment station within a production line."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    machine_id: str = Field(..., pattern=r"^MCH-LINE-\d{2}-\d{2}$", description="e.g. MCH-LINE-01-01")
    line_id: str = Field(..., pattern=r"^LINE-\d{2}$")
    name: str = Field(..., min_length=1, max_length=64)
    sequence_order: int = Field(..., ge=1, description="Station order on the line")
    criticality: MachineCriticality = Field(default=MachineCriticality.MEDIUM)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "line_id": self.line_id,
            "name": self.name,
            "sequence_order": self.sequence_order,
            "criticality": self.criticality.value,
        }


class Shift(BaseModel):
    """Scheduled 8-hour operational shift window."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    shift_id: str = Field(..., pattern=r"^SHIFT-\d{4}-\d{2}-\d{2}-[A-C]$", description="e.g. SHIFT-2026-01-01-A")
    plant_id: str = Field(..., pattern=r"^PLANT-\d{2}$")
    shift_code: ShiftCode
    start_time: datetime
    end_time: datetime
    planned_break_sec: int = Field(default=3600, ge=0, description="Scheduled break in seconds (60 min default)")

    @model_validator(mode="after")
    def validate_times(self) -> "Shift":
        if self.end_time <= self.start_time:
            raise ValueError(f"Shift end_time ({self.end_time}) must be after start_time ({self.start_time})")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shift_id": self.shift_id,
            "plant_id": self.plant_id,
            "shift_code": self.shift_code.value,
            "start_time": format_iso(self.start_time),
            "end_time": format_iso(self.end_time),
            "planned_break_sec": self.planned_break_sec,
        }


class Product(BaseModel):
    """Manufactured product definition."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str = Field(..., pattern=r"^PRD-\d{4}$", description="e.g. PRD-0001")
    sku: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    family: str = Field(..., min_length=1, max_length=32)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "sku": self.sku,
            "name": self.name,
            "family": self.family,
        }


class MachineProductStandard(BaseModel):
    """Engineering cycle time calibration for a Machine x Product pair."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    standard_id: str = Field(..., description="e.g. STD-MCH-LINE-01-01-PRD-0001")
    machine_id: str = Field(..., pattern=r"^MCH-LINE-\d{2}-\d{2}$")
    product_id: str = Field(..., pattern=r"^PRD-\d{4}$")
    ideal_cycle_time_sec: float = Field(..., gt=0.0, description="Standard takt time in seconds")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "standard_id": self.standard_id,
            "machine_id": self.machine_id,
            "product_id": self.product_id,
            "ideal_cycle_time_sec": round(self.ideal_cycle_time_sec, 3),
        }


# ---------------------------------------------------------------------------
# Transactional & Telemetry Entities
# ---------------------------------------------------------------------------

class ProductionOrder(BaseModel):
    """Work order scheduled on a production line."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(..., pattern=r"^PO-\d{4}-\d{6}$", description="e.g. PO-2026-000001")
    product_id: str = Field(..., pattern=r"^PRD-\d{4}$")
    line_id: str = Field(..., pattern=r"^LINE-\d{2}$")
    target_quantity: int = Field(..., gt=0)
    scheduled_start: datetime
    scheduled_end: datetime
    status: OrderStatus = Field(default=OrderStatus.PLANNED)
    planned_cycle_time_sec: float = Field(default=2.5, gt=0.0, description="Planned takt time in seconds for this order")

    @model_validator(mode="after")
    def validate_schedule(self) -> "ProductionOrder":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError(f"Order scheduled_end ({self.scheduled_end}) must be after scheduled_start ({self.scheduled_start})")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "product_id": self.product_id,
            "line_id": self.line_id,
            "target_quantity": self.target_quantity,
            "scheduled_start": format_iso(self.scheduled_start),
            "scheduled_end": format_iso(self.scheduled_end),
            "status": self.status.value,
            "planned_cycle_time_sec": round(self.planned_cycle_time_sec, 3),
        }


class DowntimeReason(BaseModel):
    """Master taxonomy for stoppage root causes."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason_code: str = Field(..., pattern=r"^DT-[A-Z]+-[A-Z0-9_]+$", description="e.g. DT-UNPLANNED-JAM")
    category: DowntimeCategory
    description: str = Field(..., min_length=1, max_length=128)
    affects_availability: bool = Field(..., description="True if this stoppage penalizes Availability")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "category": self.category.value,
            "description": self.description,
            "affects_availability": self.affects_availability,
        }


class StateEvent(BaseModel):
    """Continuous machine state interval record."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(..., pattern=r"^EVT-MCH-LINE-\d{2}-\d{2}-\d{6}$", description="e.g. EVT-MCH-LINE-01-01-000001")
    machine_id: str = Field(..., pattern=r"^MCH-LINE-\d{2}-\d{2}$")
    shift_id: str = Field(..., pattern=r"^SHIFT-\d{4}-\d{2}-\d{2}-[A-C]$")
    order_id: Optional[str] = Field(default=None, pattern=r"^PO-\d{4}-\d{6}$")
    state: MachineState
    start_time: datetime
    end_time: datetime
    duration_sec: int = Field(..., ge=0)
    reason_code: Optional[str] = Field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "machine_id": self.machine_id,
            "shift_id": self.shift_id,
            "order_id": self.order_id or "",
            "state": self.state.value,
            "start_time": format_iso(self.start_time),
            "end_time": format_iso(self.end_time),
            "duration_sec": self.duration_sec,
            "reason_code": self.reason_code or "",
        }


class ProductionCount(BaseModel):
    """Sensor pulse or batch increment record."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    count_id: str = Field(..., pattern=r"^CNT-PO-\d{4}-\d{6}-\d{6}$", description="e.g. CNT-PO-2026-000001-000001")
    order_id: str = Field(..., pattern=r"^PO-\d{4}-\d{6}$")
    machine_id: str = Field(..., pattern=r"^MCH-LINE-\d{2}-\d{2}$")
    shift_id: str = Field(..., pattern=r"^SHIFT-\d{4}-\d{2}-\d{2}-[A-C]$")
    timestamp: datetime
    count_delta: int = Field(..., description="Positive count increment or negative on correction")
    cumulative_count: int = Field(..., ge=0, description="Running tally for machine/order")
    is_correction: bool = Field(default=False)
    correction_ref_id: Optional[str] = Field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count_id": self.count_id,
            "order_id": self.order_id,
            "machine_id": self.machine_id,
            "shift_id": self.shift_id,
            "timestamp": format_iso(self.timestamp),
            "count_delta": self.count_delta,
            "cumulative_count": self.cumulative_count,
            "is_correction": self.is_correction,
            "correction_ref_id": self.correction_ref_id or "",
        }


class QualityInspection(BaseModel):
    """Quality control sampling audit record."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    inspection_id: str = Field(..., pattern=r"^QC-\d{4}-\d{6}$", description="e.g. QC-2026-000001")
    order_id: str = Field(..., pattern=r"^PO-\d{4}-\d{6}$")
    machine_id: str = Field(..., pattern=r"^MCH-LINE-\d{2}-\d{2}$")
    shift_id: str = Field(..., pattern=r"^SHIFT-\d{4}-\d{2}-\d{2}-[A-C]$")
    timestamp: datetime
    inspection_type: InspectionType = Field(default=InspectionType.IN_PROCESS)
    inspected_qty: int = Field(..., gt=0)
    passed_qty: int = Field(..., ge=0)
    scrap_qty: int = Field(..., ge=0)
    rework_qty: int = Field(..., ge=0)
    defect_code: Optional[DefectCode] = Field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inspection_id": self.inspection_id,
            "order_id": self.order_id,
            "machine_id": self.machine_id,
            "shift_id": self.shift_id,
            "timestamp": format_iso(self.timestamp),
            "inspection_type": self.inspection_type.value,
            "inspected_qty": self.inspected_qty,
            "passed_qty": self.passed_qty,
            "scrap_qty": self.scrap_qty,
            "rework_qty": self.rework_qty,
            "defect_code": self.defect_code.value if self.defect_code else "",
        }


# ---------------------------------------------------------------------------
# Analytical Outputs & Ground Truth
# ---------------------------------------------------------------------------

class OEEAggregate(BaseModel):
    """Rollup calculation for Shift x Machine operational effectiveness."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., description="e.g. OEE-SHIFT-2026-01-01-A-MCH-LINE-01-01")
    shift_id: str = Field(..., pattern=r"^SHIFT-\d{4}-\d{2}-\d{2}-[A-C]$")
    machine_id: str = Field(..., pattern=r"^MCH-LINE-\d{2}-\d{2}$")
    line_id: str = Field(..., pattern=r"^LINE-\d{2}$")
    planned_prod_time_sec: int = Field(..., ge=0)
    operating_time_sec: int = Field(..., ge=0)
    unplanned_downtime_sec: int = Field(..., ge=0)
    planned_downtime_sec: int = Field(..., ge=0)
    total_count: int = Field(..., ge=0)
    good_count: int = Field(..., ge=0)
    scrap_count: int = Field(..., ge=0)
    rework_count: int = Field(..., ge=0)
    ideal_cycle_time_sec: float = Field(..., gt=0.0)
    availability: float = Field(..., ge=0.0)
    performance: float = Field(..., ge=0.0)
    quality: float = Field(..., ge=0.0)
    oee: float = Field(..., ge=0.0)
    status: AggregateStatus = Field(default=AggregateStatus.CLEAN)
    exception_count: int = Field(default=0, ge=0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "aggregate_id": self.aggregate_id,
            "shift_id": self.shift_id,
            "machine_id": self.machine_id,
            "line_id": self.line_id,
            "planned_prod_time_sec": self.planned_prod_time_sec,
            "operating_time_sec": self.operating_time_sec,
            "unplanned_downtime_sec": self.unplanned_downtime_sec,
            "planned_downtime_sec": self.planned_downtime_sec,
            "total_count": self.total_count,
            "good_count": self.good_count,
            "scrap_count": self.scrap_count,
            "rework_count": self.rework_count,
            "ideal_cycle_time_sec": round(self.ideal_cycle_time_sec, 3),
            "availability": round(self.availability, 4),
            "performance": round(self.performance, 4),
            "quality": round(self.quality, 4),
            "oee": round(self.oee, 4),
            "status": self.status.value,
            "exception_count": self.exception_count,
        }



class GroundTruthAnomaly(BaseModel):
    """External anomaly registry entry documenting injected errors."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    anomaly_id: str = Field(..., pattern=r"^ANOM-\d{6}$", description="e.g. ANOM-000001")
    anomaly_type: AnomalyType
    table_name: str
    record_id: str
    related_record_id: Optional[str] = None
    field_name: str
    injected_value: str
    expected_value: str
    detection_rule_id: ValidationRuleId

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type.value,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "related_record_id": self.related_record_id or "",
            "field_name": self.field_name,
            "injected_value": self.injected_value,
            "expected_value": self.expected_value,
            "detection_rule_id": self.detection_rule_id.value,
        }


class ValidationFinding(BaseModel):
    """Single discrepancy discovered during validation."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: ValidationRuleId
    severity: Severity = Severity.ERROR
    table_name: str
    record_id: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id.value,
            "severity": self.severity.value,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "message": self.message,
            "details": self.details,
        }
