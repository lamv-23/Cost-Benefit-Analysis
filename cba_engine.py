"""
Transport CBA calculation engine (Streamlit-free).

Parameters based on TfNSW Economic Parameter Values (January 2025)
All monetary values in June 2024 prices (AUD)
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math

# ─────────────────────────────────────────────────────────────────────────────
# TfNSW ECONOMIC PARAMETER VALUES (Jan 2025, June 2024 prices)
# ─────────────────────────────────────────────────────────────────────────────
PARAMS = {
    # Value of travel time savings $/person-hr, by vehicle type.
    # Car/Bus use commute rate (personal travel); LCV/HCV use business rate (freight/commercial).
    # Source: TfNSW EPV Jan 2025, Table 3
    "vtts": {
        "urban": {"Car": 19.76, "LCV": 54.87, "HCV": 54.87, "Bus": 19.76},
        "rural": {"Car": 17.78, "LCV": 49.38, "HCV": 49.38, "Bus": 17.78},
    },
    # Vehicle occupancy (persons/vehicle). Multiplied by VHT saving to convert
    # vehicle-hours to person-hours before applying the per-person VTTS.
    # Car/Bus urban: 2014/15 HTS (Sydney), rural: ATAP 2016 PV2 pp. 16-19.
    # LCV: commercial driver (occasionally one passenger); HCV: driver only.
    # Bus: typical all-day average load (urban route / rural coach).
    # Source: TfNSW EPV Jan 2025, Tables 2.4 & 2.5; ATAP 2016 PV2
    "occupancy": {
        "urban": {"Car": 1.14, "LCV": 1.1, "HCV": 1.0, "Bus": 13.0},
        "rural": {"Car": 1.58, "LCV": 1.1, "HCV": 1.0, "Bus": 10.0},
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
    "safety_vkt": {
        "Car": 0.153,
        "LCV": 0.098,
        "HCV": 0.198,
        "Bus": 0.167,
    },
    # Proportion of blended safety_vkt rate attributable to each crash severity class.
    # Used to isolate the fatal component for VSL sensitivity testing.
    # Source: TfNSW EPV Jan 2025 crash unit costs × NSW crash rate distribution.
    "safety_severity_share": {
        "fatal": 0.36, "serious": 0.30, "minor": 0.20, "pdo": 0.14,
    },
    "vsl": 8_100_000,
    # Carbon shadow price used as the basis for emission_cost values below.
    # Source: TfNSW EPV Jan 2025 (June 2024 prices): $123/tCO₂e.
    # NOTE: NSW Treasury TPG24-34 mandates the NSW government carbon value;
    # as of June 2025 this was $135.74/tCO₂e. Verify against the EPV Excel
    # tool and update emission_cost proportionally if a newer EPV is adopted.
    # ATAP PV5 (2024) uses a separate target-consistent schedule (starts at
    # $56/tCO₂e in 2024 rising to $377 by 2050) — not applicable here.
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
    "reliability_ratio_freight": 0.6,  # LCV/HCV — lower than passenger per TfNSW EPV
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
}

# Phase 0b: Vehicle type mapping — UI labels to PARAMS internal keys
# Note: Bus approximated as artic for VOC/air/noise externality rates
VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "artic"}

# Separate mapping for emission_cost (uses "bus" key, not "artic")
EMISSION_VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "bus"}

# Separate mapping for air_pollution and noise (Bus approximated as "artic";
# kept explicit here so a future change to VTYPE_MAP won't silently affect env calcs)
AIR_NOISE_VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "artic"}

# Canonical vehicle type list for matrix inputs
VTYPES = ["Car", "LCV", "HCV", "Bus"]

# Default modelling years
DEFAULT_MODELLING_YEARS = [2026, 2031, 2041, 2056]


TYPE_LABELS = {
    "tts": "Travel Time Savings",
    "reliability": "Reliability",
    "voc": "Vehicle Operating Costs",
    "safety": "Safety",
    "env": "Environmental",
    "active": "Active Transport",
    "pavement": "Pavement Maintenance Savings",
}


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


COST_FORMAT_VERSION = 2
CAPEX_CATEGORIES = ("planning", "land", "construction")


def clean_row(values: list) -> list:
    """Return ``values`` as floats, treating ``None``, NaN and ``""`` as 0.0."""
    out = []
    for v in values:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            out.append(0.0)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        out.append(0.0 if math.isnan(f) else f)
    return out


def make_cost_data(n_project_cases: int, const_years: int, eval_period: int) -> dict:
    """Return cost_data dict keyed by project case (base has no cost entry here).

    ``C`` = ``const_years`` and ``E`` = ``eval_period``. Per project case:
        capex_base:   {"planning"|"land"|"construction": [$M per construction year] * C}
        contingency_p50 / contingency_p90: [$M per construction year] * C
        recurrent:    [$M per year] * (C + E)
        upfront_carbon_t: tonnes CO2-e
        outturn_p50_nominal / outturn_p90_nominal: reporting-only nominal $M (or None)
        construction_disbenefit_annual, construction_asset_life, residual,
        walk_pkm_day, cycle_pkm_day, generated_demand_pct_global,
        generated_demand_pct_override: {vtype: None}

    The legacy flat keys (cap_planning, opex_maint, ...) are kept alongside the
    new ones until the UI moves over to the yearly tables.
    """
    c, e = int(const_years), int(eval_period)
    template = {
        "capex_base": {cat: [0.0] * c for cat in CAPEX_CATEGORIES},
        "contingency_p50": [0.0] * c,
        "contingency_p90": [0.0] * c,
        "recurrent": [0.0] * (c + e),
        "upfront_carbon_t": 0.0,
        "outturn_p50_nominal": None,
        "outturn_p90_nominal": None,
        "construction_disbenefit_annual": 0.0,
        "construction_asset_life": 40,   # years; drives auto-calculated residual value
        "residual": 0.0,
        "walk_pkm_day": 0.0, "cycle_pkm_day": 0.0,
        "generated_demand_pct_global": 0.0,
        "generated_demand_pct_override": {vt: None for vt in VTYPES},
        # Legacy flat fields (removed once the UI uses the yearly tables)
        "cap_planning": 0.0, "cap_land": 0.0, "cap_construction": 0.0,
        "contingency_pct": 0.0, "opex_maint": 0.0, "opex_op": 0.0,
        "pavement_saving_annual": 0.0,
    }
    return {f"project_{i}": copy.deepcopy(template) for i in range(1, n_project_cases + 1)}


def make_base_case_costs(const_years: int, eval_period: int) -> dict:
    """Return the shared base-case cost dict: a recurrent row of C + E years."""
    return {"recurrent": [0.0] * (int(const_years) + int(eval_period))}


def _fit_row(row: list, n: int) -> list:
    row = list(row)[:n]
    return row + [0.0] * (n - len(row))


def fit_cost_rows(costs: dict, const_years: int, eval_period: int) -> None:
    """Resize cost rows in place: capex/contingency to C, recurrent to C + E.

    Existing entries are kept; new years are padded with 0.0. Works on project
    and base-case dicts; keys that are absent are ignored.
    """
    c = int(const_years)
    if "capex_base" in costs:
        for cat in list(costs["capex_base"]):
            costs["capex_base"][cat] = _fit_row(costs["capex_base"][cat], c)
    for key in ("contingency_p50", "contingency_p90"):
        if key in costs:
            costs[key] = _fit_row(costs[key], c)
    if "recurrent" in costs:
        costs["recurrent"] = _fit_row(costs["recurrent"], c + int(eval_period))


def _row_at(row: list, i: int) -> float:
    """Value of ``row`` at index ``i``, repeating the last value past the end."""
    if not row:
        return 0.0
    return float(row[i] if i < len(row) else row[-1])


def build_cost_schedule(
    cost: dict, base_costs: dict, const_years: int, eval_period: int,
    capital: str = "p50", delay_years: int = 0,
) -> dict:
    """Lay the yearly cost tables out on a timeline of N = D + C + E years.

    ``capital`` selects the contingency row ("p50" or "p90"). Construction is
    shifted by ``delay_years`` (D); recurrent costs follow the base case until
    construction starts. Upfront carbon is spread pro rata to P50 capital.
    """
    c, e, d = int(const_years), int(eval_period), int(delay_years)
    n = d + c + e
    cont_key = "contingency_p90" if capital == "p90" else "contingency_p50"

    def _cap_row(vals_list: list, i: int) -> float:
        return float(vals_list[i]) if i < len(vals_list) else 0.0

    base_by_cat = {
        cat: [_cap_row(cost["capex_base"].get(cat, []), i) for i in range(c)]
        for cat in CAPEX_CATEGORIES
    }
    base_year = [sum(base_by_cat[cat][i] for cat in CAPEX_CATEGORIES) for i in range(c)]
    cont_year = [_cap_row(cost.get(cont_key, []), i) for i in range(c)]
    p50_year = [base_year[i] + _cap_row(cost.get("contingency_p50", []), i) for i in range(c)]

    capital_row = [0.0] * n
    carbon_row = [0.0] * n
    p50_total = sum(p50_year)
    total_carbon = float(cost.get("upfront_carbon_t", 0.0) or 0.0)
    for i in range(c):
        capital_row[d + i] = base_year[i] + cont_year[i]
        if p50_total > 0:
            carbon_row[d + i] = total_carbon * p50_year[i] / p50_total
    if p50_total <= 0:
        carbon_row[d] = total_carbon

    recurrent = cost.get("recurrent", [])
    base_recurrent_row = base_costs.get("recurrent", [])
    base_recurrent = [_row_at(base_recurrent_row, t) for t in range(n)]
    project_recurrent = [
        base_recurrent[t] if t < d else _row_at(recurrent, t - d) for t in range(n)
    ]

    cont_total = sum(cont_year)
    cat_totals = {cat: sum(base_by_cat[cat]) for cat in CAPEX_CATEGORIES}
    base_total = sum(cat_totals.values())
    capital_by_category = {}
    for cat in CAPEX_CATEGORIES:
        if base_total > 0:
            share = cont_total * cat_totals[cat] / base_total
        else:
            share = cont_total if cat == "construction" else 0.0
        capital_by_category[cat] = cat_totals[cat] + share

    return {
        "capital": capital_row,
        "project_recurrent": project_recurrent,
        "base_recurrent": base_recurrent,
        "upfront_carbon_t": carbon_row,
        "construction_years": [d <= t < d + c for t in range(n)],
        "capital_by_category": capital_by_category,
        "capital_total": sum(capital_row),
    }


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


def _cagr_interpolate(v1: float, v2: float, y1: int, y2: int, eval_year: int) -> float:
    """CAGR-based interpolation/extrapolation between two modelling years.

    Mirrors the Excel formula: ((v2/v1)^(1/(y2-y1)))-1 applied as
    v1 * (v2/v1)^((eval_year-y1)/(y2-y1)).

    Edge cases:
    - y2 == y1: undefined interval, return v1.
    - v1 == 0 or v2 == 0: CAGR is undefined, so interpolate linearly instead,
      clamped at 0 for extrapolation (e.g. traffic starting from or declining to 0).
    """
    if y2 == y1:
        return float(v1)
    if v1 == 0 or v2 == 0:
        frac = (eval_year - y1) / (y2 - y1)
        return max(0.0, float(v1) + (float(v2) - float(v1)) * frac)
    return float(v1) * (float(v2) / float(v1)) ** ((eval_year - y1) / (y2 - y1))


def interpolate_modelling_years(modelling_years: list, values: list, eval_year: int) -> float:
    """CAGR interpolate (or extrapolate) a value for eval_year from modelling year data.

    Uses compound-growth interpolation matching the Excel CAGR formula:
        rate = (v2/v1)^(1/(y2-y1)) - 1
        value = v1 * (1+rate)^(eval_year - y1)
    Falls back to linear interpolation when either bracketing value is 0.
    """
    if len(modelling_years) == 0 or len(values) == 0:
        return 0.0
    if len(modelling_years) == 1:
        return float(values[0])

    years = modelling_years
    if eval_year <= years[0]:
        return _cagr_interpolate(values[0], values[1], years[0], years[1], eval_year)
    if eval_year >= years[-1]:
        return _cagr_interpolate(values[-2], values[-1], years[-2], years[-1], eval_year)

    for i in range(len(years) - 1):
        if years[i] <= eval_year <= years[i + 1]:
            return _cagr_interpolate(values[i], values[i + 1], years[i], years[i + 1], eval_year)

    return float(values[-1])


# ─────────────────────────────────────────────────────────────────────────────
# MATRIX CALCULATION ENGINE — Step 7
# ─────────────────────────────────────────────────────────────────────────────

def calculate_matrix(
    inputs: dict,
    base_traffic: dict,
    proj_traffic: dict,
    cost: dict,
    annualisation: dict,
    safety_vkt_base: dict = None,
    safety_vkt_proj: dict = None,
    params: dict = None,
) -> dict:
    """Compute CBA for one project case using the matrix traffic data model.

    Args:
        inputs:        Project config keys: context, evaluation_period,
                       construction_years, discount_rate, base_year.
        base_traffic:  traffic_case dict for the base case.
        proj_traffic:  traffic_case dict for this project case.
        cost:          cost_data entry for this project case.
        annualisation: annualisation factor and days_per_year per vehicle type.

    Returns:
        Result dict with the same keys as the legacy ``calculate()`` output so
        existing dashboard/export code is compatible.
    """
    _p = params if params is not None else PARAMS
    ctx = inputs["context"]
    eval_period = inputs["evaluation_period"]
    const_years = inputs["construction_years"]
    dr = inputs["discount_rate"]
    discount_base_year = inputs.get("discount_base_year", 2026)
    construction_start_year = inputs.get("construction_start_year", discount_base_year)
    zero_growth_after_last_year = inputs.get("zero_growth_after_last_year", False)

    # Annualisation: modelled-period VHT/VKT → annual (per vehicle type)
    ann_factors = {vt: annualisation[vt]["factor"] * annualisation[vt]["days"] for vt in VTYPES}

    # VTTS by vehicle type ($/person-hr)
    vtts_by_vtype = _p["vtts"][ctx]
    # Occupancy (persons/vehicle): converts VHT savings (veh-hrs) → person-hours
    occupancy_by_vtype = _p["occupancy"][ctx]

    # Capital and recurrent costs
    raw_cap = cost["cap_planning"] + cost["cap_land"] + cost["cap_construction"]
    total_capital = raw_cap * (1 + cost["contingency_pct"] / 100)
    annual_capital = total_capital / const_years if const_years > 0 else 0.0
    opex = cost["opex_maint"] + cost["opex_op"]
    # Residual value: straight-line depreciation per ATAP T2 / TfNSW CBA Guidelines.
    # Land: full value retained (perpetual, no depreciation).
    # Construction (incl. contingency): depreciated proportionally over construction_asset_life.
    # Planning/design: no residual (professional services, no physical asset).
    # Manual override: cost["residual"] > 0 takes precedence over auto-calculation.
    _const_life = cost.get("construction_asset_life", 40)
    _remaining_frac = (
        max(0.0, (_const_life - eval_period) / _const_life) if _const_life > 0 else 0.0
    )
    _cap_construction_with_cont = cost["cap_construction"] * (1 + cost["contingency_pct"] / 100)
    _auto_residual = cost["cap_land"] + _cap_construction_with_cont * _remaining_frac
    residual = cost["residual"] if cost.get("residual", 0.0) > 0.0 else _auto_residual

    modelling_years = base_traffic["years"]
    total_years = const_years + eval_period

    annual_costs: list = []
    annual_benefits: list = []
    annual_env_emit: list = []       # emission_cost component only (used for carbon sensitivity)
    annual_safety_fatal: list = []   # fatal component of safety benefit (used for VSL sensitivity)
    benefits_by_type: dict = {k: [] for k in ("tts", "tts_Car", "tts_LCV", "tts_HCV", "tts_Bus", "reliability", "voc", "safety", "env", "active", "pavement")}
    annual_net: list = []
    disc_costs: list = []
    disc_benefits: list = []
    disc_net: list = []
    cum_disc_net: list = []

    pv_costs = 0.0
    pv_benefits = 0.0
    cum = 0.0
    payback_year = None

    # Start-of-year convention: discount exponent = eval_year - discount_base_year.
    # First operational year has DF = 1.0 when discount_base_year = construction_start_year + const_years.
    base_offset = construction_start_year - discount_base_year

    for y in range(total_years):
        eval_year = construction_start_year + y
        discount_exp = base_offset + y
        df_factor = discount_factor(dr, discount_exp)
        # Clamp traffic eval year to last modelling year when zero-growth is selected
        ey = min(eval_year, modelling_years[-1]) if zero_growth_after_last_year else eval_year
        cost_y = 0.0
        b_tts = b_rel = b_voc = b_safety = b_env = b_env_emit = b_active = b_pavement = 0.0
        b_safety_fatal = 0.0
        b_tts_by_vt: dict = {vt: 0.0 for vt in VTYPES}

        if y < const_years:
            cost_y = annual_capital + cost.get("construction_disbenefit_annual", 0.0)
        else:
            cost_y = opex

            # ── TTS: per vehicle type ───────────────────────────────────────
            # Rule-of-Half: extract generated demand settings from cost dict
            gen_pct_global = cost.get("generated_demand_pct_global", 0.0)
            gen_pct_override = cost.get("generated_demand_pct_override", {})

            for vt in VTYPES:
                vht_base = interpolate_modelling_years(
                    modelling_years, base_traffic[vt]["vht"], ey
                )
                vht_proj = interpolate_modelling_years(
                    modelling_years, proj_traffic[vt]["vht"], ey
                )
                # Negative when the project is slower — a disbenefit, kept in the total
                annual_vht_saving = (vht_base - vht_proj) * ann_factors[vt]

                # Resolve per-vehicle-type generated demand % (override or global)
                gen_pct = gen_pct_override.get(vt) if gen_pct_override.get(vt) is not None else gen_pct_global

                # Split VHT delta: diverted vs generated
                diverted_vht = annual_vht_saving * (1.0 - gen_pct / 100.0)
                generated_vht = annual_vht_saving * (gen_pct / 100.0)

                # Calculate TTS for diverted (1.0x VTTS) and generated (0.5x VTTS)
                diverted_tts = diverted_vht * occupancy_by_vtype[vt] * vtts_by_vtype[vt] / 1e6
                generated_tts = generated_vht * occupancy_by_vtype[vt] * vtts_by_vtype[vt] * 0.5 / 1e6

                vt_tts = diverted_tts + generated_tts
                b_tts_by_vt[vt] = vt_tts
                b_tts += vt_tts

            # Reliability benefit: per-vehicle-type TTS × reliability_ratio × 0.3.
            # The 0.3 (30%) is the Austroads / TfNSW standard apportionment of
            # travel-time savings attributable to reliability improvement.
            # Passenger (Car, Bus): reliability_ratio (default 0.9, relative VTTS for reliability).
            # Freight (LCV, HCV): reliability_ratio_freight (default 0.6) — lower per TfNSW EPV,
            # reflecting that freight scheduling has less sensitivity to travel time variability.
            b_rel = 0.0
            for vt in VTYPES:
                _rr = (_p["reliability_ratio_freight"] if vt in ("LCV", "HCV")
                       else _p["reliability_ratio"])
                b_rel += b_tts_by_vt[vt] * _rr * 0.3

            # ── VOC: per vehicle type, speed derived from VKT/VHT ──────────
            # Rule-of-Half: split VKT delta into diverted and generated
            for vt in VTYPES:
                param_vt = VTYPE_MAP[vt]
                voc_table = _p["voc"][ctx].get(param_vt, {})
                if not voc_table:
                    continue

                vht_b = interpolate_modelling_years(modelling_years, base_traffic[vt]["vht"], ey)
                vkt_b = interpolate_modelling_years(modelling_years, base_traffic[vt]["vkt"], ey)
                vht_p = interpolate_modelling_years(modelling_years, proj_traffic[vt]["vht"], ey)
                vkt_p = interpolate_modelling_years(modelling_years, proj_traffic[vt]["vkt"], ey)

                spd_b = vkt_b / vht_b if vht_b > 0 else 0.0
                spd_p = vkt_p / vht_p if vht_p > 0 else 0.0

                voc_b = interpolate_voc(voc_table, spd_b) if spd_b > 0 else 0.0
                voc_p = interpolate_voc(voc_table, spd_p) if spd_p > 0 else 0.0

                annual_vkt_b = vkt_b * ann_factors[vt]
                annual_vkt_p = vkt_p * ann_factors[vt]

                # Resolve per-vehicle-type generated demand % (override or global)
                gen_pct = gen_pct_override.get(vt) if gen_pct_override.get(vt) is not None else gen_pct_global

                # Total base VOC minus total project VOC; diverted share at 1.0x,
                # generated share at 0.5x (same split as TTS)
                voc_saving = annual_vkt_b * voc_b - annual_vkt_p * voc_p
                diverted_voc = voc_saving * (1.0 - gen_pct / 100.0)
                generated_voc = voc_saving * (gen_pct / 100.0) * 0.5

                b_voc += (diverted_voc + generated_voc) / 1e6

            # ── Safety: $/VKT per vehicle type (per-case rates) ─────────────
            # No Rule-of-Half: crash costs are counted on the full change in VKT,
            # including generated trips (ATAP T2 — Rule-of-Half applies to user benefits only)
            _sv_base = safety_vkt_base if safety_vkt_base is not None else _p["safety_vkt"]
            _sv_proj = safety_vkt_proj if safety_vkt_proj is not None else _p["safety_vkt"]
            for vt in VTYPES:
                vkt_b = interpolate_modelling_years(modelling_years, base_traffic[vt]["vkt"], ey)
                vkt_p = interpolate_modelling_years(modelling_years, proj_traffic[vt]["vkt"], ey)
                # Base VKT × base rate − project VKT × project rate
                b_safety += (vkt_b * _sv_base[vt] - vkt_p * _sv_proj[vt]) * ann_factors[vt] / 1e6
            # Fatal component: used for VSL sensitivity (scales this share ±, rest held fixed).
            b_safety_fatal = b_safety * _p["safety_severity_share"]["fatal"]

            # ── Environmental: emission + air + noise per vtype × VKT Δ ────
            # No Rule-of-Half: externalities are counted on the full change in VKT
            for vt in VTYPES:
                emit_vt = EMISSION_VTYPE_MAP[vt]
                air_noise_vt = AIR_NOISE_VTYPE_MAP[vt]
                emit_rate = _p["emission_cost"][ctx].get(emit_vt, 0.0)
                air_rate = _p["air_pollution"][ctx].get(air_noise_vt, 0.0)
                noise_rate = _p["noise"][ctx].get(air_noise_vt, 0.0)

                vkt_b = interpolate_modelling_years(modelling_years, base_traffic[vt]["vkt"], ey)
                vkt_p = interpolate_modelling_years(modelling_years, proj_traffic[vt]["vkt"], ey)
                vkt_delta = (vkt_b - vkt_p) * ann_factors[vt]
                b_env += vkt_delta * (emit_rate + air_rate + noise_rate) / 1e6
                b_env_emit += vkt_delta * emit_rate / 1e6

            # ── Active Transport: incremental walking/cycling health benefits ─
            # Inputs are steady-state incremental person-km/day (project − base).
            # Formula mirrors cba-engine.js: pkm_day × $/person-km × 365.
            _walk = cost.get("walk_pkm_day", 0.0)
            _cycle = cost.get("cycle_pkm_day", 0.0)
            b_active = (
                _walk * _p["health_benefits"]["walking"]
                + _cycle * _p["health_benefits"]["cycling"]
            ) * 365 / 1e6

            # ── Pavement Maintenance Savings: road authority avoided cost ─────
            b_pavement = cost.get("pavement_saving_annual", 0.0)

        benefit_y = b_tts + b_rel + b_voc + b_safety + b_env + b_active + b_pavement
        if y == total_years - 1:
            benefit_y += residual

        net = benefit_y - cost_y
        annual_costs.append(cost_y)
        annual_benefits.append(benefit_y)
        annual_env_emit.append(b_env_emit)
        annual_safety_fatal.append(b_safety_fatal)
        for k, v in zip(
            ("tts", "reliability", "voc", "safety", "env", "active", "pavement"),
            (b_tts, b_rel, b_voc, b_safety, b_env, b_active, b_pavement),
        ):
            benefits_by_type[k].append(v)
        for vt in VTYPES:
            benefits_by_type[f"tts_{vt}"].append(b_tts_by_vt[vt])
        annual_net.append(net)
        disc_costs.append(cost_y * df_factor)
        disc_benefits.append(benefit_y * df_factor)
        disc_net.append(net * df_factor)
        pv_costs += cost_y * df_factor
        pv_benefits += benefit_y * df_factor
        cum += net * df_factor
        cum_disc_net.append(cum)
        if payback_year is None and cum >= 0 and y >= const_years:
            payback_year = y + 1

    npv = pv_benefits - pv_costs
    bcr = pv_benefits / pv_costs if pv_costs > 0 else 0.0
    first_op = const_years if const_years < total_years else 0
    # FYRR (First Year Rate of Return): net benefit in first operational year
    # expressed as a percentage of total undiscounted capital cost.
    # Net benefit = gross benefits minus opex; excludes construction-period costs.
    # Source: TfNSW CBA Practitioner's Guide; ATAP T2 §5.3 (supplementary).
    _first_op_net = annual_benefits[first_op] - annual_costs[first_op]
    fyrr = (_first_op_net / total_capital * 100) if total_capital > 0 else 0.0

    pv_by_type = {
        t: sum(benefits_by_type[t][y] * discount_factor(dr, base_offset + y) for y in range(total_years))
        for t in benefits_by_type
    }

    sensitivity_dr = {}
    # TfNSW CBA Guidelines / NSW Treasury TPG23-08 sensitivity rates:
    # 4% (low), 7% (base), 10% (high). ATAP T2 (2022) specifies the same core rates.
    # 3.5% = NSW Treasury long-run real risk-free reference rate (TPP20-07).
    for r in [3.5, 5, 7, 10]:
        s_pvb = sum(annual_benefits[y] * discount_factor(r, base_offset + y) for y in range(total_years))
        s_pvc = sum(annual_costs[y] * discount_factor(r, base_offset + y) for y in range(total_years))
        sensitivity_dr[r] = {
            "pvb": s_pvb, "pvc": s_pvc,
            "npv": s_pvb - s_pvc,
            "bcr": s_pvb / s_pvc if s_pvc > 0 else 0.0,
        }

    # Carbon price sensitivity: scale only the emission_cost component of env benefits.
    # Base carbon price: $123/tCO₂e (TfNSW EPV Jan 2025, June 2024 prices).
    # NSW Treasury TPG24-34 mandates $135.74/tCO₂e — included as a distinct scenario.
    _base_carbon = PARAMS["carbon_per_tonne"]  # 123
    sensitivity_carbon = {}
    for _label, _factor in [
        ("Low (0.5×, $62/t)", 0.5),
        ("Central ($123/t)", 1.0),
        (f"Treasury (${135.74}/t)", 135.74 / _base_carbon),
        ("High (2.0×, $246/t)", 2.0),
    ]:
        s_pvb = sum(
            (annual_benefits[y] + annual_env_emit[y] * (_factor - 1.0))
            * discount_factor(dr, base_offset + y)
            for y in range(total_years)
        )
        sensitivity_carbon[_label] = {
            "pvb": s_pvb, "pvc": pv_costs,
            "npv": s_pvb - pv_costs,
            "bcr": s_pvb / pv_costs if pv_costs > 0 else 0.0,
            "carbon_price": round(_base_carbon * _factor, 2),
        }

    # VSL sensitivity: scale only the fatal crash cost component of safety benefits.
    # Fatal share (default 36%) of the blended safety_vkt rate is isolated in annual_safety_fatal.
    # Other severity classes (serious, minor, PDO) are held at base values.
    # Source: TfNSW EPV Jan 2025 VSL = $8.1M; sensitivity range per ATAP T2.
    _base_vsl_m = PARAMS["vsl"] / 1e6  # 8.1 ($M)
    sensitivity_vsl = {}
    for _label, _factor in [
        ("Low (0.7×, $5.7M)", 0.7),
        ("Central ($8.1M)", 1.0),
        ("High (1.3×, $10.5M)", 1.3),
        ("Very High (2.0×, $16.2M)", 2.0),
    ]:
        s_pvb = sum(
            (annual_benefits[y] + annual_safety_fatal[y] * (_factor - 1.0))
            * discount_factor(dr, base_offset + y)
            for y in range(total_years)
        )
        sensitivity_vsl[_label] = {
            "pvb": s_pvb, "pvc": pv_costs,
            "npv": s_pvb - pv_costs,
            "bcr": s_pvb / pv_costs if pv_costs > 0 else 0.0,
            "vsl": round(_base_vsl_m * _factor, 2),
        }

    switching = {}
    if pv_benefits > 0 and pv_costs > 0:
        switching["Total Benefits"] = -((pv_benefits - pv_costs) / pv_benefits) * 100
        switching["Total Costs"] = ((pv_benefits - pv_costs) / pv_costs) * 100
        for t, label in TYPE_LABELS.items():
            if pv_by_type.get(t, 0) > 0:
                switching[label] = -((pv_benefits - pv_costs) / pv_by_type[t]) * 100

    # IRR — Internal Rate of Return.
    # Source: TfNSW CBA framework; ATAP T2 §5.3 (supplementary).
    # Find the real discount rate (%) at which NPV = 0 via bisection.
    # Uses the same start-of-year, base_offset convention as the main calculation.
    def _npv_at_rate(r_pct: float) -> float:
        return sum(
            (annual_benefits[y] - annual_costs[y]) * discount_factor(r_pct, base_offset + y)
            for y in range(total_years)
        )

    irr: float | None = None
    if _npv_at_rate(0.0) > 0:
        _lo, _hi = 0.0, 200.0
        if _npv_at_rate(_hi) < 0:
            for _ in range(60):
                _mid = (_lo + _hi) / 2.0
                if _npv_at_rate(_mid) > 0:
                    _lo = _mid
                else:
                    _hi = _mid
                if _hi - _lo < 1e-6:
                    break
            irr = round((_lo + _hi) / 2.0, 2)

    # FYRR deferral test per TfNSW CBA Guidelines (ATAP T2 supplementary):
    # proceed if FYRR >= discount rate; otherwise consider deferral.
    fyrr_deferral_pass = (fyrr >= dr) if total_capital > 0 else None

    # Benefit scenarios scale benefits only; residual value (an asset value) is held fixed
    _pv_residual = residual * discount_factor(dr, base_offset + total_years - 1) if total_years > 0 else 0.0
    scenarios = {}
    for label, factor in [("Low (-20%)", 0.8), ("Central", 1.0), ("High (+20%)", 1.2)]:
        s_pvb = (pv_benefits - _pv_residual) * factor + _pv_residual
        s_pvc = sum(annual_costs[y] * discount_factor(dr, base_offset + y) for y in range(total_years))
        scenarios[label] = {
            "pvb": s_pvb, "pvc": s_pvc,
            "npv": s_pvb - s_pvc,
            "bcr": s_pvb / s_pvc if s_pvc > 0 else 0.0,
        }

    return {
        "npv": npv, "bcr": bcr, "pv_benefits": pv_benefits, "pv_costs": pv_costs,
        "fyrr": fyrr, "fyrr_deferral_pass": fyrr_deferral_pass,
        "irr": irr,
        "payback_year": payback_year, "total_capital": total_capital,
        "annual_costs": annual_costs, "annual_benefits": annual_benefits,
        "annual_net": annual_net,
        "disc_costs": disc_costs, "disc_benefits": disc_benefits, "disc_net": disc_net,
        "cum_disc_net": cum_disc_net,
        "pv_by_type": pv_by_type, "sensitivity_dr": sensitivity_dr,
        "sensitivity_carbon": sensitivity_carbon,
        "sensitivity_vsl": sensitivity_vsl,
        "switching": switching, "scenarios": scenarios,
        "const_years": const_years, "eval_period": eval_period,
        "total_years": total_years, "dr": dr,
        "benefits_by_type": benefits_by_type,
        "annual_env_emit": annual_env_emit,
        "first_year": {
            t: benefits_by_type[t][first_op] for t in benefits_by_type
        } | {"total": annual_benefits[first_op]},
    }


def calculate_all_cases(
    inputs: dict,
    traffic_data: dict,
    cost_data: dict,
    annualisation: dict,
    safety_vkt_data: dict = None,
    params: dict = None,
) -> dict:
    """Run calculate_matrix for every active project case vs the base case."""
    n = inputs.get("n_project_cases", 1)
    results = {}
    for i in range(1, n + 1):
        case_key = f"project_{i}"
        results[case_key] = calculate_matrix(
            inputs=inputs,
            base_traffic=traffic_data["base_case"],
            proj_traffic=traffic_data[case_key],
            cost=cost_data[case_key],
            annualisation=annualisation,
            safety_vkt_base=safety_vkt_data.get("base_case") if safety_vkt_data else None,
            safety_vkt_proj=safety_vkt_data.get(case_key) if safety_vkt_data else None,
            params=params,
        )
    return results


# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO SIMULATION — Step 8b
# ─────────────────────────────────────────────────────────────────────────────

def run_monte_carlo(
    case_key: str,
    inputs: dict,
    traffic_data: dict,
    cost_data: dict,
    annualisation: dict,
    safety_vkt_data: dict = None,
    params: dict = None,
    n_simulations: int = 1000,
    seed: int = 42,
    vtts_cv: float = 0.20,
    safety_cv: float = 0.30,
    traffic_cv: float = 0.15,
    cost_overrun_min: float = 1.0,
    cost_overrun_mode: float = 1.10,
    cost_overrun_max: float = 1.40,
) -> dict:
    """Run Monte Carlo simulation for a single project case.

    Each iteration independently samples:
      - VTTS (all contexts/vehicle types): Normal(1, vtts_cv)
      - Safety $/VKT: Lognormal with sigma = safety_cv
      - Traffic VHT/VKT: Normal(1, traffic_cv), clamped > 0; one factor applied
        to both base and project so demand uncertainty moves them together
      - Capital construction cost: Triangular(min, mode, max)

    Args:
        case_key:          e.g. ``"project_1"``
        inputs:            project config dict (same as calculate_matrix)
        traffic_data:      full traffic_data dict (keyed by case)
        cost_data:         full cost_data dict (keyed by case)
        annualisation:     annualisation dict
        safety_vkt_data:   optional per-case safety rates
        params:            effective params (from build_effective_params())
        n_simulations:     number of iterations
        seed:              RNG seed for reproducibility
        vtts_cv:           coefficient of variation for VTTS sampling
        safety_cv:         CV for safety cost sampling (lognormal sigma)
        traffic_cv:        CV for traffic volume sampling
        cost_overrun_min/mode/max: triangular distribution bounds for capex factor

    Returns:
        dict with keys ``npv``, ``bcr`` (numpy arrays), percentile summaries,
        ``prob_npv_positive``, and per-parameter sensitivity arrays for tornado.
    """
    import numpy as np
    import copy

    rng = np.random.default_rng(seed)
    _p_base = params if params is not None else PARAMS

    npv_arr = np.empty(n_simulations)
    bcr_arr = np.empty(n_simulations)

    # Pre-draw all random factors for speed
    vtts_factors    = rng.normal(1.0, vtts_cv,     n_simulations).clip(0.01)
    safety_sigmas   = np.sqrt(np.log(1 + safety_cv**2))
    safety_means    = -0.5 * safety_sigmas**2
    safety_factors  = rng.lognormal(safety_means, safety_sigmas, n_simulations)
    traffic_factors = rng.normal(1.0, traffic_cv,  n_simulations).clip(0.01)
    cost_factors    = rng.triangular(cost_overrun_min, cost_overrun_mode, cost_overrun_max, n_simulations)

    base_traffic_orig = traffic_data["base_case"]
    proj_traffic_orig = traffic_data[case_key]
    cost_orig         = cost_data[case_key]
    sv_base_orig      = safety_vkt_data.get("base_case") if safety_vkt_data else None
    sv_proj_orig      = safety_vkt_data.get(case_key)    if safety_vkt_data else None

    for i in range(n_simulations):
        # ── Perturb params ──────────────────────────────────────────────────
        p = copy.deepcopy(_p_base)
        for _ctx in ("urban", "rural"):
            for _vt in VTYPES:
                p["vtts"][_ctx][_vt] *= vtts_factors[i]

        sf = safety_factors[i]
        sv_base = {vt: (sv_base_orig[vt] if sv_base_orig else p["safety_vkt"][vt]) * sf for vt in VTYPES}
        sv_proj = {vt: (sv_proj_orig[vt] if sv_proj_orig else p["safety_vkt"][vt]) * sf for vt in VTYPES}

        # ── Perturb traffic (same factor for base and project) ───────────────
        f_base = f_proj = traffic_factors[i]

        def _scale_traffic(orig: dict, factor: float) -> dict:
            tc = copy.deepcopy(orig)
            for vt in VTYPES:
                for metric in ("vht", "vkt"):
                    tc[vt][metric] = [v * factor for v in orig[vt][metric]]
            return tc

        base_traffic_s = _scale_traffic(base_traffic_orig, f_base)
        proj_traffic_s = _scale_traffic(proj_traffic_orig, f_proj)

        # ── Perturb construction cost ────────────────────────────────────────
        cost_s = dict(cost_orig)
        cost_s["cap_construction"] = cost_orig["cap_construction"] * cost_factors[i]

        # ── Calculate ────────────────────────────────────────────────────────
        result = calculate_matrix(
            inputs=inputs,
            base_traffic=base_traffic_s,
            proj_traffic=proj_traffic_s,
            cost=cost_s,
            annualisation=annualisation,
            safety_vkt_base=sv_base,
            safety_vkt_proj=sv_proj,
            params=p,
        )
        npv_arr[i] = result["npv"]
        bcr_arr[i] = result["bcr"]

    p10_npv, p25_npv, p50_npv, p75_npv, p90_npv = np.percentile(npv_arr, [10, 25, 50, 75, 90])
    p10_bcr, p25_bcr, p50_bcr, p75_bcr, p90_bcr = np.percentile(bcr_arr, [10, 25, 50, 75, 90])

    # ── Tornado: one-at-a-time sensitivity around central values ────────────
    # Each parameter held at its P10 / P90 while others stay at median (factor=1)
    _central = calculate_matrix(
        inputs=inputs,
        base_traffic=base_traffic_orig,
        proj_traffic=proj_traffic_orig,
        cost=cost_orig,
        annualisation=annualisation,
        safety_vkt_base=sv_base_orig,
        safety_vkt_proj=sv_proj_orig,
        params=_p_base,
    )
    central_npv = _central["npv"]

    def _npv_with(vtts_f=1.0, safety_f=1.0, traffic_f=1.0, cost_f=1.0):
        _p = copy.deepcopy(_p_base)
        for _ctx in ("urban", "rural"):
            for _vt in VTYPES:
                _p["vtts"][_ctx][_vt] *= vtts_f
        _sv_b = {vt: (sv_base_orig[vt] if sv_base_orig else _p_base["safety_vkt"][vt]) * safety_f for vt in VTYPES}
        _sv_p = {vt: (sv_proj_orig[vt] if sv_proj_orig else _p_base["safety_vkt"][vt]) * safety_f for vt in VTYPES}
        _bt = _scale_traffic(base_traffic_orig, traffic_f)
        _pt = _scale_traffic(proj_traffic_orig, traffic_f)
        _c = dict(cost_orig)
        _c["cap_construction"] = cost_orig["cap_construction"] * cost_f
        return calculate_matrix(
            inputs=inputs, base_traffic=_bt, proj_traffic=_pt,
            cost=_c, annualisation=annualisation,
            safety_vkt_base=_sv_b, safety_vkt_proj=_sv_p, params=_p,
        )["npv"]

    _vtts_p10_f   = float(np.percentile(vtts_factors, 10))
    _vtts_p90_f   = float(np.percentile(vtts_factors, 90))
    _safety_p10_f = float(np.percentile(safety_factors, 10))
    _safety_p90_f = float(np.percentile(safety_factors, 90))
    _traf_p10_f   = float(np.percentile(traffic_factors, 10))
    _traf_p90_f   = float(np.percentile(traffic_factors, 90))
    _cost_p10_f   = float(np.percentile(cost_factors, 10))
    _cost_p90_f   = float(np.percentile(cost_factors, 90))

    tornado = {
        "VTTS":             (_npv_with(vtts_f=_vtts_p10_f),   _npv_with(vtts_f=_vtts_p90_f)),
        "Safety cost/VKT":  (_npv_with(safety_f=_safety_p10_f), _npv_with(safety_f=_safety_p90_f)),
        "Traffic volumes":  (_npv_with(traffic_f=_traf_p10_f), _npv_with(traffic_f=_traf_p90_f)),
        "Capital cost":     (_npv_with(cost_f=_cost_p90_f),   _npv_with(cost_f=_cost_p10_f)),
    }

    return {
        "npv": npv_arr,
        "bcr": bcr_arr,
        "n_simulations": n_simulations,
        "central_npv": central_npv,
        "npv_percentiles": {"p10": p10_npv, "p25": p25_npv, "p50": p50_npv, "p75": p75_npv, "p90": p90_npv},
        "bcr_percentiles": {"p10": p10_bcr, "p25": p25_bcr, "p50": p50_bcr, "p75": p75_bcr, "p90": p90_bcr},
        "prob_npv_positive": float((npv_arr > 0).mean()),
        "prob_bcr_gt1":      float((bcr_arr > 1).mean()),
        "tornado": tornado,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def generate_csv(results: dict, project_name: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    r = results
    safe_name = project_name.replace("\t", " ").replace("\r", " ")
    if safe_name.startswith(("=", "+", "-", "@", "\t")):
        safe_name = "'" + safe_name
    w.writerow(["Transport CBA Dashboard Export"])
    w.writerow(["Project", safe_name])
    w.writerow(["Discount Rate", f"{r['dr']}%"])
    w.writerow(["NPV ($M)", f"{r['npv']:.2f}"])
    w.writerow(["BCR", f"{r['bcr']:.3f}"])
    w.writerow(["PV Benefits ($M)", f"{r['pv_benefits']:.2f}"])
    w.writerow(["PV Costs ($M)", f"{r['pv_costs']:.2f}"])
    w.writerow([])
    w.writerow(["PV Benefits by Category"])
    labels = {"tts": "Travel Time Savings", "reliability": "Reliability",
              "voc": "Vehicle Operating Costs", "safety": "Safety",
              "env": "Environmental", "active": "Active Transport",
              "pavement": "Pavement Maintenance Savings"}
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
