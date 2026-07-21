"""
tariff.py
Loads parameters.csv and computes the effective all-in electricity cost
(KSh/kWh) for each domestic tariff band. This is the single place the
tariff formula lives; the calculation engine imports from here.

Effective cost per kWh =
    (base + fuel_energy_cost_charge + forex_adjustment) * (1 + VAT)
    + rep_levy_rate * base
    + wrma_levy + epra_levy

Band assignment follows KPLC practice: a household's band is set by its
average monthly consumption over three months, and the WHOLE bill is priced
at that band's rate (bands are not progressive tiers on a single bill).
This is why added eCooking load can move a lifeline household into the
ordinary band and reprice all of its electricity -- the engine must compute
the band from (baseline consumption + added cooking kWh), not take the
current band as fixed.

Run directly for a summary: python tariff.py
"""

import csv
from pathlib import Path

PARAMS_PATH = Path(__file__).parent / "parameters.csv"


def load_params(path=PARAMS_PATH):
    params = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            params[(row["category"], row["parameter"])] = float(row["value"])
    return params


def effective_kwh_cost(base, p):
    vat = p[("electricity", "vat_rate")]
    fecc = p[("electricity", "fuel_energy_cost_charge")]
    forex = p[("electricity", "forex_adjustment")]
    rep = p[("electricity", "rep_levy_rate")]
    wrma = p[("electricity", "wrma_levy")]
    epra = p[("electricity", "epra_levy")]
    return (base + fecc + forex) * (1 + vat) + rep * base + wrma + epra


def band_for_consumption(monthly_kwh, p):
    """Return (band_name, base_rate) for a total monthly consumption."""
    if monthly_kwh <= p[("electricity", "band1_threshold")]:
        return "lifeline", p[("electricity", "band1_lifeline_base")]
    if monthly_kwh <= p[("electricity", "band2_threshold")]:
        return "ordinary", p[("electricity", "band2_ordinary_base")]
    return "high", p[("electricity", "band3_high_base")]


def effective_cost_for_consumption(monthly_kwh, p):
    band, base = band_for_consumption(monthly_kwh, p)
    return band, round(effective_kwh_cost(base, p), 2)


if __name__ == "__main__":
    p = load_params()
    print("Effective all-in electricity cost (KSh/kWh), June 2026 pass-throughs:")
    for kwh in (25, 60, 150):
        band, cost = effective_cost_for_consumption(kwh, p)
        print(f"  {kwh:>3} kWh/month -> {band:<9} {cost}")
