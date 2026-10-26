"""Shared pytest fixtures for the YottaFlex OEE test suite."""

from datetime import datetime, timezone
import pytest

from yotta_oee.domain import (
    DowntimeCategory,
    DowntimeReason,
    InspectionType,
    Line,
    LineType,
    Machine,
    MachineCriticality,
    MachineProductStandard,
    MachineState,
    OrderStatus,
    Plant,
    Product,
    ProductionCount,
    ProductionOrder,
    QualityInspection,
    Shift,
    ShiftCode,
    StateEvent,
)


@pytest.fixture
def sample_plant() -> Plant:
    return Plant(
        plant_id="PLANT-01",
        name="Apex Precision Works",
        timezone="UTC",
        country="USA",
    )


@pytest.fixture
def sample_line(sample_plant: Plant) -> Line:
    return Line(
        line_id="LINE-01",
        plant_id=sample_plant.plant_id,
        name="High-Speed Machining Cell 1",
        line_type=LineType.MACHINING,
    )


@pytest.fixture
def sample_machine(sample_line: Line) -> Machine:
    return Machine(
        machine_id="MCH-LINE-01-01",
        line_id=sample_line.line_id,
        name="5-Axis CNC Milling Station",
        sequence_order=1,
        criticality=MachineCriticality.HIGH,
    )


@pytest.fixture
def sample_shift(sample_plant: Plant) -> Shift:
    return Shift(
        shift_id="SHIFT-2026-01-01-A",
        plant_id=sample_plant.plant_id,
        shift_code=ShiftCode.SHIFT_A,
        start_time=datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
        planned_break_sec=3600,
    )


@pytest.fixture
def sample_product() -> Product:
    return Product(
        product_id="PRD-0001",
        sku="SKU-FLANGE-A100",
        name="Aerospace Titanium Flange",
        family="AEROSPACE",
    )


@pytest.fixture
def sample_standard(sample_machine: Machine, sample_product: Product) -> MachineProductStandard:
    return MachineProductStandard(
        standard_id=f"STD-{sample_machine.machine_id}-{sample_product.product_id}",
        machine_id=sample_machine.machine_id,
        product_id=sample_product.product_id,
        ideal_cycle_time_sec=12.0,
    )


@pytest.fixture
def sample_order(sample_line: Line, sample_product: Product) -> ProductionOrder:
    return ProductionOrder(
        order_id="PO-2026-000001",
        product_id=sample_product.product_id,
        line_id=sample_line.line_id,
        target_quantity=1500,
        scheduled_start=datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
        scheduled_end=datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
        status=OrderStatus.IN_PROGRESS,
    )
