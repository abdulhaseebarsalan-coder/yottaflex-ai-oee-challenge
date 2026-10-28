"""OEE consistency, analytical equivalence, and effective date validation rules."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import polars as pl

from yotta_oee.domain.enums import Severity, ValidationRuleId
from yotta_oee.recomputer.engine import IndependentOEERecomputer
from yotta_oee.validator.base import BaseValidationRule, RuleFinding


class EffectiveDateRule(BaseValidationRule):
    """VAL-DATE-001: Operational events and orders must strictly fall within master entity effective date windows."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_DATE_001

    @property
    def description(self) -> str:
        return "Validate that production orders and events fall strictly inside master entity effective dates."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []

        products_df = dataset.get("products.csv")
        orders_df = dataset.get("production_orders.csv")
        machines_df = dataset.get("machines.csv")
        events_df = dataset.get("state_events.csv")
        lines_df = dataset.get("lines.csv")

        # Map product_id -> (effective_from, effective_to)
        prod_dates: Dict[str, tuple] = {}
        if products_df is not None and "effective_from" in products_df.columns:
            for p in products_df.iter_rows(named=True):
                p_from = str(p["effective_from"]).strip()
                p_to = p.get("effective_to")
                prod_dates[p["product_id"]] = (
                    p_from,
                    str(p_to).strip() if p_to and str(p_to).strip() != "" else None,
                )

        # Map line_id -> (effective_from, effective_to)
        line_dates: Dict[str, tuple] = {}
        if lines_df is not None and "effective_from" in lines_df.columns:
            for l in lines_df.iter_rows(named=True):
                l_from = str(l["effective_from"]).strip()
                l_to = l.get("effective_to")
                line_dates[l["line_id"]] = (
                    l_from,
                    str(l_to).strip() if l_to and str(l_to).strip() != "" else None,
                )

        # Map machine_id -> (effective_from, effective_to)
        mch_dates: Dict[str, tuple] = {}
        if machines_df is not None and "effective_from" in machines_df.columns:
            for m in machines_df.iter_rows(named=True):
                m_from = str(m["effective_from"]).strip()
                m_to = m.get("effective_to")
                mch_dates[m["machine_id"]] = (
                    m_from,
                    str(m_to).strip() if m_to and str(m_to).strip() != "" else None,
                )

        # 1. Check production_orders against product and line effective dates
        if orders_df is not None:
            for o in orders_df.iter_rows(named=True):
                o_id = o["order_id"]
                p_id = o.get("product_id")
                l_id = o.get("line_id")
                o_start = str(o["scheduled_start"]).strip()
                o_end = str(o["scheduled_end"]).strip()

                if p_id in prod_dates:
                    p_from, p_to = prod_dates[p_id]
                    if o_start < p_from:
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_orders.csv",
                                record_id=o_id,
                                field_name="scheduled_start",
                                message=f"Order {o_id} scheduled_start ({o_start}) precedes product {p_id} effective_from ({p_from})",
                                observed_value=o_start,
                                expected_condition=f">= {p_from}",
                            )
                        )
                    if p_to is not None and o_end > p_to:
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_orders.csv",
                                record_id=o_id,
                                field_name="scheduled_end",
                                message=f"Order {o_id} scheduled_end ({o_end}) exceeds product {p_id} effective_to ({p_to})",
                                observed_value=o_end,
                                expected_condition=f"<= {p_to}",
                            )
                        )

                if l_id in line_dates:
                    l_from, l_to = line_dates[l_id]
                    if o_start < l_from or (l_to is not None and o_end > l_to):
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="production_orders.csv",
                                record_id=o_id,
                                field_name="scheduled_start",
                                message=f"Order {o_id} falls outside line {l_id} effective dates [{l_from}, {l_to}]",
                                observed_value=f"[{o_start}, {o_end}]",
                                expected_condition=f"Within [{l_from}, {l_to}]",
                            )
                        )

        # 2. Check state_events against machine effective dates
        if events_df is not None:
            for ev in events_df.iter_rows(named=True):
                m_id = ev["machine_id"]
                e_start = str(ev["start_time"]).strip()
                e_end = str(ev["end_time"]).strip()
                if m_id in mch_dates:
                    m_from, m_to = mch_dates[m_id]
                    if e_start < m_from or (m_to is not None and e_end > m_to):
                        findings.append(
                            RuleFinding(
                                rule_id=self.rule_id,
                                severity=Severity.ERROR,
                                table_name="state_events.csv",
                                record_id=ev["event_id"],
                                field_name="start_time",
                                message=f"Event {ev['event_id']} outside machine {m_id} effective range [{m_from}, {m_to}]",
                                observed_value=f"[{e_start}, {e_end}]",
                                expected_condition=f"Within [{m_from}, {m_to}]",
                            )
                        )

        return findings


class OEERecomputeConsistencyRule(BaseValidationRule):
    """VAL-OEE-001: Validate that OEE aggregates match independent recomputation from raw telemetry."""

    def __init__(self, findings_path: Optional[Any] = None) -> None:
        self.findings_path = Path(findings_path) if findings_path else None

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_OEE_001

    @property
    def description(self) -> str:
        return "Validate that computed OEE aggregates match independent raw recomputation within 1e-6."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []
        if "oee_aggregates.csv" not in dataset:
            return findings

        # Convert in-memory tables to dicts for independent recomputation
        dict_tables: Dict[str, List[Dict[str, Any]]] = {
            k: v.to_dicts() for k, v in dataset.items() if k != "oee_aggregates.csv"
        }

        recomputer = IndependentOEERecomputer(tables=dict_tables)
        recomputed = recomputer.recompute_all(findings_path=self.findings_path)
        recomp_map = {r["aggregate_id"]: r for r in recomputed}

        agg_df = dataset["oee_aggregates.csv"]
        for row in agg_df.iter_rows(named=True):
            agg_id = row["aggregate_id"]
            if agg_id not in recomp_map:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="oee_aggregates.csv",
                        record_id=agg_id,
                        message=f"Aggregate {agg_id} missing from independent recomputation",
                    )
                )
                continue

            rec = recomp_map[agg_id]

            # Float consistency check with 1e-6 tolerance
            for metric in ("availability", "performance", "quality", "oee"):
                file_val = float(row[metric])
                rec_val = float(rec[metric])
                delta = abs(file_val - rec_val)
                if delta > 1e-6:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="oee_aggregates.csv",
                            record_id=agg_id,
                            field_name=metric,
                            message=(
                                f"Recompute consistency mismatch on {agg_id}.{metric}: "
                                f"file={file_val:.6f}, recomputed={rec_val:.6f}, delta={delta:.2e} > 1e-6"
                            ),
                            observed_value=str(file_val),
                            expected_condition=f"Within 1e-6 of recomputed {rec_val:.6f}",
                            details={"delta": delta, "file_value": file_val, "recomputed_value": rec_val},
                        )
                    )

            # Integer metric checks
            for int_m in ("planned_prod_time_sec", "operating_time_sec", "total_count", "good_count"):
                file_v = int(row[int_m])
                rec_v = int(rec[int_m])
                if file_v != rec_v:
                    findings.append(
                        RuleFinding(
                            rule_id=self.rule_id,
                            severity=Severity.ERROR,
                            table_name="oee_aggregates.csv",
                            record_id=agg_id,
                            field_name=int_m,
                            message=f"Recompute integer metric mismatch on {agg_id}.{int_m}: file={file_v}, recomputed={rec_v}",
                            observed_value=str(file_v),
                            expected_condition=str(rec_v),
                        )
                    )

        return findings


class OEEIdentityRule(BaseValidationRule):
    """VAL-OEE-002: Dual-identity equivalence check: (A * P * Q) == ((GoodCount * ICT) / PPT)."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_OEE_002

    @property
    def description(self) -> str:
        return "Verify direct mass-energy equivalence identity (A * P * Q == Good * ICT / PPT); non-applicable on zero denominators."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []
        if "oee_aggregates.csv" not in dataset:
            return findings

        agg_df = dataset["oee_aggregates.csv"]
        for row in agg_df.iter_rows(named=True):
            ppt = float(row.get("planned_prod_time_sec", 0))
            ot = float(row.get("operating_time_sec", 0))
            total_count = float(row.get("total_count", 0))

            # Mark non-applicable on zero denominators
            if ppt <= 0 or ot <= 0 or total_count <= 0:
                continue

            a = float(row.get("availability", 0.0))
            p = float(row.get("performance", 0.0))
            q = float(row.get("quality", 0.0))
            good_count = float(row.get("good_count", 0))
            ict = float(row.get("ideal_cycle_time_sec", 0.0))

            direct_oee = (good_count * ict) / ppt
            row_oee = float(row.get("oee", 0.0))

            # 1. Theoretical mass-energy identity from unrounded components
            unrounded_a = ot / ppt
            unrounded_p = (total_count * ict) / ot
            unrounded_q = good_count / total_count
            component_delta = abs((unrounded_a * unrounded_p * unrounded_q) - direct_oee)

            # 2. Row OEE vs direct formula check
            oee_delta = abs(row_oee - round(direct_oee, 4))

            # 3. Product of rounded components vs direct formula (bounded by 4-decimal precision)
            row_mult_delta = abs((a * p * q) - direct_oee)

            if component_delta > 1e-6 or oee_delta > 1e-4 or row_mult_delta > 2e-4:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="oee_aggregates.csv",
                        record_id=row["aggregate_id"],
                        field_name="oee",
                        message=(
                            f"Dual-identity equivalence failure on {row['aggregate_id']}: "
                            f"oee_delta={oee_delta:.2e}, component_delta={component_delta:.2e}"
                        ),
                        observed_value=f"RowOEE={row_oee:.4f}, Direct={direct_oee:.4f}",
                        expected_condition="Dual identities must be equivalent within precision tolerance",
                        details={
                            "component_delta": component_delta,
                            "oee_delta": oee_delta,
                            "row_mult_delta": row_mult_delta,
                            "direct_oee": direct_oee,
                        },
                    )
                )

        return findings


class OEERangeSanityRule(BaseValidationRule):
    """VAL-OEE-003: Metric range sanity checks (Availability, Quality, OEE in [0.0, 1.0])."""

    @property
    def rule_id(self) -> ValidationRuleId:
        return ValidationRuleId.VAL_OEE_003

    @property
    def description(self) -> str:
        return "Validate that Availability, Quality, and OEE are strictly bounded in [0.0, 1.0]."

    def validate(self, dataset: Dict[str, pl.DataFrame]) -> List[RuleFinding]:
        findings: List[RuleFinding] = []
        if "oee_aggregates.csv" not in dataset:
            return findings

        agg_df = dataset["oee_aggregates.csv"]
        for row in agg_df.iter_rows(named=True):
            agg_id = row["aggregate_id"]
            avail = float(row.get("availability", 0.0))
            qual = float(row.get("quality", 0.0))
            oee = float(row.get("oee", 0.0))
            total = int(row.get("total_count", 0))
            good = int(row.get("good_count", 0))
            scrap = int(row.get("scrap_count", 0))
            rework = int(row.get("rework_count", 0))

            if not (0.0 <= avail <= 1.0):
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="oee_aggregates.csv",
                        record_id=agg_id,
                        field_name="availability",
                        message=f"Availability {avail} outside valid range [0.0, 1.0]",
                        observed_value=str(avail),
                        expected_condition="0.0 <= Availability <= 1.0",
                    )
                )

            if not (0.0 <= qual <= 1.0):
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="oee_aggregates.csv",
                        record_id=agg_id,
                        field_name="quality",
                        message=f"Quality {qual} outside valid range [0.0, 1.0]",
                        observed_value=str(qual),
                        expected_condition="0.0 <= Quality <= 1.0",
                    )
                )

            if not (0.0 <= oee <= 1.0):
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="oee_aggregates.csv",
                        record_id=agg_id,
                        field_name="oee",
                        message=f"OEE {oee} outside valid range [0.0, 1.0]",
                        observed_value=str(oee),
                        expected_condition="0.0 <= OEE <= 1.0",
                    )
                )

            if total < 0 or good < 0 or scrap < 0 or rework < 0 or good > total:
                findings.append(
                    RuleFinding(
                        rule_id=self.rule_id,
                        severity=Severity.ERROR,
                        table_name="oee_aggregates.csv",
                        record_id=agg_id,
                        field_name="total_count",
                        message=f"Count range sanity violation on {agg_id}: total={total}, good={good}, scrap={scrap}, rework={rework}",
                        observed_value=f"total={total}, good={good}",
                        expected_condition="Counts >= 0 and good <= total",
                    )
                )

        return findings
