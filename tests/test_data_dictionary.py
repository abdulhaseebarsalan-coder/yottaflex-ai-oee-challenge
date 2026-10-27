"""Tests ensuring docs/data_dictionary.md stays synchronized with Pydantic domain models."""

from pathlib import Path
import pytest

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
    ShiftCode,
)
from yotta_oee.domain.models import (
    DowntimeReason,
    Line,
    Machine,
    MachineProductStandard,
    OEEAggregate,
    Plant,
    Product,
    ProductionCount,
    ProductionOrder,
    QualityInspection,
    Shift,
    StateEvent,
)


@pytest.fixture(scope="module")
def data_dictionary_text() -> str:
    doc_path = Path("docs/data_dictionary.md")
    assert doc_path.exists(), "docs/data_dictionary.md does not exist"
    with open(doc_path, "r", encoding="utf-8") as f:
        return f.read()


class TestDataDictionaryDrift:
    def test_mermaid_er_diagram_present(self, data_dictionary_text: str):
        """Verify Mermaid ER diagram is defined with core entity blocks."""
        assert "```mermaid" in data_dictionary_text
        assert "erDiagram" in data_dictionary_text
        assert "PLANTS ||--o{ LINES" in data_dictionary_text
        assert "LINES ||--o{ MACHINES" in data_dictionary_text
        assert "MACHINES ||--o{ STATE_EVENTS" in data_dictionary_text
        assert "PRODUCTION_ORDERS ||--o{ PRODUCTION_COUNTS" in data_dictionary_text
        assert "PRODUCTION_ORDERS ||--o{ QUALITY_INSPECTIONS" in data_dictionary_text

    @pytest.mark.parametrize(
        "model_cls, table_name",
        [
            (Plant, "plants"),
            (Line, "lines"),
            (Machine, "machines"),
            (Product, "products"),
            (Shift, "shifts"),
            (MachineProductStandard, "machine_product_standards"),
            (DowntimeReason, "downtime_reasons"),
            (ProductionOrder, "production_orders"),
            (StateEvent, "state_events"),
            (ProductionCount, "production_counts"),
            (QualityInspection, "quality_inspections"),
            (OEEAggregate, "oee_aggregates"),
        ],
    )
    def test_all_model_fields_documented(self, data_dictionary_text: str, model_cls, table_name: str):
        """Assert every Pydantic model field is documented in docs/data_dictionary.md."""
        assert f"`{table_name}`" in data_dictionary_text, f"Table {table_name} missing from data dictionary"

        for field_name in model_cls.model_fields.keys():
            assert (
                f"`{field_name}`" in data_dictionary_text
            ), f"Field '{field_name}' of model '{model_cls.__name__}' ({table_name}) is missing from docs/data_dictionary.md"

    @pytest.mark.parametrize(
        "enum_cls",
        [
            ShiftCode,
            LineType,
            MachineCriticality,
            OrderStatus,
            MachineState,
            DowntimeCategory,
            InspectionType,
            DefectCode,
            AggregateStatus,
            AnomalyType,
        ],
    )
    def test_all_enums_documented(self, data_dictionary_text: str, enum_cls):
        """Assert all enum literal members are documented in docs/data_dictionary.md."""
        assert enum_cls.__name__ in data_dictionary_text, f"Enum {enum_cls.__name__} missing from data dictionary"
        for member in enum_cls:
            assert (
                member.value in data_dictionary_text
            ), f"Enum member '{member.name}' ({member.value}) of {enum_cls.__name__} missing from docs/data_dictionary.md"
