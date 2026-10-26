"""Unit tests for the pure OEE mathematical calculation engine."""

import pytest
from yotta_oee.domain.oee_math import (
    calculate_availability,
    calculate_multi_product_performance,
    calculate_oee,
    calculate_operating_time,
    calculate_performance,
    calculate_planned_production_time,
    calculate_quality,
    calculate_weighted_ideal_cycle_time,
    verify_oee_equivalence,
)


class TestPlannedProductionTime:
    def test_standard_shift_deduction(self):
        # 8h shift (28,800s) minus 60m break (3,600s) = 25,200s (7h)
        ppt = calculate_planned_production_time(28800, 3600)
        assert ppt == 25200.0

    def test_zero_planned_break(self):
        ppt = calculate_planned_production_time(28800, 0)
        assert ppt == 28800.0

    def test_break_exceeding_shift_clamped_to_zero(self):
        ppt = calculate_planned_production_time(28800, 30000)
        assert ppt == 0.0


class TestOperatingTime:
    def test_normal_operating_time(self):
        assert calculate_operating_time(18000.5) == 18000.5

    def test_negative_operating_time_clamped_to_zero(self):
        assert calculate_operating_time(-100.0) == 0.0


class TestAvailability:
    def test_standard_availability(self):
        # Operating Time = 21,000s, PPT = 25,200s -> A = 21000 / 25200 = 0.8333333...
        avail = calculate_availability(21000, 25200)
        assert pytest.approx(avail, rel=1e-5) == 0.833333

    def test_zero_planned_production_time_returns_one(self):
        assert calculate_availability(1000, 0.0) == 1.0

    def test_zero_operating_time_returns_zero(self):
        assert calculate_availability(0.0, 25200) == 0.0

    def test_unclamped_exceeds_one_for_anomaly_detection(self):
        # Over-reporting or overlap anomaly
        raw_avail = calculate_availability(30000, 25200, clamp=False)
        assert raw_avail > 1.0

    def test_clamped_availability_capped_at_one(self):
        clamped_avail = calculate_availability(30000, 25200, clamp=True)
        assert clamped_avail == 1.0


class TestPerformance:
    def test_perfect_nominal_performance(self):
        # Produced 1,750 units at 12s standard = 21,000s net operating time
        # Machine ran for 21,000s -> P = 1.0 (100%)
        perf = calculate_performance(1750, 12.0, 21000)
        assert perf == 1.0

    def test_speed_loss_performance(self):
        # Produced 1,400 units at 12s standard = 16,800s net operating time
        # Operating time = 21,000s -> P = 16,800 / 21,000 = 0.80 (80%)
        perf = calculate_performance(1400, 12.0, 21000)
        assert pytest.approx(perf, rel=1e-5) == 0.80

    def test_zero_operating_time_returns_zero(self):
        assert calculate_performance(500, 12.0, 0.0) == 0.0

    def test_zero_count_returns_zero(self):
        assert calculate_performance(0, 12.0, 21000) == 0.0

    def test_zero_cycle_time_returns_zero(self):
        assert calculate_performance(500, 0.0, 21000) == 0.0

    def test_anomalous_cycle_time_unclamped(self):
        # EC-04: standard cycle time injected as 120s instead of 12s
        perf = calculate_performance(1750, 120.0, 21000)
        assert perf == 10.0  # 1000% speed, easily detected

    def test_multi_product_performance(self):
        # Run 1: 100 units @ 10s = 1,000s
        # Run 2: 200 units @ 20s = 4,000s
        # Total net = 5,000s. Operating time = 6,250s -> P = 5000 / 6250 = 0.80
        runs = [(100, 10.0), (200, 20.0)]
        perf = calculate_multi_product_performance(runs, 6250.0)
        assert pytest.approx(perf, rel=1e-5) == 0.80


class TestQuality:
    def test_standard_quality(self):
        # 1,000 total, 50 scrap -> Good = 950 -> Q = 0.95
        qual = calculate_quality(1000, 50)
        assert qual == 0.95

    def test_zero_total_count_returns_one(self):
        assert calculate_quality(0, 0) == 1.0

    def test_zero_scrap_perfect_quality(self):
        assert calculate_quality(500, 0) == 1.0

    def test_scrap_exceeding_total_clamped(self):
        # EC-03 with clamp returns 0.0
        assert calculate_quality(100, 120, clamp=True) == 0.0

    def test_scrap_exceeding_total_unclamped_detectable(self):
        # EC-03 without clamp yields negative quality
        raw_qual = calculate_quality(100, 120, clamp=False)
        assert raw_qual == -0.20


class TestOEECompositeAndEquivalence:
    def test_composite_oee_multiplication(self):
        # A = 0.85, P = 0.90, Q = 0.98 -> OEE = 0.7497
        oee = calculate_oee(0.85, 0.90, 0.98)
        assert pytest.approx(oee, rel=1e-5) == 0.7497

    def test_oee_mass_energy_equivalence_identity(self):
        """Verify |(A * P * Q) - ((GoodCount * ICT) / PPT)| <= 1e-6."""
        ppt = 25200.0
        operating_time = 21420.0  # A = 21420 / 25200 = 0.85
        total_count = 1700
        ict = 12.0
        scrap_count = 34
        good_count = 1666         # Q = 1666 / 1700 = 0.98

        avail = calculate_availability(operating_time, ppt)
        perf = calculate_performance(total_count, ict, operating_time)
        qual = calculate_quality(total_count, scrap_count)

        is_equiv, delta = verify_oee_equivalence(
            availability=avail,
            performance=perf,
            quality=qual,
            good_count=good_count,
            ideal_cycle_time_sec=ict,
            planned_prod_time_sec=ppt,
            tolerance=1e-6,
        )

        assert is_equiv is True
        assert delta < 1e-12

    def test_weighted_ideal_cycle_time(self):
        runs = [(100, 10.0), (300, 20.0)]
        weighted_ict = calculate_weighted_ideal_cycle_time(runs)
        # (100*10 + 300*20) / 400 = 7000 / 400 = 17.5
        assert weighted_ict == 17.5

    def test_weighted_ideal_cycle_time_empty(self):
        assert calculate_weighted_ideal_cycle_time([]) == 0.0
