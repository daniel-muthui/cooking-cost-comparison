"""Unit tests for the calculation engine. Run: python -m pytest test_engine.py -q"""
import pytest
from tariff import load_params, band_for_consumption, effective_kwh_cost
from engine import (MenuItem, Household, load_lookup, monthly_result,
                    compare, WEEKS_PER_MONTH)

P = load_params()
L = load_lookup()


def test_band_thresholds():
    assert band_for_consumption(30, P)[0] == "lifeline"
    assert band_for_consumption(31, P)[0] == "ordinary"
    assert band_for_consumption(100, P)[0] == "ordinary"
    assert band_for_consumption(101, P)[0] == "high"


def test_effective_rate_ordering():
    rates = [effective_kwh_cost(band_for_consumption(k, P)[1], P) for k in (25, 60, 150)]
    assert rates[0] < rates[1] < rates[2]


def test_band_crossing_repriced():
    """Adding cooking load that crosses a band must reprice the whole bill:
    incremental cost per kWh exceeds the flat ordinary rate."""
    hh = Household(servings=2, baseline_monthly_kwh=28)  # lifeline before cooking
    menu = [MenuItem("Beans", "EPC", 2), MenuItem("Rice", "EPC", 3)]
    r = monthly_result(menu, hh, L, P)
    assert r.band == "ordinary"          # 28 + ~6 kWh crosses the 30 kWh line
    flat_ordinary = effective_kwh_cost(band_for_consumption(60, P)[1], P)
    assert r.electricity_cost / r.cooking_kwh > flat_ordinary


def test_fuel_cost_arithmetic():
    """Charcoal beans once a week, 2 servings: kg x price, no electricity."""
    hh = Household(servings=2, baseline_monthly_kwh=0)
    r = monthly_result([MenuItem("Beans", "Improved charcoal stove (ICS)", 1)], hh, L, P)
    kg = (457.5 / 1000) * WEEKS_PER_MONTH          # from cct_lookup fuel_mass_g
    assert r.fuel_cost == round(kg * P[("fuel_price", "charcoal")], 0)
    assert r.electricity_cost == 0 and r.cooking_kwh == 0


def test_linear_scaling():
    hh2 = Household(servings=2, baseline_monthly_kwh=200)  # fixed band (high)
    hh4 = Household(servings=4, baseline_monthly_kwh=200)
    m = [MenuItem("Rice", "EPC", 3)]
    r2, r4 = monthly_result(m, hh2, L, P), monthly_result(m, hh4, L, P)
    assert r4.cooking_kwh == pytest.approx(2 * r2.cooking_kwh)


def test_untested_combination_refused():
    hh = Household()
    r = monthly_result([MenuItem("Chapati", "EPC", 1)], hh, L, P)  # never tested
    assert r.total_cost == 0
    assert r.unavailable[0][:2] == ("Chapati", "EPC")


def test_no_savings_no_payback():
    hh = Household(servings=2, baseline_monthly_kwh=45)
    cheap = [MenuItem("Beans", "EPC", 2)]
    dear = [MenuItem("Beans", "Hot plate", 2)]
    out = compare(cheap, dear, hh, L, P, new_appliances=("Hot plate",))
    assert out["monthly_savings"] < 0 and out["payback_months"] is None


def test_review_flag_surfaces():
    hh = Household()
    r = monthly_result([MenuItem("Chapati", "LPG stove", 1)], hh, L, P)
    assert "REVIEW" in r.items[0]["flag"]
