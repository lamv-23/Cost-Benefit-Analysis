"""
Transport CBA calculation engine (Streamlit-free).

Parameters from TfNSW Economic Parameter Values 2026.1 (July 2026).
All monetary values in June 2026 prices (AUD).
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math
import statistics

# Price base of every parameter and of the cost inputs
PRICE_YEAR = 2026
PRICE_LABEL = "June 2026"
# CPI Sydney (ABS A2325806K, EPV Table A4.1): June 2024 137.25, June 2026 145.822,
# used to index projects saved in June 2024 dollars to June 2026
CPI_JUNE_2024_TO_2026 = 145.82243724226805 / 137.25

# ─────────────────────────────────────────────────────────────────────────────
# TfNSW ECONOMIC PARAMETER VALUES 2026.1 (July 2026, June 2026 prices)
# ─────────────────────────────────────────────────────────────────────────────
PARAMS = {
    # Value of travel time, $ per vehicle-hour, by vehicle type: EPV Table 2.2 (urban)
    # and Table 2.3 (rural) averages, weighted by vehicle mix; they include the
    # private/business car split, freight value for trucks and bus passengers (20).
    "vtt_vehicle_hr": {
        "urban": {'Car': 37.7532, 'LCV': 46.2869, 'HCV': 76.7079, 'Bus': 498.0528},
        "rural": {'Car': 45.4085, 'LCV': 46.2855, 'HCV': 65.4297, 'Bus': 490.5889},
    },
    # Vehicle operating cost, $/km by average speed (km/h): TfNSW depreciation-
    # adjusted resource-cost models, EPV Table 3.9 (urban stop-start) and Table 3.10
    # (urban freeway). Car = medium car; LCV = courier van utility and 4WD; HCV =
    # all rigid, articulated and combination trucks; Bus = heavy bus; LCV and HCV
    # weighted by the EPV vehicle mix (Table 3.19, urban). Rural roads use the
    # freeway model weighted by the regional mix (an approximation: the EPV gives
    # rural VOC only as REVS model parameters).
    "voc": {'stop_start': {'Car': {20: 0.5287,
                            30: 0.428,
                            40: 0.3777,
                            50: 0.3474,
                            60: 0.3273,
                            70: 0.3129,
                            80: 0.3021,
                            90: 0.2937,
                            100: 0.287,
                            110: 0.2815},
                    'LCV': {20: 0.6989,
                            30: 0.5571,
                            40: 0.4862,
                            50: 0.4437,
                            60: 0.4153,
                            70: 0.3951,
                            80: 0.3799,
                            90: 0.3681,
                            100: 0.3586,
                            110: 0.3509},
                    'HCV': {20: 1.5665,
                            30: 1.3518,
                            40: 1.2445,
                            50: 1.1801,
                            60: 1.1371,
                            70: 1.1065,
                            80: 1.0835,
                            90: 1.0656,
                            100: 1.0513,
                            110: 1.0395},
                    'Bus': {20: 2.2388,
                            30: 1.7992,
                            40: 1.5795,
                            50: 1.4476,
                            60: 1.3597,
                            70: 1.2969,
                            80: 1.2498,
                            90: 1.2132,
                            100: 1.1839,
                            110: 1.1599}},
     'freeway': {'Car': {20: 0.2916,
                         30: 0.2754,
                         40: 0.2627,
                         50: 0.2533,
                         60: 0.2473,
                         70: 0.2446,
                         80: 0.2453,
                         90: 0.2493,
                         100: 0.2567,
                         110: 0.2675},
                 'LCV': {20: 0.359,
                         30: 0.3445,
                         40: 0.3338,
                         50: 0.3269,
                         60: 0.3238,
                         70: 0.3245,
                         80: 0.329,
                         90: 0.3374,
                         100: 0.3495,
                         110: 0.3654},
                 'HCV': {20: 0.732,
                         30: 0.696,
                         40: 0.673,
                         50: 0.663,
                         60: 0.666,
                         70: 0.682,
                         80: 0.711,
                         90: 0.7529,
                         100: 0.8079,
                         110: 0.8758},
                 'Bus': {20: 0.9882,
                         30: 0.9338,
                         40: 0.8918,
                         50: 0.8623,
                         60: 0.8452,
                         70: 0.8404,
                         80: 0.8481,
                         90: 0.8683,
                         100: 0.9008,
                         110: 0.9458}},
     'rural': {'Car': {20: 0.2916,
                       30: 0.2754,
                       40: 0.2627,
                       50: 0.2533,
                       60: 0.2473,
                       70: 0.2446,
                       80: 0.2453,
                       90: 0.2493,
                       100: 0.2567,
                       110: 0.2675},
               'LCV': {20: 0.359,
                       30: 0.3445,
                       40: 0.3338,
                       50: 0.3269,
                       60: 0.3238,
                       70: 0.3245,
                       80: 0.329,
                       90: 0.3374,
                       100: 0.3495,
                       110: 0.3654},
               'HCV': {20: 0.914,
                       30: 0.8725,
                       40: 0.846,
                       50: 0.8344,
                       60: 0.8378,
                       70: 0.8561,
                       80: 0.8894,
                       90: 0.9376,
                       100: 1.0008,
                       110: 1.079},
               'Bus': {20: 0.9882,
                       30: 0.9338,
                       40: 0.8918,
                       50: 0.8623,
                       60: 0.8452,
                       70: 0.8404,
                       80: 0.8481,
                       90: 0.8683,
                       100: 0.9008,
                       110: 0.9458}}},
    # Default crash cost per vkt = crash rate (EPV Table 5.5, crashes per 100 MVKT,
    # by environment and carriageway) × average cost per crash (Table 3.18,
    # NSW-funded or jointly funded). Each case's rates are set on the Traffic tab.
    "crash_rate_per_100mvkt": {'rural': {'divided': 26.6, 'single': 27.6}, 'urban': {'divided': 61.86, 'single': 82.49}},
    "cost_per_crash": {'joint': {'rural': 393010.25, 'urban': 187044.82},
     'nsw': {'rural': 311070.52, 'urban': 154147.29}},
    # Proportion of crash costs that are fatal, used only for the VSL sensitivity
    # (tool assumption, not from the EPV).
    "safety_severity_share": {
        "fatal": 0.36, "serious": 0.30, "minor": 0.20, "pdo": 0.14,
    },
    # Value of a statistical life (EPV Table 5.1): NSW values for NSW-funded
    # projects, ATAP-based values for jointly funded projects
    "vsl": {'atap': 9701634.38, 'nsw': 7275000},
    # Operating carbon, tonnes CO2-e per vkt: EPV Table 6.2 (car, bus) and Table 6.3
    # (LCV, HV) cents/vkt at the FY2026 core carbon value $139.66/t
    "carbon_t_per_vkt": {'Car': 0.00018214, 'LCV': 0.00026429, 'HCV': 0.00062143, 'Bus': 0.00083928},
    # Other externalities (air pollution, well-to-tank, noise, soil and water,
    # nature and landscape, urban effects, biodiversity), cents/vkt: EPV Tables
    # 6.5/6.6 (car, bus) and 6.7/6.8 (LCV, HV), urban and rural
    "externality_cents_vkt": {'urban': {'Car': 3.8164, 'LCV': 6.2268, 'HCV': 25.7204, 'Bus': 29.9058},
     'rural': {'Car': 2.5559, 'LCV': 2.7098, 'HCV': 11.8995, 'Bus': 7.2736}},
    "externality_breakdown_cents_vkt": {'urban': {'Car': {'Air pollution': 1.0957,
                       'WTT emissions and pollutions': 0.5504,
                       'Noise': 0.8633,
                       'Soil and water': 0.3652,
                       'Nature and landscape': 0.1992,
                       'Urban effects': 0.653,
                       'Biodiversity': 0.0896},
               'LCV': {'Air pollution': 3.1211,
                       'WTT emissions and pollutions': 0.6986,
                       'Noise': 1.0957,
                       'Soil and water': 0.498,
                       'Nature and landscape': 0.1992,
                       'Urban effects': 0.5755,
                       'Biodiversity': 0.0387},
               'HCV': {'Air pollution': 9.0423,
                       'WTT emissions and pollutions': 2.2017,
                       'Noise': 5.6556,
                       'Soil and water': 3.9511,
                       'Nature and landscape': 0.5312,
                       'Urban effects': 2.9329,
                       'Biodiversity': 1.4056},
               'Bus': {'Air pollution': 13.7571,
                       'WTT emissions and pollutions': 2.6462,
                       'Noise': 6.0983,
                       'Soil and water': 4.3274,
                       'Nature and landscape': 0.4538,
                       'Urban effects': 1.9147,
                       'Biodiversity': 0.7083}},
     'rural': {'Car': {'Air pollution': 0.01,
                       'WTT emissions and pollutions': 0.5504,
                       'Noise': 0.0089,
                       'Soil and water': 0.0387,
                       'Nature and landscape': 1.9479,
                       'Urban effects': 0.0,
                       'Biodiversity': 0.0},
               'LCV': {'Air pollution': 0.0312,
                       'WTT emissions and pollutions': 0.6986,
                       'Noise': 0.01,
                       'Soil and water': 0.0,
                       'Nature and landscape': 1.97,
                       'Urban effects': 0.0,
                       'Biodiversity': 0.0},
               'HCV': {'Air pollution': 0.9075,
                       'WTT emissions and pollutions': 0.1778,
                       'Noise': 0.0564,
                       'Soil and water': 1.4056,
                       'Nature and landscape': 5.2793,
                       'Urban effects': 0.0,
                       'Biodiversity': 4.0729},
               'Bus': {'Air pollution': 0.0,
                       'WTT emissions and pollutions': 2.6462,
                       'Noise': 0.0609,
                       'Soil and water': 0.0509,
                       'Nature and landscape': 4.5156,
                       'Urban effects': 0.0,
                       'Biodiversity': 0.0}}},
    # Active transport health benefits, $/km: EPV Table 7.1 (NSW Ministry of Health)
    "health_benefits": {'walking': 5.6924, 'cycling': 3.2264},
    # Reliability ratio: TfNSW recommended value 1.0 (EPV Table 11.8)
    "reliability_ratio": 1.0,
    "reliability_ratio_freight": 1.0,
    # Share of travel time savings attributed to reliability (proxy; no published
    # source verified). Reliability benefit = TTS × reliability ratio × this share.
    "reliability_share_of_tts": 0.3,
    # Road damage: EPV Table 8.1 unit cost of road maintenance, cents/vkt. Car =
    # Cars and motorcycles; LCV = Light rigid (LCV); HCV = Sub-total heavy vehicles;
    # Bus = Buses. EPV note: 46% of the cost is road repair and maintenance, 54%
    # road provision, so only the maintenance share is counted.
    "road_damage_cents_vkt": {'Car': 5.6076, 'LCV': 5.6076, 'HCV': 19.2843, 'Bus': 10.5468},
    "road_damage_maintenance_share": 0.46,
    # Annual change (%) in emissions per vehicle-km from the FY2026 EPV factors
    # (e.g. fleet electrification). 0 holds today's factors for the whole period.
    "emission_factor_change_pct": 0.0,
}


# Carbon values ($/tCO2-e, June 2026 $) by financial year: EPV Table 6.1 FY2026
# core value $139.6586 × the Table 6.4 adjustment factors. NSW Carbon Values
# (NSW Treasury TPG24-34) give the core BCR; National Carbon Values (Infrastructure
# Australia) give the second BCR. Years after 2050 hold the 2050 value.
CARBON_VALUES = {
    "nsw": {
        "label": "NSW Carbon Values (TPG24-34, June 2026 $)",
        "central": {2024: 138.59,
         2025: 138.59,
         2026: 139.66,
         2027: 141.79,
         2028: 146.06,
         2029: 155.65,
         2030: 174.84,
         2031: 208.95,
         2032: 255.86,
         2033: 302.77,
         2034: 336.89,
         2035: 356.08,
         2036: 365.67,
         2037: 369.94,
         2038: 372.07,
         2039: 373.13,
         2040: 373.13,
         2041: 373.13,
         2042: 373.13,
         2043: 373.13,
         2044: 373.13,
         2045: 373.13,
         2046: 373.13,
         2047: 373.13,
         2048: 373.13,
         2049: 373.13,
         2050: 373.13},
        "high": {2024: 245.2,
         2025: 245.2,
         2026: 246.27,
         2027: 248.4,
         2028: 252.66,
         2029: 262.26,
         2030: 286.78,
         2031: 333.69,
         2032: 394.46,
         2033: 454.16,
         2034: 501.07,
         2035: 534.11,
         2036: 556.5,
         2037: 573.56,
         2038: 588.49,
         2039: 602.34,
         2040: 616.2,
         2041: 629.0,
         2042: 641.79,
         2043: 654.58,
         2044: 668.44,
         2045: 681.24,
         2046: 694.03,
         2047: 706.82,
         2048: 720.68,
         2049: 733.47,
         2050: 746.27},
    },
    "national": {
        "label": "National Carbon Values (Infrastructure Australia, June 2026 $)",
        "central": {2024: 61.98,
         2025: 73.05,
         2026: 84.11,
         2027: 97.4,
         2028: 115.1,
         2029: 136.13,
         2030: 163.8,
         2031: 189.26,
         2032: 212.5,
         2033: 231.31,
         2034: 245.7,
         2035: 258.98,
         2036: 270.05,
         2037: 281.12,
         2038: 292.19,
         2039: 302.15,
         2040: 312.11,
         2041: 322.07,
         2042: 332.03,
         2043: 341.99,
         2044: 351.95,
         2045: 360.8,
         2046: 370.77,
         2047: 380.73,
         2048: 391.79,
         2049: 401.75,
         2050: 417.25},
        "low": {2024: 48.7,
         2025: 61.98,
         2026: 68.62,
         2027: 76.37,
         2028: 84.11,
         2029: 96.29,
         2030: 118.42,
         2031: 137.24,
         2032: 159.37,
         2033: 175.98,
         2034: 183.72,
         2035: 190.36,
         2036: 203.64,
         2037: 211.39,
         2038: 213.61,
         2039: 227.99,
         2040: 232.42,
         2041: 234.63,
         2042: 237.95,
         2043: 252.34,
         2044: 272.26,
         2045: 295.51,
         2046: 301.04,
         2047: 303.25,
         2048: 305.47,
         2049: 314.32,
         2050: 317.64},
    },
}


def carbon_value(basis: str, case: str, year: int) -> float:
    """$/tCO2-e for ``year`` from the ``basis`` ("nsw"|"national") ``case`` schedule."""
    sched = CARBON_VALUES[basis][case]
    return sched[min(max(year, min(sched)), max(sched))]


def crash_cost_per_vkt(environment: str, carriageway: str, funding: str = "nsw",
                       params: dict | None = None) -> float:
    """EPV default crash cost, $/vkt: crash rate (Table 5.5) × cost per crash (Table 3.18).

    ``environment`` "urban"|"rural", ``carriageway`` "divided"|"single",
    ``funding`` "nsw" (NSW-funded) or "joint" (NSW and federal).
    """
    p = params if params is not None else PARAMS
    rate = p["crash_rate_per_100mvkt"][environment][carriageway] / 1e8
    return rate * p["cost_per_crash"][funding][environment]


# Canonical vehicle type list for matrix inputs
VTYPES = ["Car", "LCV", "HCV", "Bus"]

# Default modelling years
DEFAULT_MODELLING_YEARS = [2026, 2031, 2041, 2056]


TYPE_LABELS = {
    "tts": "Travel time savings",
    "reliability": "Reliability",
    "voc": "Vehicle operating costs",
    "safety": "Safety",
    "env": "Environmental",
    "road_damage": "Road damage savings",
    "active": "Active transport",
    "recurrent_savings": "Recurrent cost savings",
    "upfront_carbon": "Upfront carbon emissions",
    "construction_disruption": "Construction disruption",
    "residual": "Residual value",
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
    """Value of ``row`` at index ``i``; past the end, the row's median.

    Only the opening-delay tests reach past the end. The median stands for a
    typical year, so a one-off renewal in the final year is not repeated.
    """
    if not row:
        return 0.0
    if i < len(row):
        return float(row[i])
    return float(statistics.median(row))


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


OLD_FILE_ERROR = (
    "This project file was saved in an older format and can't be opened. "
    "Please re-enter the project."
)


def validate_project_file(data: dict) -> str | None:
    """Return the old-file error text unless ``data`` is a current-format project."""
    if data.get("type") == "cba_project" and data.get("cost_format") == COST_FORMAT_VERSION:
        return None
    return OLD_FILE_ERROR


def project_price_year(data: dict) -> int:
    """Price year of a saved project's costs; files saved before June 2026 prices were June 2024."""
    return int(data.get("price_year", 2024))


def index_costs(cost_data: dict, base_case_costs: dict, factor: float) -> None:
    """Multiply every real-dollar cost input by ``factor`` in place (e.g. June 2024 → 2026).

    Indexes capital rows, contingencies, recurrent rows (options and base case),
    construction disruption and a manual residual value. Nominal outturn figures
    and upfront carbon (tonnes) are not dollars in the appraisal price base, so
    they are left alone.
    """
    for cost in cost_data.values():
        for cat in cost.get("capex_base", {}):
            cost["capex_base"][cat] = [v * factor for v in cost["capex_base"][cat]]
        for key in ("contingency_p50", "contingency_p90", "recurrent"):
            if key in cost:
                cost[key] = [v * factor for v in cost[key]]
        for key in ("construction_disbenefit_annual", "residual"):
            if cost.get(key):
                cost[key] = cost[key] * factor
    base_case_costs["recurrent"] = [v * factor for v in base_case_costs.get("recurrent", [])]


def discount_factor(rate: float, year: int) -> float:
    return 1.0 / math.pow(1 + rate / 100, year)


def benefit_cost_ratio(pv_benefits: float, pv_costs: float) -> float | None:
    """PV benefits ÷ PV costs, or ``None`` (not defined) when PV costs are zero or negative."""
    return pv_benefits / pv_costs if pv_costs > 0 else None


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
    base_costs: dict,
    annualisation: dict,
    safety_vkt_base: dict = None,
    safety_vkt_proj: dict = None,
    params: dict = None,
    scenario: dict | None = None,
) -> dict:
    """Compute CBA for one project case using the matrix traffic data model.

    Args:
        inputs:        Project config keys: context, evaluation_period,
                       construction_years, discount_rate, base_year.
        base_traffic:  traffic_case dict for the base case.
        proj_traffic:  traffic_case dict for this project case.
        cost:          cost_data entry for this project case (yearly cost rows).
        base_costs:    shared base case costs (``make_base_case_costs``).
        annualisation: annualisation factor and days_per_year per vehicle type.
        scenario:      optional sensitivity-test options (defaults in brackets):
                       ``capital`` ("p50"|"p90"), ``delay_years`` (0),
                       ``growth`` ("forecast"|"none"|"half"), ``cost_factor`` (1.0),
                       ``benefit_factor`` (1.0), ``discount_rate`` (None: use
                       ``inputs["discount_rate"]``). ``None`` is the central case.

    Costs per year are P50 capital + net recurrent cost (option − base case) when
    that is an increase in PV terms; a net saving is the "recurrent_savings"
    benefit line instead. Upfront carbon, construction disruption and residual
    value are benefit lines (the first two negative, the last at the end of the
    final year). Carbon is valued at the ``carbon_basis`` central schedule.
    ``inputs`` may also set ``zero_growth_after_last_year`` (default True),
    ``include_reliability`` and ``include_road_damage`` (default True) and
    ``carbon_basis`` ("nsw" default, or "national"). ``bcr`` is None when PV
    costs are zero or negative.

    Returns:
        Result dict with the same keys as the legacy ``calculate()`` output so
        existing dashboard/export code is compatible.
    """
    _p = params if params is not None else PARAMS
    ctx = inputs["context"]
    eval_period = inputs["evaluation_period"]
    const_years = inputs["construction_years"]
    discount_base_year = inputs.get("discount_base_year", 2026)
    construction_start_year = inputs.get("construction_start_year", discount_base_year)
    # Traffic is held at the last modelling year by default rather than extrapolated
    zero_growth_after_last_year = inputs.get("zero_growth_after_last_year", True)
    include_reliability = inputs.get("include_reliability", True)
    include_road_damage = inputs.get("include_road_damage", True)
    carbon_basis = inputs.get("carbon_basis", "nsw")

    scn = scenario or {}
    scn_capital = scn.get("capital", "p50")
    delay = int(scn.get("delay_years", 0) or 0)
    growth_mode = scn.get("growth", "forecast")
    cost_factor = scn.get("cost_factor", 1.0)
    benefit_factor = scn.get("benefit_factor", 1.0)
    dr = scn.get("discount_rate")
    if dr is None:
        dr = inputs["discount_rate"]

    # Annualisation: modelled-period VHT/VKT → annual (per vehicle type)
    ann_factors = {vt: annualisation[vt]["factor"] * annualisation[vt]["days"] for vt in VTYPES}

    # Value of travel time, $ per vehicle-hour (EPV averages incl. occupancy and freight)
    vtt_by_vtype = _p["vtt_vehicle_hr"][ctx]
    funding = inputs.get("funding", "nsw")
    # Urban roads use the stop-start or freeway VOC model; rural roads the rural table
    voc_model = "rural" if ctx == "rural" else inputs.get("voc_road_type", "stop_start")

    # Yearly capital (P50) and recurrent cost schedule, real $M
    schedule = build_cost_schedule(
        cost, base_costs, const_years, eval_period,
        capital=scn_capital, delay_years=delay,
    )
    capital_p50_total, capital_p90_total = (
        build_cost_schedule(cost, base_costs, const_years, eval_period, capital=k)["capital_total"]
        * cost_factor
        for k in ("p50", "p90")
    )
    schedule["capital"] = [v * cost_factor for v in schedule["capital"]]
    total_years = delay + const_years + eval_period
    # Start-of-year convention: discount exponent = eval_year - discount_base_year.
    base_offset = construction_start_year - discount_base_year

    # Recurrent costs are net (option − base case), scaled with costs in the cost
    # tests. A net increase is a cost; a net saving is a benefit (TfNSW CBA Guide
    # §6.8: cost savings are treated as a benefit). The side is set by the PV.
    net_recurrent = [
        (p - b) * cost_factor
        for p, b in zip(schedule["project_recurrent"], schedule["base_recurrent"])
    ]
    pv_net_recurrent = sum(v * discount_factor(dr, base_offset + t)
                           for t, v in enumerate(net_recurrent))
    recurrent_is_saving = pv_net_recurrent < 0
    recurrent_cost_row = [0.0] * total_years if recurrent_is_saving else list(net_recurrent)
    recurrent_saving_row = ([-v for v in net_recurrent] if recurrent_is_saving
                            else [0.0] * total_years)

    disruption_annual = cost.get("construction_disbenefit_annual", 0.0) or 0.0
    # Residual value: straight-line depreciation per ATAP T2 / TfNSW CBA Guidelines.
    # Land: full value retained (perpetual, no depreciation).
    # Construction (incl. attributed contingency): depreciated over construction_asset_life.
    # Planning/design: no residual (professional services, no physical asset).
    # Manual override: cost["residual"] > 0 takes precedence over auto-calculation.
    # Valued at the end of the final appraisal year (discounted one year further
    # than that year's other flows).
    _const_life = cost.get("construction_asset_life", 40)
    _remaining_frac = (
        max(0.0, (_const_life - eval_period) / _const_life) if _const_life > 0 else 0.0
    )
    _by_cat = schedule["capital_by_category"]
    _auto_residual = _by_cat["land"] + _by_cat["construction"] * _remaining_frac
    # The manual override is the user's explicit value and is never scaled.
    residual = (cost["residual"] if (cost.get("residual", 0.0) or 0.0) > 0.0
                else _auto_residual * cost_factor)

    # Carbon: EPV tonnes per vehicle-km, valued at the carbon value for each year
    _emit_growth = _p.get("emission_factor_change_pct", 0.0) / 100.0
    _rd_rates = _p.get("road_damage_cents_vkt", {})
    _rd_share = _p.get("road_damage_maintenance_share", 1.0)
    _rel_share = _p.get("reliability_share_of_tts", 0.3)

    modelling_years = base_traffic["years"]
    open_idx = delay + const_years   # timeline index of the opening year (Y0)
    opening_year = construction_start_year + open_idx

    def _traffic(values: list, ey: int, eval_year: int) -> float:
        """Traffic value for ``eval_year`` (``ey`` is its zero-growth-clamped year).

        ``growth_mode`` "none" holds opening-year values; "half" halves the
        forecast annual growth rate from the opening year.
        """
        v = interpolate_modelling_years(modelling_years, values, ey)
        if growth_mode == "forecast":
            return v
        ey0 = min(opening_year, modelling_years[-1]) if zero_growth_after_last_year else opening_year
        v0 = interpolate_modelling_years(modelling_years, values, ey0)
        n = eval_year - opening_year
        if growth_mode == "none" or v0 == 0 or n <= 0:
            return v0
        g = (v / v0) ** (1.0 / n) - 1.0
        return v0 * (1.0 + g / 2.0) ** n

    annual_costs: list = []
    annual_capital: list = []
    annual_recurrent: list = []
    annual_benefits: list = []
    annual_env_emit: list = []       # operating-carbon component of env (carbon sensitivity)
    annual_safety_fatal: list = []   # fatal component of safety benefit (used for VSL sensitivity)
    annual_carbon_t: list = []       # net tonnes saved: operating saving − upfront emitted
    _line_keys = ("tts", "reliability", "voc", "safety", "env", "road_damage", "active",
                  "recurrent_savings", "upfront_carbon", "construction_disruption", "residual")
    benefits_by_type: dict = {k: [] for k in _line_keys}
    for vt in VTYPES:
        benefits_by_type[f"tts_{vt}"] = []
    annual_net: list = []
    disc_costs: list = []
    disc_benefits: list = []
    disc_net: list = []
    cum_disc_net: list = []
    voc_out_of_range: dict = {}      # vtype → (min, max) average speed outside the VOC table

    pv_costs = 0.0
    pv_benefits = 0.0
    cum = 0.0
    payback_year = None

    for y in range(total_years):
        eval_year = construction_start_year + y
        discount_exp = base_offset + y
        df_factor = discount_factor(dr, discount_exp)
        carbon_price = carbon_value(carbon_basis, "central", eval_year)
        # Clamp traffic eval year to last modelling year when zero-growth is selected
        ey = min(eval_year, modelling_years[-1]) if zero_growth_after_last_year else eval_year
        cap_y = schedule["capital"][y]
        rec_y = recurrent_cost_row[y]
        cost_y = cap_y + rec_y
        b_tts = b_rel = b_voc = b_safety = b_env = b_env_emit = b_active = b_road = 0.0
        b_safety_fatal = 0.0
        op_carbon_t = 0.0
        b_tts_by_vt: dict = {vt: 0.0 for vt in VTYPES}
        b_recurrent = recurrent_saving_row[y]
        # Disbenefits (0.0 - x keeps zero years at +0.0, not -0.0)
        upfront_t = schedule["upfront_carbon_t"][y]
        b_carbon = 0.0 - upfront_t * carbon_price / 1e6
        b_disruption = 0.0 - disruption_annual if schedule["construction_years"][y] else 0.0
        b_residual = residual if y == total_years - 1 else 0.0

        if y >= open_idx:

            # ── TTS: per vehicle type ───────────────────────────────────────
            # Rule-of-Half: extract generated demand settings from cost dict
            gen_pct_global = cost.get("generated_demand_pct_global", 0.0)
            gen_pct_override = cost.get("generated_demand_pct_override", {})

            for vt in VTYPES:
                vht_base = _traffic(base_traffic[vt]["vht"], ey, eval_year)
                vht_proj = _traffic(proj_traffic[vt]["vht"], ey, eval_year)
                # Negative when the project is slower — a disbenefit, kept in the total
                annual_vht_saving = (vht_base - vht_proj) * ann_factors[vt]

                # Resolve per-vehicle-type generated demand % (override or global)
                gen_pct = gen_pct_override.get(vt) if gen_pct_override.get(vt) is not None else gen_pct_global

                # Split VHT delta: diverted vs generated
                diverted_vht = annual_vht_saving * (1.0 - gen_pct / 100.0)
                generated_vht = annual_vht_saving * (gen_pct / 100.0)

                # Calculate TTS for diverted (1.0x VTTS) and generated (0.5x VTTS)
                diverted_tts = diverted_vht * vtt_by_vtype[vt] / 1e6
                generated_tts = generated_vht * vtt_by_vtype[vt] * 0.5 / 1e6

                vt_tts = diverted_tts + generated_tts
                b_tts_by_vt[vt] = vt_tts
                b_tts += vt_tts

            # Reliability benefit (proxy): per-vehicle-type TTS × reliability ratio ×
            # reliability_share_of_tts (default 0.3; no published source verified).
            # Passenger (Car, Bus): reliability_ratio; freight (LCV, HCV):
            # reliability_ratio_freight. Off when include_reliability is False.
            b_rel = 0.0
            if include_reliability:
                for vt in VTYPES:
                    _rr = (_p["reliability_ratio_freight"] if vt in ("LCV", "HCV")
                           else _p["reliability_ratio"])
                    b_rel += b_tts_by_vt[vt] * _rr * _rel_share

            # ── VOC: per vehicle type, speed derived from VKT/VHT ──────────
            # Rule-of-Half: split VKT delta into diverted and generated
            for vt in VTYPES:
                voc_table = _p["voc"][voc_model].get(vt, {})
                if not voc_table:
                    continue

                vht_b = _traffic(base_traffic[vt]["vht"], ey, eval_year)
                vkt_b = _traffic(base_traffic[vt]["vkt"], ey, eval_year)
                vht_p = _traffic(proj_traffic[vt]["vht"], ey, eval_year)
                vkt_p = _traffic(proj_traffic[vt]["vkt"], ey, eval_year)

                spd_b = vkt_b / vht_b if vht_b > 0 else 0.0
                spd_p = vkt_p / vht_p if vht_p > 0 else 0.0
                # Speeds outside the table are clamped to its end values; record them
                _lo, _hi = min(voc_table), max(voc_table)
                for _s in (spd_b, spd_p):
                    if _s > 0 and (_s < _lo or _s > _hi):
                        _seen = voc_out_of_range.get(vt, (_s, _s))
                        voc_out_of_range[vt] = (min(_seen[0], _s), max(_seen[1], _s))

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
            # Without per-case rates, both cases use the EPV single-carriageway default
            _sv_default = {v: crash_cost_per_vkt(ctx, "single", funding, _p) for v in VTYPES}
            _sv_base = safety_vkt_base if safety_vkt_base is not None else _sv_default
            _sv_proj = safety_vkt_proj if safety_vkt_proj is not None else _sv_default
            for vt in VTYPES:
                vkt_b = _traffic(base_traffic[vt]["vkt"], ey, eval_year)
                vkt_p = _traffic(proj_traffic[vt]["vkt"], ey, eval_year)
                # Base VKT × base rate − project VKT × project rate
                b_safety += (vkt_b * _sv_base[vt] - vkt_p * _sv_proj[vt]) * ann_factors[vt] / 1e6
            # Fatal component: used for VSL sensitivity (scales this share ±, rest held fixed).
            b_safety_fatal = b_safety * _p["safety_severity_share"]["fatal"]

            # ── Environmental and road damage per vtype × VKT Δ ─────────────
            # No Rule-of-Half: externalities are counted on the full change in VKT.
            # Operating carbon: EPV t/vkt, adjusted by the annual emission-factor change
            # from FY2026, valued at this year's carbon value. Other externalities are
            # the EPV cents/vkt for this context.
            _emit_scale = (1.0 + _emit_growth) ** (eval_year - 2026)
            for vt in VTYPES:
                t_per_vkt = _p["carbon_t_per_vkt"][vt] * _emit_scale
                ext_rate = _p["externality_cents_vkt"][ctx][vt] / 100.0

                vkt_b = _traffic(base_traffic[vt]["vkt"], ey, eval_year)
                vkt_p = _traffic(proj_traffic[vt]["vkt"], ey, eval_year)
                vkt_delta = (vkt_b - vkt_p) * ann_factors[vt]
                op_carbon_t += vkt_delta * t_per_vkt
                b_env += vkt_delta * ext_rate / 1e6
                if include_road_damage:
                    b_road += vkt_delta * _rd_rates.get(vt, 0.0) / 100.0 * _rd_share / 1e6
            b_env_emit = op_carbon_t * carbon_price / 1e6
            b_env += b_env_emit

            # ── Active Transport: incremental walking/cycling health benefits ─
            # Inputs are steady-state incremental person-km/day (project − base).
            # Formula mirrors cba-engine.js: pkm_day × $/person-km × 365.
            _walk = cost.get("walk_pkm_day", 0.0)
            _cycle = cost.get("cycle_pkm_day", 0.0)
            b_active = (
                _walk * _p["health_benefits"]["walking"]
                + _cycle * _p["health_benefits"]["cycling"]
            ) * 365 / 1e6

        if benefit_factor != 1.0:
            # Scale transport benefits only; recurrent cost savings, upfront carbon,
            # construction disruption and residual value are held fixed.
            b_tts *= benefit_factor
            b_rel *= benefit_factor
            b_voc *= benefit_factor
            b_safety *= benefit_factor
            b_env *= benefit_factor
            b_env_emit *= benefit_factor
            b_road *= benefit_factor
            b_active *= benefit_factor
            b_safety_fatal *= benefit_factor
            op_carbon_t *= benefit_factor
            for vt in VTYPES:
                b_tts_by_vt[vt] *= benefit_factor

        line_values = (b_tts, b_rel, b_voc, b_safety, b_env, b_road, b_active,
                       b_recurrent, b_carbon, b_disruption, b_residual)
        benefit_y = sum(line_values)

        net = benefit_y - cost_y
        # The residual sits at the end of the final year: one more year of discounting
        disc_benefit_y = ((benefit_y - b_residual) * df_factor
                          + b_residual * discount_factor(dr, discount_exp + 1))
        annual_costs.append(cost_y)
        annual_capital.append(cap_y)
        annual_recurrent.append(rec_y)
        annual_benefits.append(benefit_y)
        annual_env_emit.append(b_env_emit)
        annual_safety_fatal.append(b_safety_fatal)
        annual_carbon_t.append(op_carbon_t - upfront_t)
        for k, v in zip(_line_keys, line_values):
            benefits_by_type[k].append(v)
        for vt in VTYPES:
            benefits_by_type[f"tts_{vt}"].append(b_tts_by_vt[vt])
        annual_net.append(net)
        disc_costs.append(cost_y * df_factor)
        disc_benefits.append(disc_benefit_y)
        disc_net.append(disc_benefit_y - cost_y * df_factor)
        pv_costs += cost_y * df_factor
        pv_benefits += disc_benefit_y
        cum += disc_benefit_y - cost_y * df_factor
        cum_disc_net.append(cum)
        if payback_year is None and cum >= 0 and y >= open_idx:
            payback_year = y + 1

    npv = pv_benefits - pv_costs
    bcr = benefit_cost_ratio(pv_benefits, pv_costs)
    first_op = open_idx if open_idx < total_years else 0
    # FYRR (First Year Rate of Return): net benefit in first operational year
    # expressed as a percentage of total undiscounted P50 capital cost.
    # Net benefit = gross benefits minus recurrent costs; excludes construction-period costs.
    # Source: TfNSW CBA Practitioner's Guide; ATAP T2 §5.3 (supplementary).
    _first_op_net = annual_benefits[first_op] - annual_costs[first_op]
    fyrr = (_first_op_net / capital_p50_total * 100) if capital_p50_total > 0 else 0.0

    def _pv(row: list, shift: int = 0) -> float:
        return sum(row[y] * discount_factor(dr, base_offset + y + shift) for y in range(total_years))

    pv_by_type = {t: _pv(benefits_by_type[t]) for t in benefits_by_type}
    pv_by_type["residual"] = _pv(benefits_by_type["residual"], shift=1)
    pv_capital = _pv(annual_capital)
    pv_recurrent = _pv(annual_recurrent)

    # Carbon sensitivity: revalue the net tonnes (operating saving − upfront
    # emitted) at each schedule; everything else is unchanged.
    def _carbon_pvb(price_of) -> float:
        return pv_benefits + sum(
            annual_carbon_t[y]
            * (price_of(construction_start_year + y)
               - carbon_value(carbon_basis, "central", construction_start_year + y)) / 1e6
            * discount_factor(dr, base_offset + y)
            for y in range(total_years)
        )

    sensitivity_carbon = {}
    _carbon_rows = [
        (f"{_basis_label} {_case}", (lambda yr, b=_b, c=_case: carbon_value(b, c, yr)), _b, _case)
        for _b, _basis_label in (("nsw", "NSW"), ("national", "National"))
        for _case in CARBON_VALUES[_b] if _case != "label"
    ]
    for _label, _price_of, _b, _case in _carbon_rows:
        s_pvb = _carbon_pvb(_price_of)
        sensitivity_carbon[_label] = {
            "pvb": s_pvb, "pvc": pv_costs,
            "npv": s_pvb - pv_costs,
            "bcr": benefit_cost_ratio(s_pvb, pv_costs),
            "basis": _b, "case": _case,
            "core": _b == carbon_basis and _case == "central",
        }
    bcr_national_carbon = sensitivity_carbon["National central"]["bcr"]

    # VSL sensitivity: scale only the fatal crash cost component of safety benefits.
    # Fatal share (default 36%) of the blended safety_vkt rate is isolated in annual_safety_fatal.
    # Other severity classes (serious, minor, PDO) are held at base values.
    # Source: EPV Table 5.1 VSL (NSW value for NSW-funded, ATAP-based for jointly
    # funded projects); sensitivity range per ATAP T2.
    _base_vsl_m = _p["vsl"]["nsw" if funding == "nsw" else "atap"] / 1e6
    sensitivity_vsl = {}
    for _name, _factor in [("Low", 0.7), ("Central", 1.0), ("High", 1.3), ("Very high", 2.0)]:
        _label = (f"{_name} (${_base_vsl_m * _factor:.1f}M)" if _factor == 1.0
                  else f"{_name} ({_factor:g}×, ${_base_vsl_m * _factor:.1f}M)")
        s_pvb = pv_benefits + (_factor - 1.0) * _pv(annual_safety_fatal)
        sensitivity_vsl[_label] = {
            "pvb": s_pvb, "pvc": pv_costs,
            "npv": s_pvb - pv_costs,
            "bcr": benefit_cost_ratio(s_pvb, pv_costs),
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
    _res_row = benefits_by_type["residual"]

    def _npv_at_rate(r_pct: float) -> float:
        return sum(
            (annual_benefits[y] - _res_row[y] - annual_costs[y])
            * discount_factor(r_pct, base_offset + y)
            + _res_row[y] * discount_factor(r_pct, base_offset + y + 1)
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
    fyrr_deferral_pass = (fyrr >= dr) if capital_p50_total > 0 else None

    return {
        "npv": npv, "bcr": bcr, "pv_benefits": pv_benefits, "pv_costs": pv_costs,
        "bcr_without_reliability": benefit_cost_ratio(
            pv_benefits - pv_by_type["reliability"], pv_costs),
        "bcr_national_carbon": bcr_national_carbon,
        "carbon_basis": carbon_basis,
        "recurrent_is_saving": recurrent_is_saving,
        "pv_net_recurrent": pv_net_recurrent,
        "voc_speed_out_of_range": voc_out_of_range,
        "fyrr": fyrr, "fyrr_deferral_pass": fyrr_deferral_pass,
        "irr": irr,
        "payback_year": payback_year,
        "capital_p50_total": capital_p50_total, "capital_p90_total": capital_p90_total,
        "residual": residual,
        "pv_capital": pv_capital, "pv_recurrent": pv_recurrent,
        "annual_costs": annual_costs, "annual_capital": annual_capital,
        "annual_recurrent": annual_recurrent, "annual_benefits": annual_benefits,
        "annual_net": annual_net,
        "disc_costs": disc_costs, "disc_benefits": disc_benefits, "disc_net": disc_net,
        "cum_disc_net": cum_disc_net,
        "pv_by_type": pv_by_type,
        "sensitivity_carbon": sensitivity_carbon,
        "sensitivity_vsl": sensitivity_vsl,
        "switching": switching,
        "const_years": const_years, "eval_period": eval_period,
        "total_years": total_years, "dr": dr,
        "benefits_by_type": benefits_by_type,
        "annual_env_emit": annual_env_emit,
        "first_year": {
            t: benefits_by_type[t][first_op] for t in benefits_by_type
        } | {"total": annual_benefits[first_op]},
    }


# Required TfNSW sensitivity tests: (label, scenario options passed to calculate_matrix).
# ``None`` is the central case; the cost/benefit factors use the true minus sign (U+2212).
REQUIRED_SENSITIVITY_TESTS = [
    ("Central", None),
    ("Discount rate 3%", {"discount_rate": 3}),
    ("Discount rate 4%", {"discount_rate": 4}),
    ("Discount rate 7%", {"discount_rate": 7}),
    ("Costs +20%", {"cost_factor": 1.2}),
    ("Costs \u221220%", {"cost_factor": 0.8}),
    ("Costs +40%", {"cost_factor": 1.4}),
    ("Costs \u221240%", {"cost_factor": 0.6}),
    ("Benefits +20%", {"benefit_factor": 1.2}),
    ("Benefits \u221220%", {"benefit_factor": 0.8}),
    ("Benefits +40%", {"benefit_factor": 1.4}),
    ("Benefits \u221240%", {"benefit_factor": 0.6}),
    ("P90 capital cost", {"capital": "p90"}),
    ("Opening delayed 1 year", {"delay_years": 1}),
    ("Opening delayed 3 years", {"delay_years": 3}),
    ("No traffic growth", {"growth": "none"}),
    ("Half traffic growth", {"growth": "half"}),
]


def run_required_sensitivities(
    inputs: dict,
    base_traffic: dict,
    proj_traffic: dict,
    cost: dict,
    base_costs: dict,
    annualisation: dict,
    safety_vkt_base: dict = None,
    safety_vkt_proj: dict = None,
    params: dict = None,
) -> list[dict]:
    """Run the TfNSW required sensitivity tests for one project case.

    Returns 17 rows, always in the same order, each
    ``{"test", "pvb", "pvc", "npv", "bcr", "central"}``. The discount-rate rows
    are always 3%, 4% and 7% whatever the central rate is.
    """
    rows = []
    for label, scenario in REQUIRED_SENSITIVITY_TESTS:
        r = calculate_matrix(
            inputs, base_traffic, proj_traffic, cost, base_costs, annualisation,
            safety_vkt_base=safety_vkt_base, safety_vkt_proj=safety_vkt_proj,
            params=params, scenario=scenario,
        )
        rows.append({
            "test": label,
            "pvb": r["pv_benefits"], "pvc": r["pv_costs"],
            "npv": r["npv"], "bcr": r["bcr"],
            "central": scenario is None,
        })
    return rows


def calculate_all_cases(
    inputs: dict,
    traffic_data: dict,
    cost_data: dict,
    base_case_costs: dict,
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
            base_costs=base_case_costs,
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
    base_case_costs: dict,
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
      - P50 construction capital (construction base + P50 contingency):
        Triangular(min, mode, max)

    Args:
        case_key:          e.g. ``"project_1"``
        inputs:            project config dict (same as calculate_matrix)
        traffic_data:      full traffic_data dict (keyed by case)
        cost_data:         full cost_data dict (keyed by case)
        base_case_costs:   shared base case costs
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
    # Same fallback as calculate_matrix: EPV single-carriageway crash cost
    _sv_default = {vt: crash_cost_per_vkt(inputs["context"], "single",
                                          inputs.get("funding", "nsw"), _p_base) for vt in VTYPES}

    def _scale_capital(factor: float) -> dict:
        """Copy of the case costs with P50 construction capital scaled by ``factor``."""
        c = copy.deepcopy(cost_orig)
        c["capex_base"]["construction"] = [v * factor for v in c["capex_base"]["construction"]]
        c["contingency_p50"] = [v * factor for v in c["contingency_p50"]]
        return c

    for i in range(n_simulations):
        # ── Perturb params ──────────────────────────────────────────────────
        p = copy.deepcopy(_p_base)
        for _ctx in ("urban", "rural"):
            for _vt in VTYPES:
                p["vtt_vehicle_hr"][_ctx][_vt] *= vtts_factors[i]

        sf = safety_factors[i]
        sv_base = {vt: (sv_base_orig or _sv_default)[vt] * sf for vt in VTYPES}
        sv_proj = {vt: (sv_proj_orig or _sv_default)[vt] * sf for vt in VTYPES}

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
        cost_s = _scale_capital(cost_factors[i])

        # ── Calculate ────────────────────────────────────────────────────────
        result = calculate_matrix(
            inputs=inputs,
            base_traffic=base_traffic_s,
            proj_traffic=proj_traffic_s,
            cost=cost_s,
            base_costs=base_case_costs,
            annualisation=annualisation,
            safety_vkt_base=sv_base,
            safety_vkt_proj=sv_proj,
            params=p,
        )
        npv_arr[i] = result["npv"]
        bcr_arr[i] = np.nan if result["bcr"] is None else result["bcr"]

    p10_npv, p25_npv, p50_npv, p75_npv, p90_npv = np.percentile(npv_arr, [10, 25, 50, 75, 90])
    p10_bcr, p25_bcr, p50_bcr, p75_bcr, p90_bcr = np.nanpercentile(bcr_arr, [10, 25, 50, 75, 90])

    # ── Tornado: one-at-a-time sensitivity around central values ────────────
    # Each parameter held at its P10 / P90 while others stay at median (factor=1)
    _central = calculate_matrix(
        inputs=inputs,
        base_traffic=base_traffic_orig,
        proj_traffic=proj_traffic_orig,
        cost=cost_orig,
        base_costs=base_case_costs,
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
                _p["vtt_vehicle_hr"][_ctx][_vt] *= vtts_f
        _sv_b = {vt: (sv_base_orig or _sv_default)[vt] * safety_f for vt in VTYPES}
        _sv_p = {vt: (sv_proj_orig or _sv_default)[vt] * safety_f for vt in VTYPES}
        _bt = _scale_traffic(base_traffic_orig, traffic_f)
        _pt = _scale_traffic(proj_traffic_orig, traffic_f)
        _c = _scale_capital(cost_f)
        return calculate_matrix(
            inputs=inputs, base_traffic=_bt, proj_traffic=_pt,
            cost=_c, base_costs=base_case_costs, annualisation=annualisation,
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

NOT_ENTERED = "not entered"
NOT_DEFINED = "–"  # BCR when PV costs are zero or negative

# Method notes written to the CSV so a reviewer can see the conventions used
METHOD_NOTES = (
    "Discounting: start-of-year convention, 1 / (1 + r)^(year - discount base year); "
    "residual value is discounted from the end of the final year.",
    "Recurrent costs: net of the base case. A net increase is a cost; a net saving is the "
    "'Recurrent cost savings' benefit (TfNSW CBA Guide 2024, section 6.8).",
    "Parameters: TfNSW Economic Parameter Values 2026.1 (July 2026), June 2026 prices.",
    "Travel time: EPV average value per vehicle-hour by vehicle type (Tables 2.2 urban, 2.3 rural).",
    "VOC: TfNSW depreciation-adjusted resource-cost models (EPV Tables 3.9 stop-start, 3.10 "
    "freeway); rural roads use the freeway model with the regional vehicle mix (approximation; "
    "the EPV gives rural VOC only as REVS model parameters).",
    "Carbon: operating and upfront carbon valued at NSW Carbon Values (TPG24-34) by year "
    "(EPV Tables 6.1, 6.4); a BCR with National Carbon Values is also reported.",
    "Safety: crash cost per vkt by case; EPV defaults = crash rate (Table 5.5) x cost per crash "
    "(Table 3.18, NSW-funded or jointly funded).",
    "Road damage: EPV Table 8.1, maintenance share only (46%).",
    "BCR shows '–' when PV costs are zero or negative (not defined); use NPV.",
)


def appraisal_summary(result: dict, cost: dict) -> dict:
    """Return the TfNSW-style appraisal summary for one option.

    The two outturn figures are nominal $M copied from ``cost`` exactly as
    entered (reporting only, never used in a calculation); a blank one shows
    ``"not entered"``. Every other figure is real June 2026 dollars.
    """
    def _outturn(key: str):
        v = cost.get(key)
        return NOT_ENTERED if v is None else v

    return {
        "P50 outturn capital (nominal $M)": _outturn("outturn_p50_nominal"),
        "P90 outturn capital (nominal $M)": _outturn("outturn_p90_nominal"),
        "PV capital ($M)": result["pv_capital"],
        "PV net recurrent costs ($M)": result["pv_recurrent"],
        "PV costs ($M)": result["pv_costs"],
        "PV benefits ($M)": result["pv_benefits"],
        "NPV ($M)": result["npv"],
        "BCR": result["bcr"],
        "BCR without reliability": result["bcr_without_reliability"],
        "BCR with National carbon values": result["bcr_national_carbon"],
        "Carbon values (core)": CARBON_VALUES[result["carbon_basis"]]["label"] + ", central",
        "Discounting": "Start of year; residual value at the end of the final year",
    }


def format_summary_value(key: str, value, screen: bool = False) -> str:
    """Format one appraisal summary value.

    The CSV (default) uses $M to 2 dp and BCR to 3 dp; ``screen=True`` uses $M to
    1 dp with thousands separators and BCR to 2 dp. Outturn figures are always
    shown exactly as entered.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return NOT_DEFINED
    if key.startswith(("P50 outturn", "P90 outturn")):
        return str(value)
    if key.startswith("BCR"):
        return f"{value:.2f}" if screen else f"{value:.3f}"
    return f"{value:,.1f}" if screen else f"{value:.2f}"


def generate_csv(results: dict, project_name: str, summary: dict,
                 sensitivity_rows: list) -> str:
    """Build the results CSV: summary, itemised PV, required sensitivity tests, cashflow."""
    buf = io.StringIO()
    w = csv.writer(buf)
    r = results
    safe_name = project_name.replace("\t", " ").replace("\r", " ")
    if safe_name.startswith(("=", "+", "-", "@", "\t")):
        safe_name = "'" + safe_name
    w.writerow(["Transport CBA Dashboard Export"])
    w.writerow(["Project", safe_name])
    w.writerow(["Discount Rate", f"{r['dr']}%"])
    w.writerow([f"All values are real {PRICE_LABEL} dollars, except the nominal outturn capital rows."])
    for note in METHOD_NOTES:
        w.writerow(["Method", note])
    w.writerow([])
    w.writerow(["Appraisal summary"])
    for k, v in summary.items():
        w.writerow([k, format_summary_value(k, v)])
    w.writerow([])
    w.writerow(["Itemised PV ($M)"])
    for k, lbl in TYPE_LABELS.items():
        w.writerow([lbl, f"{r['pv_by_type'][k]:.2f}"])
    w.writerow(["PV capital", f"{r['pv_capital']:.2f}"])
    w.writerow(["PV net recurrent costs", f"{r['pv_recurrent']:.2f}"])
    w.writerow([])
    w.writerow(["TfNSW required sensitivity tests"])
    w.writerow(["Test", "PV benefits ($M)", "PV costs ($M)", "NPV ($M)", "BCR"])
    for row in sensitivity_rows:
        w.writerow([row["test"], f"{row['pvb']:.2f}", f"{row['pvc']:.2f}",
                    f"{row['npv']:.2f}", format_summary_value("BCR", row["bcr"])])
    w.writerow([])
    w.writerow(["Cashflow by year ($M)"])
    w.writerow(["Year", "Capital", "Recurrent", "Benefits", "Net",
                "Discounted net", "Cumulative"])
    for y in range(r["total_years"]):
        w.writerow([
            y + 1, f"{r['annual_capital'][y]:.3f}", f"{r['annual_recurrent'][y]:.3f}",
            f"{r['annual_benefits'][y]:.3f}", f"{r['annual_net'][y]:.3f}",
            f"{r['disc_net'][y]:.3f}", f"{r['cum_disc_net'][y]:.3f}",
        ])
    return buf.getvalue()
