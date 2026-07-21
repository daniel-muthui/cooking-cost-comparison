"""
app.py -- Streamlit interface for the Household Energy and Cost Comparison Tool.

Run locally:  streamlit run app.py
Requires: streamlit (pip install streamlit); engine.py, tariff.py,
cct_lookup.csv, parameters.csv in the same folder.

The interface is a thin layer: every number comes from engine.py, which is
unit-tested separately. Untested dish-appliance combinations are simply not
offered, so coverage gaps cannot be selected in the first place.
"""

import streamlit as st
from engine import (MenuItem, Household, load_lookup, compare,
                    APPLIANCE_COST_KEY)
from tariff import load_params

st.set_page_config(page_title="Cooking Cost Comparison -- Kenya", page_icon="🍲")

DISHES = ["Beans", "Rice", "Spinach", "Chapati", "Chips"]  # well-tested set
DEFAULT_FREQ = {"Beans": 2, "Rice": 3, "Spinach": 4, "Chapati": 1, "Chips": 1}


@st.cache_data
def data():
    return load_lookup(), load_params()


lookup, params = data()

# appliances available per dish = tested combos with usable energy only
def options_for(dish):
    return sorted(a for (d, a), rec in lookup.items()
                  if d == dish and rec["energy_kwh"] is not None)


st.title("Household Cooking Cost Comparison")
st.caption("Energy and cost of cooking fuels and appliances, from Controlled "
           "Cooking Test data (eCAP, Kenya Power Pika na Power kitchen) and "
           "current EPRA tariffs. Costs in KSh per month.")

with st.sidebar:
    st.header("Your household")
    servings = st.slider("Servings per meal", 1, 10, 4)
    baseline_kwh = st.number_input(
        "Current electricity use (kWh/month, excluding cooking)",
        min_value=0, max_value=500, value=45,
        help="From your KPLC bill or token purchases. Determines your tariff "
             "band -- adding electric cooking can move you to a higher band, "
             "which this tool accounts for.")
    st.divider()
    st.caption("Prices and tariffs are read from parameters.csv -- edit that "
               "file to update them. Fuel prices vary by locality.")

st.subheader("1. What you cook, and on what")
col_now, col_new = st.columns(2)
col_now.markdown("**Current appliance**")
col_new.markdown("**Considering instead**")

baseline_menu, proposed_menu = [], []
for dish in DISHES:
    opts = options_for(dish)
    with st.container():
        c0, c1, c2 = st.columns([1.2, 1.5, 1.5])
        freq = c0.number_input(f"{dish} (times/week)", 0.0, 21.0,
                               float(DEFAULT_FREQ[dish]), 0.5, key=f"f_{dish}")
        cur = c1.selectbox(dish, opts, key=f"cur_{dish}",
                           index=opts.index("LPG stove") if "LPG stove" in opts else 0,
                           label_visibility="collapsed")
        prop_default = ("EPC" if "EPC" in opts else
                        "Induction cooker" if "Induction cooker" in opts else opts[0])
        prop = c2.selectbox(dish, opts, key=f"prop_{dish}",
                            index=opts.index(prop_default),
                            label_visibility="collapsed")
    if freq > 0:
        baseline_menu.append(MenuItem(dish, cur, freq))
        proposed_menu.append(MenuItem(dish, prop, freq))

st.subheader("2. Appliances you would need to buy")
proposed_apps = sorted({m.appliance for m in proposed_menu})
current_apps = {m.appliance for m in baseline_menu}
to_buy = st.multiselect(
    "Only appliances you don't already own count toward payback",
    proposed_apps, default=[a for a in proposed_apps if a not in current_apps])

# ------------------------------------------------------------------ results
hh = Household(servings=servings, baseline_monthly_kwh=baseline_kwh)
out = compare(baseline_menu, proposed_menu, hh, lookup, params,
              new_appliances=tuple(to_buy))
b, p = out["baseline"], out["proposed"]

st.subheader("3. Results")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Current cost", f"KSh {b.total_cost:,.0f}/mo")
m2.metric("Proposed cost", f"KSh {p.total_cost:,.0f}/mo",
          delta=f"{p.total_cost - b.total_cost:+,.0f}", delta_color="inverse")
m3.metric("Monthly savings", f"KSh {out['monthly_savings']:,.0f}")
if out["payback_months"] is None:
    m4.metric("Payback", "never (no savings)")
elif out["payback_months"] == 0:
    m4.metric("Payback", "nothing to buy")
else:
    m4.metric("Payback", f"{out['payback_months']} months",
              help=f"Upfront cost KSh {out['upfront_cost']:,.0f}")

if p.cooking_kwh:
    st.info(f"Electric cooking adds **{p.cooking_kwh:.0f} kWh/month**; with your "
            f"baseline of {baseline_kwh} kWh you would be billed on the "
            f"**{p.band}** tariff band. Band changes reprice your whole bill, "
            f"and that effect is included in the numbers above.")

st.markdown(f"Cooking time: **{b.time_hours} h/mo now** vs "
            f"**{p.time_hours} h/mo proposed**.")

with st.expander("Per-dish breakdown"):
    cA, cB = st.columns(2)
    for col, res, title in ((cA, b, "Current"), (cB, p, "Proposed")):
        col.markdown(f"**{title}**")
        col.dataframe(
            [{"dish": e["dish"], "appliance": e["appliance"],
              "KSh/mo": e["monthly_cost"]} for e in res.items],
            hide_index=True, width='stretch')

warnings = ([f"{d} on {a}: {why}" for d, a, why in b.unavailable + p.unavailable]
            + [f"{e['dish']} on {e['appliance']}: data flagged -- {e['flag'][:90]}"
               for e in b.items + p.items if e["flag"]])
if warnings:
    with st.expander("Data caveats for this comparison"):
        for w in sorted(set(warnings)):
            st.warning(w)

st.caption("Method: MECS Controlled Cooking Test protocol; results scaled "
           "linearly from tested portions (a stated approximation that is "
           "conservative for large households). Untested combinations are "
           "never estimated. Sources and dates for every price are in "
           "parameters.csv.")
