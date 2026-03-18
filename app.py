"""
Transport Cost-Benefit Analysis Dashboard
Parameters based on TfNSW Economic Parameter Values (January 2025)
All monetary values in June 2024 prices (AUD)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import math
import io
import csv

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Transport CBA Dashboard — TfNSW",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# TfNSW ECONOMIC PARAMETER VALUES (Jan 2025, June 2024 prices)
# ─────────────────────────────────────────────────────────────────────────────
PARAMS = {
    "vtts": {
        "urban": {"commute": 19.76, "business": 54.87, "other": 9.35},
        "rural": {"commute": 17.78, "business": 49.38, "other": 8.42},
    },
    "voc": {
        "urban": {
            "car":   {40: 0.268, 50: 0.241, 60: 0.224, 70: 0.215, 80: 0.212, 90: 0.215, 100: 0.224},
            "lgv":   {40: 0.323, 50: 0.296, 60: 0.281, 70: 0.273, 80: 0.271, 90: 0.276, 100: 0.287},
            "rigid": {40: 0.602, 50: 0.553, 60: 0.523, 70: 0.508, 80: 0.505, 90: 0.513, 100: 0.534},
            "artic": {40: 0.836, 50: 0.768, 60: 0.726, 70: 0.705, 80: 0.700, 90: 0.711, 100: 0.740},
        },
        "rural": {
            "car":   {60: 0.210, 80: 0.198, 100: 0.209, 110: 0.221},
            "lgv":   {60: 0.265, 80: 0.255, 100: 0.268, 110: 0.282},
            "rigid": {60: 0.493, 80: 0.475, 100: 0.502, 110: 0.526},
            "artic": {60: 0.685, 80: 0.660, 100: 0.697, 110: 0.731},
        },
    },
    "crash_costs": {
        "fatal": 9_462_000,
        "serious": 471_000,
        "moderate": 28_200,
        "minor": 13_100,
        "pdo": 11_500,
    },
    "vsl": 8_100_000,
    "carbon_per_tonne": 123,
    "air_pollution": {
        "urban": {"car": 0.032, "lgv": 0.045, "rigid": 0.179, "artic": 0.228},
        "rural": {"car": 0.005, "lgv": 0.007, "rigid": 0.028, "artic": 0.036},
    },
    "noise": {
        "urban": {"car": 0.005, "lgv": 0.005, "rigid": 0.037, "artic": 0.037},
        "rural": {"car": 0.001, "lgv": 0.001, "rigid": 0.006, "artic": 0.006},
    },
    "health_benefits": {"walking": 3.17, "cycling": 1.60},
    "reliability_ratio": 0.9,
    "working_days_per_year": 253,
    "days_per_year": 365,
    "traffic_composition": {
        "urban": {"car": 0.84, "lgv": 0.08, "rigid": 0.05, "artic": 0.03},
        "rural": {"car": 0.75, "lgv": 0.10, "rigid": 0.08, "artic": 0.07},
    },
    # Phase 0a: Emission cost per vehicle-km ($/veh-km), combining emission factor × carbon price
    # Derived from NTC fleet-average emission factors × $123/tCO₂e (June 2024)
    "emission_cost": {
        "urban": {"car": 0.023, "lgv": 0.027, "rigid": 0.071, "bus": 0.101},
        "rural": {"car": 0.007, "lgv": 0.009, "rigid": 0.022, "bus": 0.032},
    },
    # Phase 0c: Occupancy per vehicle type (persons/vehicle)
    # Car=1.4 (average auto), LCV/HCV=1.0 (driver only), Bus=45 (seated capacity)
    "occupancy": {"Car": 1.4, "LCV": 1.0, "HCV": 1.0, "Bus": 45.0},
}

# Phase 0b: Vehicle type mapping — UI labels to PARAMS internal keys
# Note: Bus approximated as artic for VOC/air/noise externality rates
VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "artic"}

# Canonical vehicle type list for matrix inputs
VTYPES = ["Car", "LCV", "HCV", "Bus"]

# Default modelling years
DEFAULT_MODELLING_YEARS = [2026, 2031, 2041, 2056]

# ─────────────────────────────────────────────────────────────────────────────
# DATA SCHEMA — Step 1: factory functions for matrix input structures
# ─────────────────────────────────────────────────────────────────────────────

def make_traffic_case(years: list) -> dict:
    """Return a zeroed traffic data dict for one case (base or project).

    Structure:
        {
          "years": [2026, 2031, ...],
          "Car":  {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
          "LCV":  {...},
          "HCV":  {...},
          "Bus":  {...},
        }
    """
    n = len(years)
    return {
        "years": list(years),
        **{
            vt: {"vht": [0.0] * n, "vkt": [0.0] * n, "stops": [0.0] * n, "demand": [0.0] * n}
            for vt in VTYPES
        },
    }


def make_traffic_data(years: list, n_project_cases: int = 1) -> dict:
    """Return a full traffic_data dict: base_case + project_1 … project_N.

    Structure:
        {
          "base_case":  <traffic_case>,
          "project_1":  <traffic_case>,
          ...
        }
    """
    data = {"base_case": make_traffic_case(years)}
    for i in range(1, n_project_cases + 1):
        data[f"project_{i}"] = make_traffic_case(years)
    return data


def make_crash_case(years: list) -> dict:
    """Return a zeroed crash data dict for one case.

    Structure:
        {"fatal": [...], "serious": [...], "moderate": [...], "minor": [...], "pdo": [...]}
    """
    n = len(years)
    severities = ["fatal", "serious", "moderate", "minor", "pdo"]
    return {s: [0.0] * n for s in severities}


def make_crash_data(years: list, n_project_cases: int = 1) -> dict:
    """Return crash_data dict keyed by case name."""
    data = {"base_case": make_crash_case(years)}
    for i in range(1, n_project_cases + 1):
        data[f"project_{i}"] = make_crash_case(years)
    return data


def make_cost_data(n_project_cases: int = 1) -> dict:
    """Return cost_data dict keyed by project case (base has no costs).

    Structure per project case:
        {
          "cap_planning": 0.0,   # $M
          "cap_land": 0.0,       # $M
          "cap_construction": 0.0,  # $M
          "contingency_pct": 0.0,   # %
          "opex_maint": 0.0,     # $M/year
          "opex_op": 0.0,        # $M/year
          "residual": 0.0,       # $M
        }
    """
    template = {
        "cap_planning": 0.0, "cap_land": 0.0, "cap_construction": 0.0,
        "contingency_pct": 0.0, "opex_maint": 0.0, "opex_op": 0.0, "residual": 0.0,
    }
    return {f"project_{i}": dict(template) for i in range(1, n_project_cases + 1)}


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def discount_factor(rate: float, year: int) -> float:
    return 1.0 / math.pow(1 + rate / 100, year)


def interpolate_voc(voc_table: dict, speed: float) -> float:
    speeds = sorted(voc_table.keys())
    if speed <= speeds[0]:
        return voc_table[speeds[0]]
    if speed >= speeds[-1]:
        return voc_table[speeds[-1]]
    for i in range(len(speeds) - 1):
        if speeds[i] <= speed <= speeds[i + 1]:
            ratio = (speed - speeds[i]) / (speeds[i + 1] - speeds[i])
            return voc_table[speeds[i]] + ratio * (voc_table[speeds[i + 1]] - voc_table[speeds[i]])
    return voc_table[speeds[0]]


def format_m(value: float) -> str:
    if abs(value) >= 1000:
        return f"${value / 1000:.1f}B"
    return f"${value:.1f}M"


def interpolate_modelling_years(modelling_years: list, values: list, eval_year: int) -> float:
    """Linearly interpolate (or extrapolate) a value for eval_year from modelling year data.

    Args:
        modelling_years: Sorted list of modelling years (e.g. [2026, 2031, 2041, 2056]).
        values: Values at each modelling year (same length as modelling_years).
        eval_year: The evaluation year to interpolate for.

    Returns:
        Interpolated (or extrapolated) value for eval_year.
    """
    if len(modelling_years) == 0 or len(values) == 0:
        return 0.0
    if len(modelling_years) == 1:
        return float(values[0])

    years = modelling_years
    # Clamp to range: extrapolate beyond last two points using last segment slope
    if eval_year <= years[0]:
        # Extrapolate below first modelling year using first two points
        slope = (values[1] - values[0]) / (years[1] - years[0]) if years[1] != years[0] else 0.0
        return float(values[0]) + slope * (eval_year - years[0])
    if eval_year >= years[-1]:
        # Extrapolate beyond last modelling year using last two points
        slope = (values[-1] - values[-2]) / (years[-1] - years[-2]) if years[-1] != years[-2] else 0.0
        return float(values[-1]) + slope * (eval_year - years[-1])

    # Linear interpolation between bracketing modelling years
    for i in range(len(years) - 1):
        if years[i] <= eval_year <= years[i + 1]:
            if years[i + 1] == years[i]:
                return float(values[i])
            ratio = (eval_year - years[i]) / (years[i + 1] - years[i])
            return float(values[i]) + ratio * (float(values[i + 1]) - float(values[i]))

    return float(values[-1])


# ─────────────────────────────────────────────────────────────────────────────
# CALCULATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def calculate(inputs: dict) -> dict:
    ctx = inputs["context"]
    eval_period = inputs["evaluation_period"]
    const_years = inputs["construction_years"]
    dr = inputs["discount_rate"]
    aadt = inputs["aadt"]
    growth = inputs["traffic_growth"] / 100
    trip_len = inputs["trip_length"]
    occupancy = inputs["occupancy"]
    pct_commute = inputs["pct_commute"] / 100
    pct_business = inputs["pct_business"] / 100
    pct_other = max(0, 1 - pct_commute - pct_business)
    pct_heavy = inputs["pct_heavy"] / 100
    speed_base = inputs["speed_base"]
    speed_project = inputs["speed_project"]

    # --- COSTS ---
    cap_planning = inputs["cap_planning"]
    cap_land = inputs["cap_land"]
    cap_construction = inputs["cap_construction"]
    contingency_pct = inputs["contingency"] / 100
    total_capital = (cap_planning + cap_land + cap_construction) * (1 + contingency_pct)
    opex_maint = inputs["opex_maint"]
    opex_op = inputs["opex_op"]
    residual = inputs["residual"]
    annual_capital = total_capital / const_years if const_years > 0 else 0

    # --- ANNUAL BENEFITS (first year of operation) ---
    vtts_set = PARAMS["vtts"][ctx]

    time_base_hr = trip_len / speed_base if speed_base > 0 else 0
    time_project_hr = trip_len / speed_project if speed_project > 0 else 0
    time_saving_hr = max(0, time_base_hr - time_project_hr)

    daily_person_trips = aadt * occupancy
    vtts_weighted = (
        vtts_set["commute"] * pct_commute
        + vtts_set["business"] * pct_business
        + vtts_set["other"] * pct_other
    )

    annual_tts = daily_person_trips * time_saving_hr * vtts_weighted * PARAMS["days_per_year"] / 1e6
    annual_reliability = annual_tts * PARAMS["reliability_ratio"] * 0.3

    # VOC savings
    voc_base_car = interpolate_voc(PARAMS["voc"][ctx]["car"], speed_base)
    voc_proj_car = interpolate_voc(PARAMS["voc"][ctx]["car"], speed_project)
    voc_saving_car = max(0, voc_base_car - voc_proj_car)

    voc_base_heavy = interpolate_voc(PARAMS["voc"][ctx]["rigid"], speed_base)
    voc_proj_heavy = interpolate_voc(PARAMS["voc"][ctx]["rigid"], speed_project)
    voc_saving_heavy = max(0, voc_base_heavy - voc_proj_heavy)

    annual_voc = (
        aadt * (1 - pct_heavy) * trip_len * voc_saving_car
        + aadt * pct_heavy * trip_len * voc_saving_heavy
    ) * PARAMS["days_per_year"] / 1e6

    # Safety
    annual_safety = (
        inputs["crash_fatal"] * PARAMS["crash_costs"]["fatal"]
        + inputs["crash_serious"] * PARAMS["crash_costs"]["serious"]
        + inputs["crash_moderate"] * PARAMS["crash_costs"]["moderate"]
        + inputs["crash_minor"] * PARAMS["crash_costs"]["minor"]
        + inputs["crash_pdo"] * PARAMS["crash_costs"]["pdo"]
    ) / 1e6

    # Environmental
    annual_co2 = inputs["co2_reduction"] * PARAMS["carbon_per_tonne"] / 1e6
    annual_air = inputs["air_pollution_reduction"] / 1e3
    annual_noise = inputs["noise_reduction"] / 1e3
    annual_env = annual_co2 + annual_air + annual_noise

    # Active transport
    annual_walk = inputs["walk_km"] * PARAMS["health_benefits"]["walking"] * PARAMS["days_per_year"] / 1e6
    annual_cycle = inputs["cycle_km"] * PARAMS["health_benefits"]["cycling"] * PARAMS["days_per_year"] / 1e6
    annual_active = annual_walk + annual_cycle

    total_first_year = annual_tts + annual_reliability + annual_voc + annual_safety + annual_env + annual_active

    # --- YEAR-BY-YEAR CASHFLOW ---
    total_years = const_years + eval_period
    annual_costs = []
    annual_benefits = []
    benefits_by_type = {"tts": [], "reliability": [], "voc": [], "safety": [], "env": [], "active": []}
    annual_net = []
    disc_costs = []
    disc_benefits = []
    disc_net = []
    cum_disc_net = []

    pv_benefits = 0
    pv_costs = 0
    cum = 0
    payback_year = None

    for y in range(total_years):
        df = discount_factor(dr, y)
        cost = 0
        benefit = 0
        b_tts = b_rel = b_voc = b_safety = b_env = b_active = 0

        if y < const_years:
            cost = annual_capital
        else:
            op_year = y - const_years
            gf = math.pow(1 + growth, op_year)
            cost = opex_maint + opex_op
            b_tts = annual_tts * gf
            b_rel = annual_reliability * gf
            b_voc = annual_voc * gf
            b_safety = annual_safety
            b_env = annual_env
            b_active = annual_active
            benefit = b_tts + b_rel + b_voc + b_safety + b_env + b_active
            if y == total_years - 1:
                benefit += residual

        annual_costs.append(cost)
        annual_benefits.append(benefit)
        benefits_by_type["tts"].append(b_tts)
        benefits_by_type["reliability"].append(b_rel)
        benefits_by_type["voc"].append(b_voc)
        benefits_by_type["safety"].append(b_safety)
        benefits_by_type["env"].append(b_env)
        benefits_by_type["active"].append(b_active)

        net = benefit - cost
        annual_net.append(net)
        disc_costs.append(cost * df)
        disc_benefits.append(benefit * df)
        disc_net.append(net * df)

        pv_costs += cost * df
        pv_benefits += benefit * df
        cum += net * df
        cum_disc_net.append(cum)

        if payback_year is None and cum >= 0 and y >= const_years:
            payback_year = y + 1

    npv = pv_benefits - pv_costs
    bcr = pv_benefits / pv_costs if pv_costs > 0 else 0
    fyrr = (total_first_year / total_capital) * 100 if total_capital > 0 else 0

    # PV by benefit type
    pv_by_type = {}
    for t in benefits_by_type:
        pv_by_type[t] = sum(benefits_by_type[t][y] * discount_factor(dr, y) for y in range(total_years))

    # Sensitivity: discount rates
    sensitivity_dr = {}
    for r in [3, 4, 5, 7, 10, 12]:
        s_pvb = sum(annual_benefits[y] * discount_factor(r, y) for y in range(total_years))
        s_pvc = sum(annual_costs[y] * discount_factor(r, y) for y in range(total_years))
        sensitivity_dr[r] = {
            "pvb": s_pvb, "pvc": s_pvc, "npv": s_pvb - s_pvc,
            "bcr": s_pvb / s_pvc if s_pvc > 0 else 0,
        }

    # Switching values
    switching = {}
    if pv_benefits > 0 and pv_costs > 0:
        switching["Total Benefits"] = -((pv_benefits - pv_costs) / pv_benefits) * 100
        switching["Total Costs"] = ((pv_benefits - pv_costs) / pv_costs) * 100
        type_labels = {
            "tts": "Travel Time Savings", "reliability": "Reliability",
            "voc": "Vehicle Operating Costs", "safety": "Safety",
            "env": "Environmental", "active": "Active Transport",
        }
        for t, label in type_labels.items():
            if pv_by_type[t] > 0:
                switching[label] = -((pv_benefits - pv_costs) / pv_by_type[t]) * 100

    # Demand scenarios
    scenarios = {}
    for label, factor in [("Low (-20%)", 0.8), ("Central", 1.0), ("High (+20%)", 1.2)]:
        s_pvb = sum(annual_benefits[y] * factor * discount_factor(dr, y) for y in range(total_years))
        s_pvc = sum(annual_costs[y] * discount_factor(dr, y) for y in range(total_years))
        scenarios[label] = {
            "pvb": s_pvb, "pvc": s_pvc, "npv": s_pvb - s_pvc,
            "bcr": s_pvb / s_pvc if s_pvc > 0 else 0,
        }

    return {
        "npv": npv, "bcr": bcr, "pv_benefits": pv_benefits, "pv_costs": pv_costs,
        "fyrr": fyrr, "payback_year": payback_year,
        "total_capital": total_capital,
        "annual_costs": annual_costs, "annual_benefits": annual_benefits,
        "annual_net": annual_net,
        "disc_costs": disc_costs, "disc_benefits": disc_benefits, "disc_net": disc_net,
        "cum_disc_net": cum_disc_net,
        "pv_by_type": pv_by_type, "sensitivity_dr": sensitivity_dr,
        "switching": switching, "scenarios": scenarios,
        "const_years": const_years, "eval_period": eval_period,
        "total_years": total_years, "dr": dr,
        "benefits_by_type": benefits_by_type,
        "first_year": {
            "tts": annual_tts, "reliability": annual_reliability,
            "voc": annual_voc, "safety": annual_safety,
            "env": annual_env, "active": annual_active,
            "total": total_first_year,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def generate_csv(results: dict, project_name: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    r = results
    w.writerow(["Transport CBA Dashboard Export"])
    w.writerow(["Project", project_name])
    w.writerow(["Discount Rate", f"{r['dr']}%"])
    w.writerow(["NPV ($M)", f"{r['npv']:.2f}"])
    w.writerow(["BCR", f"{r['bcr']:.3f}"])
    w.writerow(["PV Benefits ($M)", f"{r['pv_benefits']:.2f}"])
    w.writerow(["PV Costs ($M)", f"{r['pv_costs']:.2f}"])
    w.writerow([])
    w.writerow(["PV Benefits by Category"])
    labels = {"tts": "Travel Time Savings", "reliability": "Reliability",
              "voc": "Vehicle Operating Costs", "safety": "Safety",
              "env": "Environmental", "active": "Active Transport"}
    for k, lbl in labels.items():
        w.writerow([lbl, f"{r['pv_by_type'][k]:.2f}"])
    w.writerow([])
    w.writerow(["Year", "Undiscounted Cost ($M)", "Undiscounted Benefit ($M)",
                "Undiscounted Net ($M)", "Discounted Cost ($M)", "Discounted Benefit ($M)",
                "Discounted Net ($M)", "Cumulative Disc Net ($M)"])
    for y in range(r["total_years"]):
        w.writerow([
            y + 1, f"{r['annual_costs'][y]:.3f}", f"{r['annual_benefits'][y]:.3f}",
            f"{r['annual_net'][y]:.3f}", f"{r['disc_costs'][y]:.3f}",
            f"{r['disc_benefits'][y]:.3f}", f"{r['disc_net'][y]:.3f}",
            f"{r['cum_disc_net'][y]:.3f}",
        ])
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────────────────────
COLORS = {
    "tts": "#0d6efd",
    "reliability": "#6610f2",
    "voc": "#fd7e14",
    "safety": "#dc3545",
    "env": "#198754",
    "active": "#20c997",
    "cost": "#6c757d",
    "positive": "#198754",
    "negative": "#dc3545",
    "neutral": "#0d6efd",
}

TYPE_LABELS = {
    "tts": "Travel Time Savings",
    "reliability": "Reliability",
    "voc": "Vehicle Operating Costs",
    "safety": "Safety",
    "env": "Environmental",
    "active": "Active Transport",
}


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS — theme-aware (works in both light and dark mode)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* KPI metric cards — uses Streamlit theme variables */
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 0.75rem;
        padding: 1rem 1.25rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }
    div[data-testid="stMetric"] label {
        font-size: 0.8rem !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.75;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700;
    }
    /* Header banner — self-contained dark gradient with white text */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #0d6efd 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 0.75rem;
        margin-bottom: 1.5rem;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; }
    .main-header p { margin: 0.25rem 0 0 0; opacity: 0.85; font-size: 0.9rem; }
    /* Section headers — theme-aware */
    .section-header {
        background: var(--secondary-background-color);
        border-left: 4px solid var(--primary-color, #0d6efd);
        padding: 0.6rem 1rem;
        border-radius: 0 0.5rem 0.5rem 0;
        margin: 1.5rem 0 0.75rem 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text-color);
    }
    /* Sensitivity table — semi-transparent highlight works in both modes */
    .sensitivity-highlight { background-color: rgba(13, 110, 253, 0.1) !important; font-weight: 700; }
    .bcr-pass { color: #198754; font-weight: 700; }
    .bcr-fail { color: #dc3545; font-weight: 700; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — ALL INPUTS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Transport CBA")
    st.caption("TfNSW Economic Parameter Values (Jan 2025) · June 2024 prices")

    # --- Comparison mode toggle ---
    comparison_mode = st.toggle("Compare Scenarios", value=False, key="comparison_mode")

    # --- Project Details ---
    st.markdown("### Project Details")
    project_name = st.text_input("Project Name", value="Sample Road Upgrade")
    col1, col2 = st.columns(2)
    with col1:
        eval_period = st.number_input("Evaluation Period (years)", 1, 50, 30)
        base_year = st.number_input("Base Year", 2020, 2040, 2026)
    with col2:
        const_years = st.number_input("Construction Period (years)", 1, 10, 3)
        discount_rate = st.number_input("Discount Rate (%)", 0.0, 20.0, 7.0, step=0.5)
    context = st.selectbox("Context", ["urban", "rural"], format_func=str.title)

    st.divider()

    # --- Capital Costs ---
    st.markdown("### Capital Costs ($M, undiscounted)")
    col1, col2 = st.columns(2)
    with col1:
        cap_planning = st.number_input("Planning & Design", 0.0, value=5.0, step=0.1)
        cap_construction = st.number_input("Construction", 0.0, value=120.0, step=1.0)
    with col2:
        cap_land = st.number_input("Land Acquisition", 0.0, value=10.0, step=0.1)
        contingency = st.number_input("Contingency (%)", 0.0, 100.0, 20.0, step=1.0)

    # --- Recurrent Costs ---
    st.markdown("### Recurrent Costs ($M/year)")
    col1, col2 = st.columns(2)
    with col1:
        opex_maint = st.number_input("Maintenance", 0.0, value=1.5, step=0.1)
    with col2:
        opex_op = st.number_input("Operating", 0.0, value=0.8, step=0.1)
    residual = st.number_input("Residual Value ($M)", 0.0, value=15.0, step=0.1)

    st.divider()

    # --- Traffic & Demand ---
    st.markdown("### Traffic & Demand")
    aadt = st.number_input("Base AADT (vehicles/day)", 0, value=25000, step=100)
    col1, col2 = st.columns(2)
    with col1:
        traffic_growth = st.number_input("Traffic Growth (%/yr)", 0.0, 10.0, 1.5, step=0.1)
        avg_occupancy = st.number_input("Avg Occupancy", 1.0, 5.0, 1.4, step=0.1)
        pct_commute = st.number_input("% Commute Trips", 0.0, 100.0, 35.0, step=1.0)
        pct_heavy = st.number_input("% Heavy Vehicles", 0.0, 100.0, 8.0, step=0.5)
    with col2:
        trip_length = st.number_input("Avg Trip Length (km)", 0.1, value=12.0, step=0.1)
        speed_base = st.number_input("Base Speed (km/h)", 5.0, 130.0, 45.0, step=1.0)
        pct_business = st.number_input("% Business Trips", 0.0, 100.0, 15.0, step=1.0)
        speed_project = st.number_input("Project Speed (km/h)", 5.0, 130.0, 65.0, step=1.0)

    if pct_commute + pct_business > 100:
        st.error("Commute + Business trips cannot exceed 100%")

    st.divider()

    # --- Safety ---
    st.markdown("### Safety — Annual Crash Reductions")
    col1, col2 = st.columns(2)
    with col1:
        crash_fatal = st.number_input("Fatal", 0.0, value=0.3, step=0.01)
        crash_moderate = st.number_input("Moderate Injury", 0.0, value=3.0, step=0.1)
        crash_pdo = st.number_input("Property Damage Only", 0.0, value=10.0, step=0.5)
    with col2:
        crash_serious = st.number_input("Serious Injury", 0.0, value=1.5, step=0.1)
        crash_minor = st.number_input("Minor Injury", 0.0, value=5.0, step=0.1)

    st.divider()

    # --- Environmental ---
    st.markdown("### Environmental Externalities")
    co2_reduction = st.number_input("Annual CO₂ Reduction (tonnes)", 0.0, value=500.0, step=10.0)
    col1, col2 = st.columns(2)
    with col1:
        air_pollution_reduction = st.number_input("Air Pollution ($000s/yr)", 0.0, value=85.0, step=1.0)
    with col2:
        noise_reduction = st.number_input("Noise Cost ($000s/yr)", 0.0, value=30.0, step=1.0)

    # --- Active Transport ---
    st.markdown("### Active Transport")
    col1, col2 = st.columns(2)
    with col1:
        walk_km = st.number_input("Daily Walking (person-km)", 0.0, value=0.0, step=10.0)
    with col2:
        cycle_km = st.number_input("Daily Cycling (person-km)", 0.0, value=0.0, step=10.0)

    # --- Scenario B overrides (only shown when comparison mode is on) ---
    if comparison_mode:
        st.divider()
        st.markdown("### Scenario B — Overrides")
        st.caption("Parameters not overridden use Scenario A values")
        b_name = st.text_input("Project Name (B)", value=project_name + " — Alt", key="b_name")
        b_col1, b_col2 = st.columns(2)
        with b_col1:
            b_cap_construction = st.number_input("Construction ($M)", 0.0, value=cap_construction, step=1.0, key="b_construction")
            b_speed_project = st.number_input("Project Speed (km/h)", 5.0, 130.0, speed_project, step=1.0, key="b_speed_project")
            b_traffic_growth = st.number_input("Traffic Growth (%/yr)", 0.0, 10.0, traffic_growth, step=0.1, key="b_growth")
        with b_col2:
            b_contingency = st.number_input("Contingency (%)", 0.0, 100.0, contingency, step=1.0, key="b_contingency")
            b_aadt = st.number_input("Base AADT", 0, value=aadt, step=100, key="b_aadt")
            b_discount_rate = st.number_input("Discount Rate (%)", 0.0, 20.0, discount_rate, step=0.5, key="b_dr")


# ─────────────────────────────────────────────────────────────────────────────
# RUN CALCULATION
# ─────────────────────────────────────────────────────────────────────────────
inputs = {
    "context": context, "evaluation_period": eval_period,
    "construction_years": const_years, "discount_rate": discount_rate,
    "aadt": aadt, "traffic_growth": traffic_growth, "trip_length": trip_length,
    "occupancy": avg_occupancy, "pct_commute": pct_commute,
    "pct_business": pct_business, "pct_heavy": pct_heavy,
    "speed_base": speed_base, "speed_project": speed_project,
    "cap_planning": cap_planning, "cap_land": cap_land,
    "cap_construction": cap_construction, "contingency": contingency,
    "opex_maint": opex_maint, "opex_op": opex_op, "residual": residual,
    "crash_fatal": crash_fatal, "crash_serious": crash_serious,
    "crash_moderate": crash_moderate, "crash_minor": crash_minor,
    "crash_pdo": crash_pdo, "co2_reduction": co2_reduction,
    "air_pollution_reduction": air_pollution_reduction,
    "noise_reduction": noise_reduction, "walk_km": walk_km, "cycle_km": cycle_km,
}

results = calculate(inputs)

# Scenario B calculation (if comparison mode)
results_b = None
if comparison_mode:
    inputs_b = inputs.copy()
    inputs_b.update({
        "cap_construction": b_cap_construction,
        "contingency": b_contingency,
        "speed_project": b_speed_project,
        "aadt": b_aadt,
        "traffic_growth": b_traffic_growth,
        "discount_rate": b_discount_rate,
    })
    results_b = calculate(inputs_b)


# ─────────────────────────────────────────────────────────────────────────────
# PLOTLY LAYOUT DEFAULTS (transparent background for theme compatibility)
# ─────────────────────────────────────────────────────────────────────────────
PLOTLY_TRANSPARENT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")


# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="main-header">
    <h1>Transport Cost-Benefit Analysis</h1>
    <p>{project_name} · TfNSW Framework · {context.title()} · {discount_rate}% discount rate</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# KPI METRICS
# ─────────────────────────────────────────────────────────────────────────────
if comparison_mode and results_b:
    # Side-by-side KPIs for comparison mode
    col_a, col_b, col_delta = st.columns(3)
    with col_a:
        st.markdown(f"**Scenario A: {project_name}**")
        st.metric("NPV", format_m(results["npv"]),
                  delta="Positive" if results["npv"] >= 0 else "Negative",
                  delta_color="normal" if results["npv"] >= 0 else "inverse")
        st.metric("BCR", f"{results['bcr']:.2f}",
                  delta="Above 1.0" if results["bcr"] >= 1 else "Below 1.0",
                  delta_color="normal" if results["bcr"] >= 1 else "inverse")
        st.metric("PV Benefits", format_m(results["pv_benefits"]))
        st.metric("PV Costs", format_m(results["pv_costs"]))
        st.metric("FYRR", f"{results['fyrr']:.1f}%")
        pb_a = f"{results['payback_year']} yrs" if results["payback_year"] else "N/A"
        st.metric("Payback", pb_a)
    with col_b:
        st.markdown(f"**Scenario B: {b_name}**")
        st.metric("NPV", format_m(results_b["npv"]),
                  delta="Positive" if results_b["npv"] >= 0 else "Negative",
                  delta_color="normal" if results_b["npv"] >= 0 else "inverse")
        st.metric("BCR", f"{results_b['bcr']:.2f}",
                  delta="Above 1.0" if results_b["bcr"] >= 1 else "Below 1.0",
                  delta_color="normal" if results_b["bcr"] >= 1 else "inverse")
        st.metric("PV Benefits", format_m(results_b["pv_benefits"]))
        st.metric("PV Costs", format_m(results_b["pv_costs"]))
        st.metric("FYRR", f"{results_b['fyrr']:.1f}%")
        pb_b = f"{results_b['payback_year']} yrs" if results_b["payback_year"] else "N/A"
        st.metric("Payback", pb_b)
    with col_delta:
        st.markdown("**Delta (B - A)**")
        delta_npv = results_b["npv"] - results["npv"]
        st.metric("NPV Delta", format_m(delta_npv),
                  delta="Better" if delta_npv > 0 else "Worse",
                  delta_color="normal" if delta_npv > 0 else "inverse")
        delta_bcr = results_b["bcr"] - results["bcr"]
        st.metric("BCR Delta", f"{delta_bcr:+.2f}",
                  delta="Better" if delta_bcr > 0 else "Worse",
                  delta_color="normal" if delta_bcr > 0 else "inverse")
        delta_pvb = results_b["pv_benefits"] - results["pv_benefits"]
        st.metric("PV Benefits Delta", format_m(delta_pvb))
        delta_pvc = results_b["pv_costs"] - results["pv_costs"]
        st.metric("PV Costs Delta", format_m(delta_pvc))
        delta_fyrr = results_b["fyrr"] - results["fyrr"]
        st.metric("FYRR Delta", f"{delta_fyrr:+.1f}%")
else:
    # Standard single-scenario KPIs
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.metric("Net Present Value", format_m(results["npv"]),
                  delta="Positive" if results["npv"] >= 0 else "Negative",
                  delta_color="normal" if results["npv"] >= 0 else "inverse")
    with k2:
        st.metric("Benefit-Cost Ratio", f"{results['bcr']:.2f}",
                  delta="Above 1.0" if results["bcr"] >= 1 else "Below 1.0",
                  delta_color="normal" if results["bcr"] >= 1 else "inverse")
    with k3:
        st.metric("PV Benefits", format_m(results["pv_benefits"]))
    with k4:
        st.metric("PV Costs", format_m(results["pv_costs"]))
    with k5:
        st.metric("First Year Rate of Return", f"{results['fyrr']:.1f}%")
    with k6:
        pb = f"{results['payback_year']} years" if results["payback_year"] else "N/A"
        st.metric("Payback Period", pb)

# ─────────────────────────────────────────────────────────────────────────────
# EXPORT BUTTON
# ─────────────────────────────────────────────────────────────────────────────
csv_data = generate_csv(results, project_name)
st.download_button(
    "Download CSV Export",
    csv_data,
    file_name="cba-results.csv",
    mime="text/csv",
    use_container_width=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# TABBED LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
tab_dash, tab_cashflow, tab_sensitivity, tab_params = st.tabs(
    ["Dashboard", "Detailed Cashflow", "Sensitivity", "Parameters"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: DASHBOARD — Charts
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.markdown('<div class="section-header">Analysis Charts</div>', unsafe_allow_html=True)

    chart1, chart2 = st.columns(2)

    with chart1:
        st.subheader("Benefit Composition (PV $M)")
        pv = results["pv_by_type"]
        labels_list = []
        values_list = []
        colors_list = []
        for t in ["tts", "reliability", "voc", "safety", "env", "active"]:
            if pv[t] > 0:
                labels_list.append(TYPE_LABELS[t])
                values_list.append(round(pv[t], 2))
                colors_list.append(COLORS[t])
        fig_pie = go.Figure(data=[go.Pie(
            labels=labels_list, values=values_list,
            hole=0.45, marker_colors=colors_list,
            textinfo="label+percent", textposition="outside",
            pull=[0.03] * len(labels_list),
        )])
        fig_pie.update_layout(
            showlegend=True, height=400,
            margin=dict(t=20, b=20, l=20, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=-0.15),
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with chart2:
        st.subheader("NPV Waterfall ($M)")
        wf_labels = list(TYPE_LABELS.values()) + ["Total Benefits", "Costs", "NPV"]
        wf_values = [pv[t] for t in TYPE_LABELS] + [
            results["pv_benefits"], -results["pv_costs"], results["npv"]
        ]
        wf_measures = ["relative"] * 6 + ["total", "relative", "total"]
        fig_wf = go.Figure(go.Waterfall(
            x=wf_labels, y=wf_values, measure=wf_measures,
            connector={"line": {"color": "#ced4da"}},
            increasing={"marker": {"color": COLORS["positive"]}},
            decreasing={"marker": {"color": COLORS["negative"]}},
            totals={"marker": {"color": COLORS["neutral"]}},
            textposition="outside",
            text=[f"${v:.1f}M" for v in wf_values],
        ))
        fig_wf.update_layout(
            height=400, margin=dict(t=20, b=20, l=20, r=20),
            yaxis_title="$M", showlegend=False,
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_wf, use_container_width=True)

    # --- Row 2: Cashflow & Cumulative ---
    chart3, chart4 = st.columns(2)
    years = list(range(1, results["total_years"] + 1))

    with chart3:
        st.subheader("Annual Cashflow ($M, undiscounted)")
        fig_cf = go.Figure()
        fig_cf.add_trace(go.Bar(
            x=years, y=[-c for c in results["annual_costs"]],
            name="Costs", marker_color=COLORS["negative"], opacity=0.7,
        ))
        fig_cf.add_trace(go.Bar(
            x=years, y=results["annual_benefits"],
            name="Benefits", marker_color=COLORS["positive"], opacity=0.7,
        ))
        fig_cf.add_trace(go.Scatter(
            x=years, y=results["annual_net"],
            name="Net", mode="lines+markers",
            line=dict(color=COLORS["neutral"], width=2),
            marker=dict(size=4),
        ))
        fig_cf.update_layout(
            barmode="relative", height=400,
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="Year", yaxis_title="$M",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_cf, use_container_width=True)

    with chart4:
        st.subheader("Cumulative Discounted Net Benefits ($M)")
        fig_cum = go.Figure()
        fig_cum.add_trace(go.Scatter(
            x=years, y=results["cum_disc_net"],
            fill="tozeroy", mode="lines",
            line=dict(color=COLORS["neutral"], width=2.5),
            fillcolor="rgba(13, 110, 253, 0.15)",
            name="Scenario A" if comparison_mode else "Cumulative NPV",
        ))
        # Overlay Scenario B if comparison mode
        if comparison_mode and results_b:
            years_b = list(range(1, results_b["total_years"] + 1))
            fig_cum.add_trace(go.Scatter(
                x=years_b, y=results_b["cum_disc_net"],
                mode="lines", name="Scenario B",
                line=dict(color="#fd7e14", width=2.5, dash="dash"),
            ))
        fig_cum.add_hline(y=0, line_dash="dash", line_color="#6c757d", opacity=0.5)
        if results["payback_year"]:
            fig_cum.add_vline(
                x=results["payback_year"], line_dash="dot",
                line_color=COLORS["positive"], opacity=0.7,
                annotation_text=f"Payback: Year {results['payback_year']}",
                annotation_position="top right",
            )
        fig_cum.update_layout(
            height=400, margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="Year", yaxis_title="$M",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_cum, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: DETAILED CASHFLOW
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cashflow:
    st.markdown('<div class="section-header">Year-by-Year Cashflow</div>', unsafe_allow_html=True)

    view_mode = st.radio("Values", ["Undiscounted", "Discounted"], horizontal=True, key="cf_view")
    years_list = list(range(1, results["total_years"] + 1))

    if view_mode == "Undiscounted":
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Costs ($M)": [round(c, 3) for c in results["annual_costs"]],
            "Benefits ($M)": [round(b, 3) for b in results["annual_benefits"]],
            "TTS ($M)": [round(v, 3) for v in results["benefits_by_type"]["tts"]],
            "Reliability ($M)": [round(v, 3) for v in results["benefits_by_type"]["reliability"]],
            "VOC ($M)": [round(v, 3) for v in results["benefits_by_type"]["voc"]],
            "Safety ($M)": [round(v, 3) for v in results["benefits_by_type"]["safety"]],
            "Environmental ($M)": [round(v, 3) for v in results["benefits_by_type"]["env"]],
            "Active Transport ($M)": [round(v, 3) for v in results["benefits_by_type"]["active"]],
            "Net ($M)": [round(n, 3) for n in results["annual_net"]],
        })
    else:
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Costs ($M)": [round(c, 3) for c in results["disc_costs"]],
            "Benefits ($M)": [round(b, 3) for b in results["disc_benefits"]],
            "Net ($M)": [round(n, 3) for n in results["disc_net"]],
            "Cumulative Net ($M)": [round(c, 3) for c in results["cum_disc_net"]],
        })

    st.dataframe(df_cf, use_container_width=True, hide_index=True)

    # Download for this table
    cf_csv = df_cf.to_csv(index=False)
    st.download_button(
        f"Download {view_mode} Cashflow CSV",
        cf_csv,
        file_name=f"cashflow-{view_mode.lower()}.csv",
        mime="text/csv",
        key="dl_cashflow",
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: SENSITIVITY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sensitivity:
    # --- Existing sensitivity charts ---
    st.markdown('<div class="section-header">Sensitivity Analysis</div>', unsafe_allow_html=True)

    sen1, sen2 = st.columns(2)

    with sen1:
        st.subheader("Discount Rate Sensitivity (BCR)")
        dr_rates = sorted(results["sensitivity_dr"].keys())
        dr_bcrs = [results["sensitivity_dr"][r]["bcr"] for r in dr_rates]
        bar_colors = [COLORS["positive"] if b >= 1 else COLORS["negative"] for b in dr_bcrs]
        fig_dr = go.Figure(go.Bar(
            x=[f"{r}%" for r in dr_rates], y=dr_bcrs,
            marker_color=bar_colors,
            text=[f"{b:.2f}" for b in dr_bcrs], textposition="outside",
        ))
        fig_dr.add_hline(y=1.0, line_dash="dash", line_color="#6c757d",
                         annotation_text="BCR = 1.0", annotation_position="bottom right")
        fig_dr.update_layout(
            height=380, margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="Discount Rate", yaxis_title="BCR", showlegend=False,
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_dr, use_container_width=True)

    with sen2:
        st.subheader("Switching Values (% change for BCR = 1.0)")
        sw = results["switching"]
        if sw:
            sw_labels = list(sw.keys())
            sw_values = list(sw.values())
            sw_colors = [COLORS["negative"] if v < 0 else COLORS["positive"] for v in sw_values]
            fig_sw = go.Figure(go.Bar(
                y=sw_labels, x=sw_values, orientation="h",
                marker_color=sw_colors,
                text=[f"{v:+.1f}%" for v in sw_values], textposition="outside",
            ))
            fig_sw.add_vline(x=0, line_color="#6c757d")
            fig_sw.update_layout(
                height=380, margin=dict(t=20, b=20, l=60, r=60),
                xaxis_title="% Change Required", showlegend=False,
                **PLOTLY_TRANSPARENT,
            )
            st.plotly_chart(fig_sw, use_container_width=True)
        else:
            st.info("Insufficient data for switching values.")

    # --- Scenario Analysis Table ---
    st.subheader("Scenario Analysis")
    rows = []
    for r_val in sorted(results["sensitivity_dr"].keys()):
        v = results["sensitivity_dr"][r_val]
        rows.append({
            "Scenario": f"Discount Rate {r_val}%",
            "PV Benefits ($M)": round(v["pvb"], 1),
            "PV Costs ($M)": round(v["pvc"], 1),
            "NPV ($M)": round(v["npv"], 1),
            "BCR": round(v["bcr"], 2),
        })
    for label, v in results["scenarios"].items():
        rows.append({
            "Scenario": f"Demand {label}",
            "PV Benefits ($M)": round(v["pvb"], 1),
            "PV Costs ($M)": round(v["pvc"], 1),
            "NPV ($M)": round(v["npv"], 1),
            "BCR": round(v["bcr"], 2),
        })
    df_sens = pd.DataFrame(rows)

    def highlight_rows(row):
        styles = [""] * len(row)
        if f"Discount Rate {int(discount_rate)}%" in row["Scenario"] or row["Scenario"] == "Demand Central":
            styles = ["background-color: rgba(13, 110, 253, 0.1); font-weight: 700"] * len(row)
        bcr_idx = df_sens.columns.get_loc("BCR")
        if row["BCR"] >= 1:
            styles[bcr_idx] += "; color: #198754; font-weight: 700"
        else:
            styles[bcr_idx] += "; color: #dc3545; font-weight: 700"
        return styles

    styled = df_sens.style.apply(highlight_rows, axis=1).format({
        "PV Benefits ($M)": "{:.1f}",
        "PV Costs ($M)": "{:.1f}",
        "NPV ($M)": "{:.1f}",
        "BCR": "{:.2f}",
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # --- First-Year Benefit Breakdown ---
    st.markdown('<div class="section-header">First-Year Benefit Breakdown ($M)</div>', unsafe_allow_html=True)
    fy = results["first_year"]
    fy_cols = st.columns(7)
    for i, (key, label) in enumerate(TYPE_LABELS.items()):
        with fy_cols[i]:
            st.metric(label, f"${fy[key]:.2f}M")
    with fy_cols[6]:
        st.metric("Total", f"${fy['total']:.2f}M")

    # ─────────────────────────────────────────────────────────────────────────
    # INTERACTIVE SENSITIVITY SLIDERS + TORNADO CHART
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Interactive Parameter Sensitivity</div>', unsafe_allow_html=True)
    st.caption("Drag sliders to explore how each parameter affects the BCR. "
               "The tornado chart shows the BCR range from varying each parameter independently.")

    sens_params = {
        "AADT": {"key": "aadt", "min_val": max(1000, int(aadt * 0.5)), "max_val": int(aadt * 1.5),
                 "default": aadt, "step": 500},
        "Traffic Growth (%/yr)": {"key": "traffic_growth", "min_val": 0.0, "max_val": 5.0,
                                   "default": traffic_growth, "step": 0.1},
        "Construction Cost ($M)": {"key": "cap_construction", "min_val": max(1.0, cap_construction * 0.5),
                                    "max_val": cap_construction * 1.5, "default": cap_construction, "step": 1.0},
        "Discount Rate (%)": {"key": "discount_rate", "min_val": 3.0, "max_val": 12.0,
                               "default": discount_rate, "step": 0.5},
        "Evaluation Period (yrs)": {"key": "evaluation_period", "min_val": 10, "max_val": 50,
                                     "default": eval_period, "step": 1},
    }

    sl1, sl2 = st.columns(2)
    slider_values = {}
    for i, (label, cfg) in enumerate(sens_params.items()):
        col = sl1 if i % 2 == 0 else sl2
        with col:
            slider_values[cfg["key"]] = st.slider(
                label, min_value=cfg["min_val"], max_value=cfg["max_val"],
                value=cfg["default"], step=cfg["step"],
                key=f"sens_{cfg['key']}"
            )

    # Compute tornado data
    baseline_bcr = results["bcr"]
    tornado_data = []

    for label, cfg in sens_params.items():
        inputs_low = inputs.copy()
        inputs_low[cfg["key"]] = cfg["min_val"]
        bcr_low = calculate(inputs_low)["bcr"]

        inputs_high = inputs.copy()
        inputs_high[cfg["key"]] = cfg["max_val"]
        bcr_high = calculate(inputs_high)["bcr"]

        tornado_data.append({
            "param": label,
            "bcr_low": min(bcr_low, bcr_high),
            "bcr_high": max(bcr_low, bcr_high),
            "range": abs(bcr_high - bcr_low),
        })

    tornado_data.sort(key=lambda x: x["range"], reverse=True)

    fig_tornado = go.Figure()
    for item in tornado_data:
        fig_tornado.add_trace(go.Bar(
            y=[item["param"]],
            x=[item["bcr_high"] - baseline_bcr],
            base=[baseline_bcr],
            orientation="h",
            marker_color=COLORS["positive"],
            showlegend=False,
        ))
        fig_tornado.add_trace(go.Bar(
            y=[item["param"]],
            x=[item["bcr_low"] - baseline_bcr],
            base=[baseline_bcr],
            orientation="h",
            marker_color=COLORS["negative"],
            showlegend=False,
        ))

    fig_tornado.add_vline(x=baseline_bcr, line_dash="dash", line_color="#6c757d",
                          annotation_text=f"Baseline BCR: {baseline_bcr:.2f}")
    fig_tornado.update_layout(
        height=350, barmode="overlay",
        xaxis_title="BCR", yaxis_title="",
        margin=dict(t=30, b=30, l=150, r=30),
        **PLOTLY_TRANSPARENT,
    )
    st.plotly_chart(fig_tornado, use_container_width=True)

    # What-if calculation using all slider values simultaneously
    inputs_whatif = inputs.copy()
    for cfg in sens_params.values():
        inputs_whatif[cfg["key"]] = slider_values[cfg["key"]]
    results_whatif = calculate(inputs_whatif)

    wi1, wi2, wi3 = st.columns(3)
    with wi1:
        st.metric("What-If BCR", f"{results_whatif['bcr']:.2f}",
                  delta=f"{results_whatif['bcr'] - baseline_bcr:+.2f} vs baseline")
    with wi2:
        st.metric("What-If NPV", format_m(results_whatif["npv"]))
    with wi3:
        st.metric("What-If PV Benefits", format_m(results_whatif["pv_benefits"]))

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: PARAMETERS REFERENCE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_params:
    st.markdown('<div class="section-header">TfNSW Economic Parameter Values Reference</div>', unsafe_allow_html=True)
    st.caption("Source: TfNSW Economic Parameter Values (January 2025), indexed to June 2024 prices.")

    with st.expander("Value of Travel Time Savings ($/person-hour)"):
        vtts_df = pd.DataFrame({
            "Trip Purpose": ["Commute", "Business", "Other / Private"],
            "Urban": [f"${PARAMS['vtts']['urban'][k]:.2f}" for k in ["commute", "business", "other"]],
            "Rural": [f"${PARAMS['vtts']['rural'][k]:.2f}" for k in ["commute", "business", "other"]],
        })
        st.dataframe(vtts_df, hide_index=True, use_container_width=True)

    with st.expander("Vehicle Operating Costs — Urban ($/vehicle-km)"):
        speeds_urban = [40, 50, 60, 70, 80, 90, 100]
        voc_rows = []
        for s in speeds_urban:
            voc_rows.append({
                "Speed (km/h)": s,
                "Car": PARAMS["voc"]["urban"]["car"].get(s, "–"),
                "LGV": PARAMS["voc"]["urban"]["lgv"].get(s, "–"),
                "Rigid Truck": PARAMS["voc"]["urban"]["rigid"].get(s, "–"),
                "Articulated Truck": PARAMS["voc"]["urban"]["artic"].get(s, "–"),
            })
        st.dataframe(pd.DataFrame(voc_rows), hide_index=True, use_container_width=True)

    with st.expander("Vehicle Operating Costs — Rural ($/vehicle-km)"):
        speeds_rural = [60, 80, 100, 110]
        voc_rows_r = []
        for s in speeds_rural:
            voc_rows_r.append({
                "Speed (km/h)": s,
                "Car": PARAMS["voc"]["rural"]["car"].get(s, "–"),
                "LGV": PARAMS["voc"]["rural"]["lgv"].get(s, "–"),
                "Rigid Truck": PARAMS["voc"]["rural"]["rigid"].get(s, "–"),
                "Articulated Truck": PARAMS["voc"]["rural"]["artic"].get(s, "–"),
            })
        st.dataframe(pd.DataFrame(voc_rows_r), hide_index=True, use_container_width=True)

    with st.expander("Crash Costs ($/crash)"):
        crash_df = pd.DataFrame({
            "Severity": ["Fatal", "Serious Injury", "Moderate Injury", "Minor Injury", "Property Damage Only"],
            "Cost per Crash": [
                f"${PARAMS['crash_costs']['fatal']:,.0f}",
                f"${PARAMS['crash_costs']['serious']:,.0f}",
                f"${PARAMS['crash_costs']['moderate']:,.0f}",
                f"${PARAMS['crash_costs']['minor']:,.0f}",
                f"${PARAMS['crash_costs']['pdo']:,.0f}",
            ],
        })
        st.dataframe(crash_df, hide_index=True, use_container_width=True)

    with st.expander("Environmental Externalities"):
        env_df = pd.DataFrame([
            {"Parameter": "CO₂ Social Cost ($/tonne)", "Urban": f"${PARAMS['carbon_per_tonne']}", "Rural": f"${PARAMS['carbon_per_tonne']}"},
            {"Parameter": "Air Pollution — Car ($/veh-km)", "Urban": f"${PARAMS['air_pollution']['urban']['car']:.3f}", "Rural": f"${PARAMS['air_pollution']['rural']['car']:.3f}"},
            {"Parameter": "Air Pollution — Rigid Truck ($/veh-km)", "Urban": f"${PARAMS['air_pollution']['urban']['rigid']:.3f}", "Rural": f"${PARAMS['air_pollution']['rural']['rigid']:.3f}"},
            {"Parameter": "Noise — Car ($/veh-km)", "Urban": f"${PARAMS['noise']['urban']['car']:.3f}", "Rural": f"${PARAMS['noise']['rural']['car']:.3f}"},
            {"Parameter": "Noise — Heavy Vehicle ($/veh-km)", "Urban": f"${PARAMS['noise']['urban']['rigid']:.3f}", "Rural": f"${PARAMS['noise']['rural']['rigid']:.3f}"},
        ])
        st.dataframe(env_df, hide_index=True, use_container_width=True)

    with st.expander("Active Transport Health Benefits ($/person-km)"):
        health_df = pd.DataFrame({
            "Mode": ["Walking", "Cycling"],
            "Health Benefit": [f"${PARAMS['health_benefits']['walking']:.2f}", f"${PARAMS['health_benefits']['cycling']:.2f}"],
        })
        st.dataframe(health_df, hide_index=True, use_container_width=True)

    with st.expander("Other Key Parameters"):
        other_df = pd.DataFrame({
            "Parameter": ["Value of Statistical Life (VSL)", "Reliability Ratio", "Central Discount Rate",
                           "Low Discount Rate (sensitivity)", "High Discount Rate (sensitivity)", "Working Days per Year"],
            "Value": [f"${PARAMS['vsl']/1e6:.1f}M", f"{PARAMS['reliability_ratio']}", "7%", "4%", "10%",
                      f"{PARAMS['working_days_per_year']}"],
        })
        st.dataframe(other_df, hide_index=True, use_container_width=True)

    with st.expander("Default Traffic Composition (%)"):
        comp_df = pd.DataFrame({
            "Vehicle Type": ["Car", "Light Commercial", "Rigid Truck", "Articulated Truck"],
            "Urban": [f"{PARAMS['traffic_composition']['urban'][k]*100:.0f}%" for k in ["car", "lgv", "rigid", "artic"]],
            "Rural": [f"{PARAMS['traffic_composition']['rural'][k]*100:.0f}%" for k in ["car", "lgv", "rigid", "artic"]],
        })
        st.dataframe(comp_df, hide_index=True, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Transport CBA Dashboard · Parameters based on TfNSW Economic Parameter Values (Jan 2025) · For practitioner use · Not for public distribution")
