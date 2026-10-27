"""Unit tests for Pydantic domain models and data serialization."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from yotta_oee.domain import (
    AggregateStatus,
    AnomalyType,
    DefectCode,
    DowntimeCategory,
    DowntimeReason,
    GroundTruthAnomaly,
    InspectionType,
    Line,
    LineType,
    Machine,
    MachineCriticality,
    MachineProductStandard,
    MachineState,
    OEEAggregate,
    OrderStatus,
    Plant,
    Product,
    ProductionCount,
    ProductionOrder,
    QualityInspection,
    Shift,
    ShiftCode,
    StateEvent,
    ValidationFinding,
    ValidationRuleId,
)



class TestMasterDataModels:
    def test_plant_valid_and_serialize(self, sample_plant: Plant):
        d = sample_plant.to_dict()
        assert d["plant_id"] == "PLANT-01"
        assert d["timezone"] == "UTC"

    def test_plant_invalid_id_raises(self):
        with pytest.raises(ValidationError):
            Plant(plant_id="BAD_PLANT_ID", name="Invalid", timezone="UTC", country="USA")

    def test_line_valid_and_serialize(self, sample_line: Line):
        d = sample_line.to_dict()
        assert d["line_id"] == "LINE-01"
        assert d["line_type"] == "MACHINING"

    def test_machine_valid_and_serialize(self, sample_machine: Machine):
        d = sample_machine.to_dict()
        assert d["machine_id"] == "MCH-LINE-01-01"
        assert d["sequence_order"] == 1

    def test_shift_chronology_validation(self, sample_plant: Plant):
        # Valid shift
        s = Shift(
            shift_id="SHIFT-2026-01-01-A",
            plant_id=sample_plant.plant_id,
            shift_code=ShiftCode.SHIFT_A,
            start_time=datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
            planned_break_sec=3600,
        )
        assert s.to_dict()["shift_code"] == "SHIFT_A"

        # End time before start time must raise ValidationError
        with pytest.raises(ValidationError):
            Shift(
                shift_id="SHIFT-2026-01-01-A",
                plant_id=sample_plant.plant_id,
                shift_code=ShiftCode.SHIFT_A,
                start_time=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
                planned_break_sec=3600,
            )

    def test_product_and_standard(self, sample_standard: MachineProductStandard):
        d = sample_standard.to_dict()
        assert d["ideal_cycle_time_sec"] == 12.0
        assert d["machine_id"] == "MCH-LINE-01-01"


class TestTransactionalModels:
    def test_production_order_schedule_validation(self, sample_line: Line, sample_product: Product):
        with pytest.raises(ValidationError):
            ProductionOrder(
                order_id="PO-2026-000001",
                product_id=sample_product.product_id,
                line_id=sample_line.line_id,
                target_quantity=1000,
                scheduled_start=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
                scheduled_end=datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            )

    def test_state_event_serialization(self, sample_machine: Machine, sample_shift: Shift):
        event = StateEvent(
            event_id="EVT-MCH-LINE-01-01-000001",
            machine_id=sample_machine.machine_id,
            shift_id=sample_shift.shift_id,
            state=MachineState.RUNNING,
            start_time=datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 1, 8, 30, 0, tzinfo=timezone.utc),
            duration_sec=9000,
        )
        d = event.to_dict()
        assert d["event_id"] == "EVT-MCH-LINE-01-01-000001"
        assert d["state"] == "RUNNING"
        assert d["duration_sec"] == 9000

    def test_production_count_and_correction(self, sample_order: ProductionOrder, sample_machine: Machine, sample_shift: Shift):
        # Normal count
        cnt = ProductionCount(
            count_id=f"CNT-{sample_order.order_id}-000001",
            order_id=sample_order.order_id,
            machine_id=sample_machine.machine_id,
            shift_id=sample_shift.shift_id,
            timestamp=datetime(2026, 1, 1, 6, 5, 0, tzinfo=timezone.utc),
            count_delta=25,
            cumulative_count=25,
            is_correction=False,
        )
        assert cnt.to_dict()["count_delta"] == 25

        # Correction count
        corr = ProductionCount(
            count_id=f"CNT-{sample_order.order_id}-000002",
            order_id=sample_order.order_id,
            machine_id=sample_machine.machine_id,
            shift_id=sample_shift.shift_id,
            timestamp=datetime(2026, 1, 1, 6, 6, 0, tzinfo=timezone.utc),
            count_delta=-5,
            cumulative_count=20,
            is_correction=True,
            correction_ref_id=cnt.count_id,
        )
        assert corr.to_dict()["is_correction"] is True
        assert corr.to_dict()["correction_ref_id"] == cnt.count_id

    def test_quality_inspection_serialization(self, sample_order: ProductionOrder, sample_machine: Machine, sample_shift: Shift):
        qc = QualityInspection(
            inspection_id="QC-2026-000001",
            order_id=sample_order.order_id,
            machine_id=sample_machine.machine_id,
            shift_id=sample_shift.shift_id,
            timestamp=datetime(2026, 1, 1, 7, 0, 0, tzinfo=timezone.utc),
            inspection_type=InspectionType.IN_PROCESS,
            inspected_qty=50,
            passed_qty=47,
            scrap_qty=2,
            rework_qty=1,
            defect_code=DefectCode.TOOL_MARKING,
        )
        d = qc.to_dict()
        assert d["inspected_qty"] == 50
        assert d["passed_qty"] == 47
        assert d["defect_code"] == "TOOL_MARKING"


class TestOutputAndGroundTruthModels:
    def test_oee_aggregate_serialization(self, sample_shift: Shift, sample_machine: Machine, sample_line: Line):
        agg = OEEAggregate(
            aggregate_id=f"OEE-{sample_shift.shift_id}-{sample_machine.machine_id}",
            shift_id=sample_shift.shift_id,
            machine_id=sample_machine.machine_id,
            line_id=sample_line.line_id,
            planned_prod_time_sec=25200,
            operating_time_sec=21420,
            unplanned_downtime_sec=3780,
            planned_downtime_sec=3600,
            total_count=1700,
            good_count=1666,
            scrap_count=34,
            rework_count=10,
            ideal_cycle_time_sec=12.0,
            availability=0.8500,
            performance=0.9524,
            quality=0.9800,
            oee=0.7933,
            status=AggregateStatus.CLEAN,
            exception_count=0,
        )
        d = agg.to_dict()
        assert d["oee"] == 0.7933
        assert d["status"] == "CLEAN"
        assert d["exception_count"] == 0

        assert d["availability"] == 0.8500

    def test_ground_truth_anomaly_model(self):
        anomaly = GroundTruthAnomaly(
            anomaly_id="ANOM-000001",
            anomaly_type=AnomalyType.OVERLAPPING_STATE,
            table_name="state_events",
            record_id="EVT-MCH-LINE-01-01-000142",
            related_record_id="EVT-MCH-LINE-01-01-000143",
            field_name="start_time",
            injected_value="2026-01-01T08:00:00Z",
            expected_value="2026-01-01T08:30:00Z",
            detection_rule_id=ValidationRuleId.VAL_TIME_002,
        )
        d = anomaly.to_dict()
        assert d["anomaly_type"] == "OVERLAPPING_STATE"
        assert d["detection_rule_id"] == "VAL-TIME-002"

    def test_validation_finding_model(self):
        finding = ValidationFinding(
            rule_id=ValidationRuleId.VAL_TIME_002,
            table_name="state_events",
            record_id="EVT-MCH-LINE-01-01-000142",
            message="State event overlaps with subsequent event",
            details={"overlap_seconds": 1800},
        )
        d = finding.to_dict()
        assert d["rule_id"] == "VAL-TIME-002"
        assert d["details"]["overlap_seconds"] == 1800
