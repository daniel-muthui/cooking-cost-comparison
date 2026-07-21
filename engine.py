"""
engine.py
Calculation engine for the Household Energy and Cost Comparison Tool.

Joins the CCT performance table (cct_lookup.csv) to the price/tariff
parameter file (parameters.csv) and computes, for a household menu:

  - monthly energy use per appliance/fuel
  - monthly cooking cost in KSh (tariff-band aware for electricity)
  - savings of a proposed menu against the household's baseline stack
  - payback period for newly purchased appliances

Design decisions (documented, per concept note):

  PORTION SCALING -- CCT results are for the tested batch (approx. two
  portions). Household demand is scaled LINEARLY by scale =
  servings_needed / CCT_REFERENCE_SERVINGS. Linear scaling overstates
  energy for larger pots (thermal losses do not scale with mass), so
  results for large households are conservative upper bounds. This is a
  stated limitation, not a hidden one.

  TARIFF BANDS -- a household's band is set by its total average monthly
  consumption (baseline non-cooking kWh + cooking kWh) and the WHOLE bill
  is priced at that band. Cooking electricity cost is therefore computed
  as bill(baseline + cooking) - bill(baseline), which correctly captures
  band-crossing repricing in either direction.

  UNTESTED COMBINATIONS -- if a dish-appliance pair has no CCT record (or
  a record with missing energy), the engine refuses to guess: it returns
  the pair in `unavailable` and excludes it from totals. Coverage gaps
  are managed by design, not silently interpolated.

Usage: see demo at bottom, or `python engine.py` for a worked example.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from tariff import load_params, band_for_consumption, effective_kwh_cost

LOOKUP_PATH = Path(__file__).parent / "cct_lookup.csv"


WEEKS_PER_MONTH = 52 / 12
CCT_REFERENCE_SERVINGS = 2  # each CCT prepared two portions (eCAP methodology)

# parameters.csv appliance_cost keys, mapped from canonical appliance names
APPLIANCE_COST_KEY = {
    "EPC": "epc",
    "Induction cooker": "induction_cooker",
    "Rice cooker": "rice_cooker",
    "Air fryer": "air_fryer",
    "Infrared cooker": "infrared_cooker",
    "Hot plate": "hot_plate",
    "LPG stove": "lpg_stove_cylinder",
    "Improved charcoal stove (ICS)": "improved_charcoal_stove",
    "Kerosene stove": "kerosene_stove",
    "Ethanol stove": "ethanol_stove",
}


# ------------------------------------------------------------------ loading

def load_lookup(path=LOOKUP_PATH):
    """Return {(dish, appliance): record} with numeric fields parsed."""
    table = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            for k in ("food_weight_g", "fuel_mass_g", "energy_kwh", "time_min",
                      "ease_of_use", "taste"):
                row[k] = float(row[k]) if row[k] not in ("", None) else None
            table[(row["dish"], row["appliance"])] = row
    return table


# ------------------------------------------------------------------- inputs

@dataclass
class MenuItem:
    """One dish cooked on one appliance a number of times per week."""
    dish: str
    appliance: str
    times_per_week: float


@dataclass
class Household:
    servings: int = 2                 # portions needed per cooking event
    baseline_monthly_kwh: float = 0   # non-cooking electricity use


@dataclass
class MonthlyResult:
    items: list = field(default_factory=list)        # per-item breakdown
    unavailable: list = field(default_factory=list)  # (dish, appliance, reason)
    cooking_kwh: float = 0.0          # electric cooking energy
    fuel_kg: dict = field(default_factory=dict)      # fuel -> kg/month
    fuel_cost: float = 0.0            # non-electric fuel cost, KSh
    electricity_cost: float = 0.0     # incremental electric cost, KSh
    band: str = ""                    # resulting tariff band
    time_hours: float = 0.0           # monthly time spent cooking

    @property
    def total_cost(self):
        return round(self.fuel_cost + self.electricity_cost, 0)


# ------------------------------------------------------------------- engine

def monthly_result(menu, household, lookup, params):
    """Compute monthly energy, cost, and time for a menu of MenuItems."""
    res = MonthlyResult()
    scale = household.servings / CCT_REFERENCE_SERVINGS

    for item in menu:
        rec = lookup.get((item.dish, item.appliance))
        if rec is None:
            res.unavailable.append((item.dish, item.appliance, "not tested in CCTs"))
            continue
        if rec["energy_kwh"] is None:
            res.unavailable.append((item.dish, item.appliance,
                                    "CCT record has no usable energy value"))
            continue

        events = item.times_per_week * WEEKS_PER_MONTH
        entry = {
            "dish": item.dish,
            "appliance": item.appliance,
            "fuel": rec["fuel"],
            "events_per_month": round(events, 1),
            "monthly_kwh": round(rec["energy_kwh"] * scale * events, 2),
            "monthly_cost": None,  # filled below
            "flag": rec["notes"] if ("REVIEW" in rec["notes"]
                                     or "caution" in rec["notes"]) else "",
        }
        if rec["time_min"]:
            res.time_hours += rec["time_min"] * events / 60

        if rec["fuel"] == "electricity":
            res.cooking_kwh += rec["energy_kwh"] * scale * events
        else:
            kg = (rec["fuel_mass_g"] / 1000.0) * scale * events
            price = params[("fuel_price", rec["fuel"])]
            cost = kg * price
            res.fuel_kg[rec["fuel"]] = res.fuel_kg.get(rec["fuel"], 0) + kg
            res.fuel_cost += cost
            entry["monthly_cost"] = round(cost, 0)
        res.items.append(entry)

    # electricity: incremental cost with band-aware repricing
    def bill(kwh):
        band, base = band_for_consumption(kwh, params)
        return kwh * effective_kwh_cost(base, params), band

    bill_with, band_with = bill(household.baseline_monthly_kwh + res.cooking_kwh)
    bill_without, _ = bill(household.baseline_monthly_kwh)
    res.electricity_cost = bill_with - bill_without
    res.band = band_with

    # distribute electric cost back to items proportionally for the breakdown
    if res.cooking_kwh > 0:
        per_kwh = res.electricity_cost / res.cooking_kwh
        for e in res.items:
            if e["monthly_cost"] is None:
                e["monthly_cost"] = round(e["monthly_kwh"] * per_kwh, 0)

    res.fuel_cost = round(res.fuel_cost, 0)
    res.electricity_cost = round(res.electricity_cost, 0)
    res.time_hours = round(res.time_hours, 1)
    return res


def compare(baseline_menu, proposed_menu, household, lookup, params,
            new_appliances=()):
    """Compare a proposed menu against the household's baseline stack.

    new_appliances: canonical names of appliances the household would need
    to BUY for the proposed menu (payback computed on their summed cost).
    """
    base = monthly_result(baseline_menu, household, lookup, params)
    prop = monthly_result(proposed_menu, household, lookup, params)
    savings = base.total_cost - prop.total_cost

    upfront = sum(
        params[("appliance_cost", APPLIANCE_COST_KEY[a])] for a in new_appliances
    )
    if savings > 0 and upfront > 0:
        payback_months = round(upfront / savings, 1)
    elif upfront > 0:
        payback_months = None  # no savings -> no payback
    else:
        payback_months = 0

    return {
        "baseline": base,
        "proposed": prop,
        "monthly_savings": round(savings, 0),
        "upfront_cost": round(upfront, 0),
        "payback_months": payback_months,
    }


# --------------------------------------------------------------------- demo

if __name__ == "__main__":
    lookup = load_lookup()
    params = load_params()

    # Household: 4 servings per meal, 45 kWh/month non-cooking electricity
    hh = Household(servings=4, baseline_monthly_kwh=45)

    # Baseline stack: charcoal for long-boiling, LPG for the rest
    baseline = [
        MenuItem("Beans", "Improved charcoal stove (ICS)", 2),
        MenuItem("Rice", "LPG stove", 3),
        MenuItem("Spinach", "LPG stove", 4),
        MenuItem("Chapati", "LPG stove", 1),
        MenuItem("Chips", "LPG stove", 1),
    ]

    # Proposed: EPC for boiling dishes + induction for the frying
    proposed = [
        MenuItem("Beans", "EPC", 2),
        MenuItem("Rice", "EPC", 3),
        MenuItem("Spinach", "EPC", 4),
        MenuItem("Chapati", "Induction cooker", 1),
        MenuItem("Chips", "Induction cooker", 1),
    ]

    out = compare(baseline, proposed, hh, lookup, params,
                  new_appliances=("EPC", "Induction cooker"))

    b, p = out["baseline"], out["proposed"]
    print(f"Baseline stack:           KSh {b.total_cost:>6,.0f}/month  "
          f"(fuel {b.fuel_cost:,.0f} + electricity {b.electricity_cost:,.0f}); "
          f"~{b.time_hours} h cooking")
    print(f"Proposed (EPC+induction): KSh {p.total_cost:>6,.0f}/month  "
          f"(+{p.cooking_kwh:.0f} kWh -> band '{p.band}'); ~{p.time_hours} h cooking")
    print(f"Monthly savings: KSh {out['monthly_savings']:,.0f}")
    print(f"Upfront cost:    KSh {out['upfront_cost']:,.0f}")
    print(f"Payback:         {out['payback_months']} months")
    for d, a, why in b.unavailable + p.unavailable:
        print(f"  !! {d} on {a}: {why}")
    for e in p.items:
        if e["flag"]:
            print(f"  ?? {e['dish']} on {e['appliance']}: {e['flag'][:80]}")
