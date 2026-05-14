"""
Transport Cost-Benefit Analysis Dashboard
Parameters based on TfNSW Economic Parameter Values (January 2025)
All monetary values in June 2024 prices (AUD)
"""

__version__ = "1.0.0"

import html
import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import math
import io
import csv
import copy
import re
import os

# Optional: Excel template generation (Step 6) — requires openpyxl
try:
    import openpyxl  # noqa: F401
    _EXCEL_AVAILABLE = True
except ImportError:
    _EXCEL_AVAILABLE = False

# Custom drag-and-drop column mapper component
_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "column_mapper_component")
column_mapper = components.declare_component("column_mapper", path=_COMPONENT_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=f"Transport CBA Dashboard — TfNSW v{__version__}",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

# ── Auto-match helpers for drag-drop mapper ────────────────────────────────────
_VTYPE_ALIASES = {
    "Car": ["car", "cars", "private", "passenger", "light vehicle"],
    "LCV": ["lcv", "lgv", "light commercial", "light goods", "lav", "van", "vans"],
    "HCV": ["hcv", "hgv", "heavy", "truck", "trucks", "rigid", "articulated", "artic"],
    "Bus": ["bus", "buses", "coach", "coaches", "transit"],
}


def _auto_match_vtypes(detected: list) -> dict:
    """Return {detected_name: VTYPE} for values matching known aliases."""
    result = {}
    for name in detected:
        norm = name.lower().strip()
        for target, aliases in _VTYPE_ALIASES.items():
            if any(a in norm for a in aliases):
                result[name] = target
                break
    return result


def _auto_match_years(detected: list) -> dict:
    """Return {detected_col: year_int} for headers that contain a 4-digit year."""
    result = {}
    for name in detected:
        m = re.search(r'\b(19|20)\d{2}\b', str(name))
        if m:
            result[name] = int(m.group())
    return result


def _auto_match_cases(detected: list, n: int) -> dict:
    """Best-effort mapping of detected case strings to standard names."""
    standard = ["Base Case"] + [f"Project {i}" for i in range(1, n + 1)]
    result = {}
    assigned = set()
    for name in detected:
        norm = name.lower().strip()
        if any(k in norm for k in ("base", "do nothing", "reference", "without", "existing")):
            result[name] = "Base Case"
            assigned.add("Base Case")
    # Assign remaining detected cases to remaining standard names in order
    remaining_std = [s for s in standard if s not in assigned]
    remaining_det = [d for d in detected if d not in result]
    for det, std in zip(remaining_det, remaining_std):
        result[det] = std
    return result

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
        "construction_disbenefit_annual": 0.0,
        "construction_asset_life": 40,   # years; drives auto-calculated residual value
        "walk_pkm_day": 0.0, "cycle_pkm_day": 0.0,
        "pavement_saving_annual": 0.0,
    }
    return {f"project_{i}": dict(template) for i in range(1, n_project_cases + 1)}


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE DATA LOADER
# ─────────────────────────────────────────────────────────────────────────────

def _load_sample_data() -> None:
    """Pre-populate session state with a representative rural road upgrade scenario.

    Scenario: 2-lane rural highway bypass, Car-dominant with moderate HCV freight.
    Base case = existing alignment; Project 1 = new bypass with higher speeds.
    All values are illustrative only (not based on any real project).
    """
    years = [2026, 2031, 2041, 2056]
    st.session_state["modelling_years"] = years
    st.session_state["n_project_cases"] = 1

    td = make_traffic_data(years, 1)

    # ── Base Case (existing road: congested, longer route, more stops) ──────
    bc = td["base_case"]
    bc["Car"]  = {"vht": [1200.0, 1350.0, 1550.0, 1800.0],
                  "vkt": [85000.0, 96000.0, 110000.0, 128000.0],
                  "stops": [180.0, 200.0, 225.0, 260.0],
                  "demand": [8500.0, 9600.0, 11000.0, 12800.0]}
    bc["LCV"]  = {"vht": [95.0, 107.0, 123.0, 143.0],
                  "vkt": [7200.0, 8100.0, 9300.0, 10800.0],
                  "stops": [12.0, 14.0, 16.0, 19.0],
                  "demand": [720.0, 810.0, 930.0, 1080.0]}
    bc["HCV"]  = {"vht": [120.0, 135.0, 155.0, 180.0],
                  "vkt": [9500.0, 10700.0, 12300.0, 14300.0],
                  "stops": [8.0, 9.0, 10.0, 12.0],
                  "demand": [480.0, 540.0, 620.0, 720.0]}
    bc["Bus"]  = {"vht": [18.0, 20.0, 23.0, 27.0],
                  "vkt": [1400.0, 1580.0, 1810.0, 2110.0],
                  "stops": [90.0, 100.0, 115.0, 133.0],
                  "demand": [1200.0, 1350.0, 1550.0, 1800.0]}

    # ── Project 1 (bypass: shorter route, fewer stops, free-flow) ───────
    # VKT and VHT both decrease — benefits across TTS, VOC, safety, env.
    p1 = td["project_1"]
    p1["Car"]  = {"vht": [980.0, 1100.0, 1270.0, 1480.0],
                  "vkt": [78000.0, 88000.0, 101000.0, 118000.0],
                  "stops": [30.0, 34.0, 39.0, 45.0],
                  "demand": [8200.0, 9300.0, 10700.0, 12400.0]}
    p1["LCV"]  = {"vht": [78.0, 88.0, 101.0, 117.0],
                  "vkt": [6600.0, 7400.0, 8500.0, 9900.0],
                  "stops": [2.0, 2.0, 3.0, 3.0],
                  "demand": [680.0, 760.0, 880.0, 1020.0]}
    p1["HCV"]  = {"vht": [95.0, 107.0, 123.0, 143.0],
                  "vkt": [8200.0, 9200.0, 10600.0, 12300.0],
                  "stops": [2.0, 2.0, 2.0, 3.0],
                  "demand": [420.0, 470.0, 540.0, 630.0]}
    p1["Bus"]  = {"vht": [14.0, 16.0, 18.0, 21.0],
                  "vkt": [1100.0, 1240.0, 1420.0, 1650.0],
                  "stops": [15.0, 17.0, 20.0, 23.0],
                  "demand": [1050.0, 1180.0, 1360.0, 1580.0]}

    st.session_state["traffic_data"] = td

    # ── Costs (Project 1) ──────────────────────────────────────────────────
    st.session_state["cost_data"] = {
        "project_1": {
            "cap_planning": 5.0,
            "cap_land": 12.0,
            "cap_construction": 85.0,
            "contingency_pct": 15.0,
            "opex_maint": 1.8,
            "opex_op": 0.4,
            "residual": 0.0,                  # 0 = use auto-calculated residual
            "construction_disbenefit_annual": 0.0,
            "construction_asset_life": 40,
            "walk_pkm_day": 800.0, "cycle_pkm_day": 400.0,
            "pavement_saving_annual": 0.3,
        }
    }

    # ── Safety rates — keep defaults from PARAMS ───────────────────────────
    _case_keys = ["base_case", "project_1"]
    st.session_state["safety_vkt_data"] = {
        ck: dict(PARAMS["safety_vkt"]) for ck in _case_keys
    }

    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# SAVE / LOAD PROJECT
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_project() -> dict:
    """Serialise all project state to a JSON-compatible dict."""
    keys_to_save = [
        "traffic_data", "cost_data", "safety_vkt_data", "crash_data",
        "annualisation", "modelling_years", "n_project_cases",
        "safety_mode", "env_mode", "reliability_mode", "show_advanced",
        "project_name",
    ]
    data = {"version": __version__, "type": "cba_project"}
    for k in keys_to_save:
        if k in st.session_state:
            data[k] = st.session_state[k]
    for k in list(st.session_state.keys()):
        if k.startswith("param_"):
            data[k] = st.session_state[k]
    return data


def _deserialise_project(data: dict) -> None:
    """Restore project state from a JSON dict."""
    if data.get("type") != "cba_project":
        st.error("Invalid file: not a CBA project export.")
        return
    if data.get("version") != __version__:
        st.warning(f"File version {data.get('version')} differs from app version {__version__}. Some data may not load correctly.")
    for k in ("traffic_data", "cost_data", "safety_vkt_data", "crash_data",
              "annualisation", "modelling_years", "n_project_cases",
              "safety_mode", "env_mode", "reliability_mode", "show_advanced"):
        if k in data:
            st.session_state[k] = data[k]
    for k in list(data.keys()):
        if k.startswith("param_"):
            st.session_state[k] = data[k]
    st.session_state["n_project_cases"] = data.get("n_project_cases", 1)
    st.success("Project loaded successfully!")


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


def _cagr_interpolate(v1: float, v2: float, y1: int, y2: int, eval_year: int) -> float:
    """CAGR-based interpolation/extrapolation between two modelling years.

    Mirrors the Excel formula: ((v2/v1)^(1/(y2-y1)))-1 applied as
    v1 * (v2/v1)^((eval_year-y1)/(y2-y1)).

    Edge cases:
    - y2 == y1: undefined interval, return v1.
    - v1 == 0: no base to grow from; return 0 for all years.
    - v2 == 0: traffic declines to zero; interpolate linearly to 0 then hold at 0
      (CAGR is undefined when the end-value is 0).
    """
    if y2 == y1:
        return float(v1)
    if v1 == 0:
        return 0.0
    if v2 == 0:
        # Linear decline to zero over [y1, y2]; clamp at 0 for extrapolation beyond y2.
        frac = (eval_year - y1) / (y2 - y1)
        return float(v1) * max(0.0, 1.0 - frac)
    return float(v1) * (float(v2) / float(v1)) ** ((eval_year - y1) / (y2 - y1))


def interpolate_modelling_years(modelling_years: list, values: list, eval_year: int) -> float:
    """CAGR interpolate (or extrapolate) a value for eval_year from modelling year data.

    Uses compound-growth interpolation matching the Excel CAGR formula:
        rate = (v2/v1)^(1/(y2-y1)) - 1
        value = v1 * (1+rate)^(eval_year - y1)
    Returns 0 when either bracketing value is 0.
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
# MATRIX UI HELPERS — Step 3
# ─────────────────────────────────────────────────────────────────────────────

def _style_incr(val):
    if isinstance(val, (int, float)):
        if val < 0:
            return "background-color:rgba(220,53,69,0.12);color:#dc3545"
        if val > 0:
            return "background-color:rgba(25,135,84,0.12);color:#198754"
    return ""


def render_traffic_matrix(metric: str, unit_label: str) -> None:
    """Render st.data_editor tables for one traffic metric across all cases.

    Displays one editable table per case (Base Case + N project cases), then a
    colour-coded read-only incremental table (Project − Base) beneath.
    Reads and writes ``st.session_state.traffic_data`` in-place.

    Args:
        metric:     One of "vht", "vkt", "stops", "demand".
        unit_label: Human-readable unit string shown in the table header.
    """
    years: list = st.session_state.modelling_years
    n: int = st.session_state.n_project_cases
    case_keys = ["base_case"] + [f"project_{i}" for i in range(1, n + 1)]
    case_labels = ["Base Case"] + [f"Project {i}" for i in range(1, n + 1)]

    col_cfg = {
        str(y): st.column_config.NumberColumn(str(y), min_value=0.0, format="%.0f")
        for y in years
    }

    # ── Editable input tables ──────────────────────────────────────────────
    for case_key, case_label in zip(case_keys, case_labels):
        st.markdown(f"**{case_label}** &nbsp;·&nbsp; <small>{unit_label}</small>",
                    unsafe_allow_html=True)

        # Build DataFrame: rows = vehicle types, columns = modelling years
        row_data = {
            str(y): {
                vt: st.session_state.traffic_data[case_key][vt][metric][y_idx]
                for vt in VTYPES
            }
            for y_idx, y in enumerate(years)
        }
        df_edit = pd.DataFrame(row_data, index=VTYPES)

        edited = st.data_editor(
            df_edit,
            num_rows="fixed",
            key=f"de_{metric}_{case_key}",
            use_container_width=True,
            column_config=col_cfg,
        )

        # Persist edits back to session_state
        for y_idx, y in enumerate(years):
            for vt in VTYPES:
                try:
                    val = float(edited.loc[vt, str(y)])
                except (KeyError, ValueError, TypeError):
                    val = 0.0
                st.session_state.traffic_data[case_key][vt][metric][y_idx] = val

        # Auto-sum totals (read-only caption below each table)
        totals = edited.sum()
        st.caption(
            "  Total: " + "   |   ".join(f"{y}: {totals[str(y)]:.0f}" for y in years)
        )

    # ── Incremental tables (Project − Base) ───────────────────────────────
    if n >= 1:
        st.divider()
        st.markdown("**Incremental (Project − Base)**")

        base_data = {
            str(y): {
                vt: st.session_state.traffic_data["base_case"][vt][metric][y_idx]
                for vt in VTYPES
            }
            for y_idx, y in enumerate(years)
        }
        base_df = pd.DataFrame(base_data, index=VTYPES)

        for i in range(1, n + 1):
            proj_data = {
                str(y): {
                    vt: st.session_state.traffic_data[f"project_{i}"][vt][metric][y_idx]
                    for vt in VTYPES
                }
                for y_idx, y in enumerate(years)
            }
            proj_df = pd.DataFrame(proj_data, index=VTYPES)
            incr_df = proj_df - base_df

            if n > 1:
                st.caption(f"Project {i} − Base")

            st.dataframe(
                incr_df.style.map(_style_incr).format("{:+.0f}"),
                use_container_width=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# CRASH MATRIX UI HELPER — Step 4
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# COST ENTRY UI HELPER — Step 5
# ─────────────────────────────────────────────────────────────────────────────

def render_cost_entry(eval_period: int = 30) -> None:
    """Render cost input forms per project case (Step 5).

    One expandable section per project case with capital costs (planning, land,
    construction, contingency %), recurrent costs (maintenance, operating), and
    residual value.  Updates ``st.session_state.cost_data`` in-place.

    Args:
        eval_period: Operational evaluation period in years (from sidebar).
                     Used to compute auto-calculated residual value.
    """
    n = st.session_state.n_project_cases
    for i in range(1, n + 1):
        case_key = f"project_{i}"
        cd = st.session_state.cost_data[case_key]

        with st.expander(f"Project {i} — Costs", expanded=(i == 1)):
            st.markdown("**Capital Costs ($M, undiscounted)**")
            c1, c2 = st.columns(2)
            with c1:
                cd["cap_planning"] = st.number_input(
                    "Planning & Design ($M)", min_value=0.0,
                    value=float(cd["cap_planning"]), step=0.1, key=f"cost_planning_{i}",
                )
                cd["cap_construction"] = st.number_input(
                    "Construction ($M)", min_value=0.0,
                    value=float(cd["cap_construction"]), step=1.0, key=f"cost_construction_{i}",
                )
                cd["construction_asset_life"] = st.number_input(
                    "Construction Asset Life (years)",
                    min_value=1, max_value=200,
                    value=int(cd.get("construction_asset_life", 40)),
                    step=5, key=f"cost_asset_life_{i}",
                    help=(
                        "Useful life of the constructed asset — used to auto-calculate residual "
                        "value at end of evaluation period (straight-line depreciation). "
                        "Typical values: sealed rural road 40–60 yr · urban arterial 30–50 yr · "
                        "bridge/major structure 80–100 yr · flexible pavement 25–35 yr · "
                        "unsealed road 15–20 yr · ITS/signals 15–25 yr. "
                        "Land acquisition always retains full value regardless of this setting."
                    ),
                )
            with c2:
                cd["cap_land"] = st.number_input(
                    "Land Acquisition ($M)", min_value=0.0,
                    value=float(cd["cap_land"]), step=0.1, key=f"cost_land_{i}",
                )
                cd["contingency_pct"] = st.number_input(
                    "Contingency (%)", min_value=0.0, max_value=50.0,
                    value=float(cd["contingency_pct"]), step=1.0, key=f"cost_contingency_{i}",
                )

            total_cap = (
                (cd["cap_planning"] + cd["cap_land"] + cd["cap_construction"])
                * (1 + cd["contingency_pct"] / 100)
            )
            st.metric(
                f"Total Capital incl. {cd['contingency_pct']:.0f}% contingency ($M)",
                f"${total_cap:.2f}M",
            )

            # ── Auto-calculated Residual Value ───────────────────────────────
            _life = int(cd.get("construction_asset_life", 40))
            _rem_frac = max(0.0, (_life - eval_period) / _life) if _life > 0 else 0.0
            _const_with_cont = cd["cap_construction"] * (1 + cd["contingency_pct"] / 100)
            _land_res = cd["cap_land"]
            _const_res = _const_with_cont * _rem_frac
            _auto_res = _land_res + _const_res
            _override = cd.get("residual", 0.0) > 0.0
            st.markdown("**Residual Value (auto-calculated)**")
            _rc1, _rc2, _rc3 = st.columns(3)
            _rc1.metric(
                "Land Residual ($M)", f"${_land_res:.2f}M",
                help="Land acquisition retains full value (no depreciation).",
            )
            _rc2.metric(
                "Construction Residual ($M)", f"${_const_res:.2f}M",
                help=(
                    f"{_rem_frac*100:.0f}% of construction cost (incl. contingency) remaining "
                    f"after {eval_period}-yr evaluation period "
                    f"(asset life {_life} yr). "
                    "Formula: cost × max(0, (asset_life − eval_period) / asset_life)."
                ),
            )
            _rc3.metric(
                "Auto Residual ($M)" + (" — OVERRIDDEN" if _override else ""),
                f"${_auto_res:.2f}M",
                help=(
                    "Sum of land + construction residuals. "
                    "Planning/design has no residual value (professional services). "
                    "Overridden if Manual Residual Override below is > $0."
                ),
            )

            st.markdown("**Recurrent Costs ($M/year)**")
            r1, r2 = st.columns(2)
            with r1:
                cd["opex_maint"] = st.number_input(
                    "Maintenance ($M/yr)", min_value=0.0,
                    value=float(cd["opex_maint"]), step=0.1, key=f"cost_maint_{i}",
                )
            with r2:
                cd["opex_op"] = st.number_input(
                    "Operating ($M/yr)", min_value=0.0,
                    value=float(cd["opex_op"]), step=0.1, key=f"cost_op_{i}",
                )

            st.markdown("**Construction-Phase Disbenefits ($M/year)**")
            cd["construction_disbenefit_annual"] = st.number_input(
                "Traffic Disruption During Construction ($M/yr)",
                min_value=0.0,
                value=float(cd.get("construction_disbenefit_annual", 0.0)),
                step=0.1,
                key=f"cost_const_disb_{i}",
                help=(
                    "Annual road-user delay cost during construction (e.g. detour travel time, "
                    "VOC on diversion routes). Applied each year of the construction period and "
                    "added to project costs. Source: TfNSW CBA Guidelines — model delays using "
                    "affected AADT × detour delay × VTTS, or use a lump-sum estimate."
                ),
            )

            cd["residual"] = st.number_input(
                "Manual Residual Override ($M)",
                min_value=0.0,
                value=float(cd["residual"]), step=0.1, key=f"cost_residual_{i}",
                help=(
                    "Leave at $0 to use the auto-calculated residual shown above. "
                    "Enter a value > $0 to override the auto-calculation entirely. "
                    "Source: TfNSW CBA Guidelines — residual value = "
                    "(remaining asset life / total asset life) × capital cost."
                ),
            )

            st.markdown("**Active Transport — Incremental Health Benefits**")
            at1, at2 = st.columns(2)
            with at1:
                cd["walk_pkm_day"] = st.number_input(
                    "Incremental Walking (person-km/day)", min_value=0.0,
                    value=float(cd.get("walk_pkm_day", 0.0)), step=1.0,
                    key=f"cost_walk_{i}",
                    help=(
                        "New walking person-km/day generated by this project vs. base case "
                        "(e.g. new footpaths, bridge crossings). "
                        "Benefit = person-km/day × $3.17/person-km × 365. "
                        "Source: TfNSW EPV Jan 2025, Table 18."
                    ),
                )
            with at2:
                cd["cycle_pkm_day"] = st.number_input(
                    "Incremental Cycling (person-km/day)", min_value=0.0,
                    value=float(cd.get("cycle_pkm_day", 0.0)), step=1.0,
                    key=f"cost_cycle_{i}",
                    help=(
                        "New cycling person-km/day generated by this project vs. base case "
                        "(e.g. new shared paths, separated lanes). "
                        "Benefit = person-km/day × $1.60/person-km × 365. "
                        "Source: TfNSW EPV Jan 2025, Table 18."
                    ),
                )

            st.markdown("**Pavement Maintenance Savings ($M/year)**")
            cd["pavement_saving_annual"] = st.number_input(
                "Road Authority Maintenance Saving ($M/yr)", min_value=0.0,
                value=float(cd.get("pavement_saving_annual", 0.0)), step=0.1,
                key=f"cost_pavement_{i}",
                help=(
                    "Avoided road authority pavement maintenance cost during the operational "
                    "period (e.g. reduced resurfacing on routes that lose heavy freight traffic, "
                    "or longer pavement life on a new alignment). Applied as a benefit from "
                    "first operational year. Source: TfNSW CBA Guidelines — pavement "
                    "deterioration modelling or agency-supplied unit cost rates."
                ),
            )

            st.session_state.cost_data[case_key] = cd


# ─────────────────────────────────────────────────────────────────────────────
# FILE UPLOAD HELPERS — Step 6
# ─────────────────────────────────────────────────────────────────────────────

def generate_template_excel():
    """Generate a pre-structured Excel template for matrix traffic data.

    Returns raw bytes suitable for st.download_button, or None if openpyxl is
    not installed.
    """
    if not _EXCEL_AVAILABLE:
        return None

    years = st.session_state.modelling_years
    n = st.session_state.n_project_cases
    case_keys = ["base_case"] + [f"project_{i}" for i in range(1, n + 1)]
    case_labels = ["Base Case"] + [f"Project {i}" for i in range(1, n + 1)]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # One sheet per traffic metric
        for metric in ["VHT", "VKT", "Stops", "Demand"]:
            rows = []
            for case_key, case_label in zip(case_keys, case_labels):
                for vt in VTYPES:
                    row = {"Case": case_label, "Vehicle Type": vt}
                    for y in years:
                        row[str(y)] = 0.0
                    rows.append(row)
            pd.DataFrame(rows).to_excel(writer, sheet_name=metric, index=False)

    return buf.getvalue()


def _apply_template_df(df: pd.DataFrame, metric: str, years: list, n: int) -> None:
    """Write a parsed template DataFrame into ``st.session_state.traffic_data``."""
    case_labels_map = {
        "Base Case": "base_case",
        **{f"Project {i}": f"project_{i}" for i in range(1, n + 1)},
    }
    year_cols = [str(y) for y in years]
    for _, row in df.iterrows():
        case_key = case_labels_map.get(str(row.get("Case", "")).strip())
        vt = str(row.get("Vehicle Type", "")).strip()
        if case_key and vt in VTYPES and case_key in st.session_state.traffic_data:
            for y_idx, yc in enumerate(year_cols):
                try:
                    val = float(row.get(yc, 0.0) or 0.0)
                except (ValueError, TypeError):
                    val = 0.0
                st.session_state.traffic_data[case_key][vt][metric][y_idx] = val


def _handle_template_upload(uploaded_file) -> None:
    """Parse a file uploaded in Template mode and populate session_state data."""
    years = st.session_state.modelling_years
    n = st.session_state.n_project_cases
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
            _apply_template_df(df, "vht", years, n)
            st.success("Imported VHT data from CSV (for full import use Excel template).")
        else:
            xl = pd.ExcelFile(uploaded_file)
            metrics_map = {"VHT": "vht", "VKT": "vkt", "Stops": "stops", "Demand": "demand"}
            imported = []
            for sheet_name, metric in metrics_map.items():
                if sheet_name in xl.sheet_names:
                    _apply_template_df(xl.parse(sheet_name), metric, years, n)
                    imported.append(sheet_name)
            if imported:
                st.success(f"Imported: {', '.join(imported)}")
                st.rerun()
            else:
                st.warning(
                    "No matching sheets found. Expected sheet names: "
                    "VHT, VKT, Stops, Demand."
                )
    except Exception as e:
        st.error(f"Import failed: {e}")


def _smart_parse_upload(uploaded_file) -> None:
    """Attempt automatic column detection for arbitrary CSV/Excel files."""
    years = st.session_state.modelling_years
    n = st.session_state.n_project_cases

    try:
        if uploaded_file.name.endswith(".csv"):
            dfs = {"Sheet1": pd.read_csv(uploaded_file)}
        else:
            xl = pd.ExcelFile(uploaded_file)
            # If it looks like our own template, delegate to the template handler
            template_sheets = {"VHT", "VKT", "Stops", "Demand", "Crashes"}
            if template_sheets.issubset(set(xl.sheet_names)):
                _handle_template_upload(uploaded_file)
                return
            dfs = {sh: xl.parse(sh) for sh in xl.sheet_names}

        case_labels_norm = {
            "base case": "Base Case", "base": "Base Case",
            **{f"project {i}": f"Project {i}" for i in range(1, n + 1)},
            **{f"project_{i}": f"Project {i}" for i in range(1, n + 1)},
            **{f"project{i}": f"Project {i}" for i in range(1, n + 1)},
        }

        imported = []
        for sheet_name, df in dfs.items():
            df.columns = [str(c).strip() for c in df.columns]

            # Detect year columns: 4-digit integers in range 1990-2200, sorted ascending
            year_cols = sorted(
                [c for c in df.columns if c.isdigit() and 1990 <= int(c) <= 2200],
                key=int,
            )
            if not year_cols:
                continue

            case_col = next((c for c in df.columns if c.lower() in
                             ("case", "scenario", "project")), None)
            vt_col = next((c for c in df.columns if c.lower() in
                           ("vehicle type", "vehicletype", "vtype", "vehicle")), None)

            # Infer metric from sheet name
            inferred_metric = next(
                (m for m in ("vht", "vkt", "stops", "demand") if m in sheet_name.lower()),
                "vht",
            )

            norm_rows = []
            for _, row in df.iterrows():
                raw_case = str(row[case_col]).strip().lower() if case_col else "base case"
                norm_case = case_labels_norm.get(raw_case, "Base Case")

                raw_vt = str(row[vt_col]).strip() if vt_col else "Car"
                vt_match = _auto_match_vtypes([raw_vt]).get(raw_vt)
                if vt_match is None:
                    continue

                norm_row = {"Case": norm_case, "Vehicle Type": vt_match}
                for yc in year_cols:
                    norm_row[yc] = row.get(yc, 0.0)
                norm_rows.append(norm_row)

            if norm_rows:
                _apply_template_df(pd.DataFrame(norm_rows), inferred_metric, years, n)
                imported.append(f"{sheet_name} → {inferred_metric.upper()}")

        if imported:
            st.success(f"Smart parse imported: {', '.join(imported)}")
            st.rerun()
        else:
            st.warning(
                "Could not detect year columns (expecting 4-digit years ≥ 2020) or no "
                "matching vehicle types found. Switch to **User mapping** to drag-and-drop "
                "your column and row names onto the expected fields."
            )
    except Exception as e:
        st.error(f"Smart parse failed: {e}")


def _render_user_mapping_upload(uploaded_file) -> None:
    """Drag-and-drop column/row/case mapping UI for arbitrary CSV/Excel files."""
    years = st.session_state.modelling_years
    n     = st.session_state.n_project_cases
    std_cases = ["Base Case"] + [f"Project {i}" for i in range(1, n + 1)]

    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            xl = pd.ExcelFile(uploaded_file)
            sheet = st.selectbox("Sheet", xl.sheet_names, key="um_sheet")
            df = xl.parse(sheet)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    df.columns = [str(c).strip() for c in df.columns]

    # Detect structural columns (Case, Vehicle Type) and the remaining year columns
    case_col = next((c for c in df.columns if c.lower() in ("case", "scenario", "project")), None)
    vt_col   = next((c for c in df.columns
                     if "vehicle" in c.lower() or "vtype" in c.lower()), None)
    year_cols = [c for c in df.columns if c not in filter(None, [case_col, vt_col])]

    detected_cases  = ([str(v).strip() for v in df[case_col].dropna().unique()[:8]]
                       if case_col else [])
    detected_vtypes = ([str(v).strip() for v in df[vt_col].dropna().unique()]
                       if vt_col else [])

    metric = st.selectbox("Metric in this file / sheet",
                          ["vht", "vkt", "stops", "demand"], key="um_metric")

    st.caption(
        "Drag vehicle type chips onto the matching drop zones. "
        "Year columns are auto-filled — correct them if needed. "
        "Then click **Confirm Mapping**."
    )

    mapping = column_mapper(
        detected_rows=detected_vtypes,
        detected_cols=year_cols,
        detected_cases=detected_cases,
        auto_row_mapping=_auto_match_vtypes(detected_vtypes),
        auto_col_mapping=_auto_match_years(year_cols),
        auto_case_mapping=_auto_match_cases(detected_cases, n),
        target_rows=[{"key": vt, "label": vt} for vt in VTYPES],
        target_cases=std_cases,
        key=f"um_mapper_{uploaded_file.name}_{metric}",
        height=480,
        default=None,
    )

    if mapping:
        row_map  = mapping.get("row_mapping", {})   # {detected_vt: "Car"/"LCV"/...}
        col_map  = mapping.get("col_mapping", {})   # {detected_col: year_int}
        case_map = mapping.get("case_mapping", {})  # {detected_case: "Base Case"/...}

        ordered_cols = sorted(col_map, key=lambda c: col_map[c])

        norm_rows = []
        for _, row in df.iterrows():
            raw_case = (str(row[case_col]).strip()
                        if case_col else (next(iter(case_map), "Base Case")))
            norm_case = case_map.get(raw_case, "Base Case") if case_map else "Base Case"

            raw_vt   = str(row[vt_col]).strip() if vt_col else ""
            norm_vt  = row_map.get(raw_vt)
            if norm_vt is None:
                continue

            norm_row = {"Case": norm_case, "Vehicle Type": norm_vt}
            for col in ordered_cols:
                try:
                    norm_row[str(col_map[col])] = float(row.get(col, 0.0) or 0.0)
                except (ValueError, TypeError):
                    norm_row[str(col_map[col])] = 0.0
            norm_rows.append(norm_row)

        if not norm_rows:
            st.warning("No rows matched after mapping. Check column selections and values.")
            return

        # Merge any new mapped years into the modelling_years list
        mapped_year_ints = sorted({col_map[c] for c in ordered_cols})
        merged_years = sorted(set(years) | set(mapped_year_ints))

        _apply_template_df(pd.DataFrame(norm_rows), metric, merged_years, n)
        if merged_years != list(years):
            st.session_state.modelling_years = merged_years
        st.success(f"Mapped {len(norm_rows)} rows → {metric.upper()}")
        st.rerun()



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
            for vt in VTYPES:
                vht_base = interpolate_modelling_years(
                    modelling_years, base_traffic[vt]["vht"], ey
                )
                vht_proj = interpolate_modelling_years(
                    modelling_years, proj_traffic[vt]["vht"], ey
                )
                annual_vht_saving = max(0.0, vht_base - vht_proj) * ann_factors[vt]
                vt_tts = annual_vht_saving * occupancy_by_vtype[vt] * vtts_by_vtype[vt] / 1e6
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
                voc_saving = annual_vkt_b * voc_b - annual_vkt_p * voc_p
                b_voc += max(0.0, voc_saving) / 1e6

            # ── Safety: $/VKT per vehicle type (per-case rates) ─────────────
            _sv_base = safety_vkt_base if safety_vkt_base is not None else _p["safety_vkt"]
            _sv_proj = safety_vkt_proj if safety_vkt_proj is not None else _p["safety_vkt"]
            for vt in VTYPES:
                vkt_b = interpolate_modelling_years(modelling_years, base_traffic[vt]["vkt"], ey)
                vkt_p = interpolate_modelling_years(modelling_years, proj_traffic[vt]["vkt"], ey)
                b_safety += (vkt_b * _sv_base[vt] - vkt_p * _sv_proj[vt]) * ann_factors[vt] / 1e6
            # Fatal component: used for VSL sensitivity (scales this share ±, rest held fixed).
            b_safety_fatal = b_safety * _p["safety_severity_share"]["fatal"]

            # ── Environmental: emission + air + noise per vtype × VKT Δ ────
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

    scenarios = {}
    for label, factor in [("Low (-20%)", 0.8), ("Central", 1.0), ("High (+20%)", 1.2)]:
        s_pvb = sum(annual_benefits[y] * factor * discount_factor(dr, base_offset + y) for y in range(total_years))
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


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-CASE LOOP — Step 8
# ─────────────────────────────────────────────────────────────────────────────

def _stable_hash(*args) -> str:
    """Create a stable MD5 hex digest from JSON-serialised args for caching."""
    import hashlib
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()


@st.cache_data(show_spinner=False)
def _cached_calculate_all_cases(_cache_key: str, inputs: dict,
                                traffic_data: dict, cost_data: dict,
                                annualisation: dict, safety_vkt_data: dict,
                                params: dict) -> dict:
    return calculate_all_cases(
        inputs=inputs,
        traffic_data=traffic_data,
        cost_data=cost_data,
        annualisation=annualisation,
        safety_vkt_data=safety_vkt_data,
        params=params,
    )


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
      - Traffic VHT/VKT (base and project): Normal(1, traffic_cv), clamped > 0
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
    traffic_factors = rng.normal(1.0, traffic_cv,  (n_simulations, 2)).clip(0.01)  # [base, proj]
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

        # ── Perturb traffic (multiplicative, independent for base vs project) ─
        f_base = traffic_factors[i, 0]
        f_proj = traffic_factors[i, 1]

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

    def _npv_with(vtts_f=1.0, safety_f=1.0, traffic_base_f=1.0, traffic_proj_f=1.0, cost_f=1.0):
        _p = copy.deepcopy(_p_base)
        for _ctx in ("urban", "rural"):
            for _vt in VTYPES:
                _p["vtts"][_ctx][_vt] *= vtts_f
        _sv_b = {vt: (_p_base["safety_vkt"][vt]) * safety_f for vt in VTYPES}
        _sv_p = {vt: (_p_base["safety_vkt"][vt]) * safety_f for vt in VTYPES}
        _bt = _scale_traffic(base_traffic_orig, traffic_base_f)
        _pt = _scale_traffic(proj_traffic_orig, traffic_proj_f)
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
    _traf_p10_f   = float(np.percentile(traffic_factors[:, 1], 10))
    _traf_p90_f   = float(np.percentile(traffic_factors[:, 1], 90))
    _cost_p10_f   = float(np.percentile(cost_factors, 10))
    _cost_p90_f   = float(np.percentile(cost_factors, 90))

    tornado = {
        "VTTS":             (_npv_with(vtts_f=_vtts_p10_f),   _npv_with(vtts_f=_vtts_p90_f)),
        "Safety cost/VKT":  (_npv_with(safety_f=_safety_p10_f), _npv_with(safety_f=_safety_p90_f)),
        "Traffic volumes":  (_npv_with(traffic_proj_f=_traf_p10_f), _npv_with(traffic_proj_f=_traf_p90_f)),
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


# ─────────────────────────────────────────────────────────────────────────────
# PARAMETER EDITOR HELPERS — Phase 0e
# ─────────────────────────────────────────────────────────────────────────────

def _param_sync_num(param_key: str) -> None:
    """on_change callback: push number_input value → canonical key + slider."""
    val = float(st.session_state[f"{param_key}_num"])
    st.session_state[param_key] = val
    st.session_state[f"{param_key}_sl"] = val


def _param_sync_sl(param_key: str) -> None:
    """on_change callback: push slider value → canonical key + number_input."""
    val = float(st.session_state[f"{param_key}_sl"])
    st.session_state[param_key] = val
    st.session_state[f"{param_key}_num"] = val


def param_editor(label: str, key: str, default: float,
                 min_val: float, max_val: float, step: float,
                 unit: str, source: str = "") -> float:
    """Render a synchronized number_input + slider for one economic parameter.

    Writes the current value to ``st.session_state[key]``.  A delta badge is
    shown when the value has been changed from its TfNSW default.

    Returns the current (possibly overridden) value.
    """
    # Initialise canonical key and both widget keys from it
    if key not in st.session_state:
        st.session_state[key] = float(default)
    current = float(st.session_state[key])
    if f"{key}_num" not in st.session_state:
        st.session_state[f"{key}_num"] = current
    if f"{key}_sl" not in st.session_state:
        st.session_state[f"{key}_sl"] = current

    col_lbl, col_num, col_sl = st.columns([2, 1, 2])
    with col_lbl:
        st.write(f"**{label}** `{unit}`")
        if source:
            st.caption(source)
        if current != default and default != 0:
            pct = (current - default) / abs(default) * 100
            arrow = "↑" if current > default else "↓"
            st.caption(f"{arrow} {abs(pct):.0f}% from default")
    with col_num:
        st.number_input(
            f"{label} value", key=f"{key}_num",
            min_value=float(min_val), max_value=float(max_val), step=float(step),
            label_visibility="collapsed",
            on_change=_param_sync_num, args=(key,),
        )
    with col_sl:
        st.slider(
            f"{label} slider", key=f"{key}_sl",
            min_value=float(min_val), max_value=float(max_val), step=float(step),
            label_visibility="collapsed",
            on_change=_param_sync_sl, args=(key,),
        )
    return float(st.session_state[key])


def build_effective_params() -> dict:
    """Return a deep copy of PARAMS with any session_state overrides applied.

    The Parameters tab writes overrides to session_state under ``param_*`` keys.
    This function merges those back into the canonical PARAMS structure so that
    ``calculate_matrix()`` uses user-edited values without mutating the global.
    """
    p = copy.deepcopy(PARAMS)
    ss = st.session_state
    for _ctx in ("urban", "rural"):
        for _vt in ("Car", "LCV", "HCV", "Bus"):
            _k = f"param_vtts_{_ctx}_{_vt}"
            if _k in ss:
                p["vtts"][_ctx][_vt] = float(ss[_k])
            _k = f"param_occupancy_{_ctx}_{_vt}"
            if _k in ss:
                p["occupancy"][_ctx][_vt] = float(ss[_k])
    if "param_reliability_ratio" in ss:
        p["reliability_ratio"] = float(ss["param_reliability_ratio"])
    if "param_reliability_ratio_freight" in ss:
        p["reliability_ratio_freight"] = float(ss["param_reliability_ratio_freight"])
    for _vt in VTYPES:
        _k = f"param_safety_vkt_{_vt}"
        if _k in ss:
            p["safety_vkt"][_vt] = float(ss[_k])
    for _ctx in ("urban", "rural"):
        for _vt in ("car", "lgv", "rigid", "bus"):
            _k = f"param_emission_{_ctx}_{_vt}"
            if _k in ss:
                p["emission_cost"][_ctx][_vt] = float(ss[_k])
        for _vt in ("car", "lgv", "rigid", "artic"):
            _k = f"param_air_{_ctx}_{_vt}"
            if _k in ss:
                p["air_pollution"][_ctx][_vt] = float(ss[_k])
            _k = f"param_noise_{_ctx}_{_vt}"
            if _k in ss:
                p["noise"][_ctx][_vt] = float(ss[_k])
    for _mode in ("walking", "cycling"):
        _k = f"param_health_{_mode}"
        if _k in ss:
            p["health_benefits"][_mode] = float(ss[_k])
    return p


# ─────────────────────────────────────────────────────────────────────────────
# INCREMENTAL BENEFITS SUMMARY HELPER — Step 11
# ─────────────────────────────────────────────────────────────────────────────

def render_incremental_summary() -> None:
    """Step 11: Render the Incremental Benefits Summary table.

    Shows base-case and project-case absolute traffic values at a chosen
    modelling year, plus colour-coded Δ columns (Project − Base).
    Negative Δ = green (reduction = improvement for VHT/VKT).
    Positive Δ = red (increase = disbenefit for the same metrics).
    """
    years = st.session_state.modelling_years
    n = st.session_state.n_project_cases
    td = st.session_state.traffic_data

    if not years or not td:
        return

    st.markdown(
        '<div class="section-header">Incremental Benefits Summary</div>',
        unsafe_allow_html=True,
    )

    sel_year = st.selectbox(
        "Display modelling year",
        options=years,
        key="incr_summary_year_sel",
    )
    y_idx = years.index(sel_year)

    _TRAFFIC_ROWS = [
        ("VHT (veh-hrs/peak period)", "vht"),
        ("VKT (veh-km/peak period)", "vkt"),
        ("Stops (stops/peak period)", "stops"),
        ("Demand (person-trips/peak period)", "demand"),
    ]
    rows_data = {}

    # Traffic rows: sum across vehicle types at selected modelling year
    for label, metric in _TRAFFIC_ROWS:
        base_val = sum(td["base_case"][vt][metric][y_idx] for vt in VTYPES)
        row: dict = {"Base Case": base_val}
        for i in range(1, n + 1):
            proj_val = sum(td[f"project_{i}"][vt][metric][y_idx] for vt in VTYPES)
            row[f"Project {i}"] = proj_val
            row[f"Δ{i}"] = proj_val - base_val
        rows_data[label] = row

    df_inc = pd.DataFrame.from_dict(rows_data, orient="index")
    delta_cols = [c for c in df_inc.columns if str(c).startswith("Δ")]

    def _colour_delta(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return "background-color:rgba(25,135,84,0.12);color:#198754"
            if val > 0:
                return "background-color:rgba(220,53,69,0.12);color:#dc3545"
        return ""

    fmt: dict = {}
    fmt.update({col: "{:+.0f}" for col in delta_cols})
    fmt.update({col: "{:.0f}" for col in df_inc.columns if col not in delta_cols})

    styled = df_inc.style.format(fmt)
    for col in delta_cols:
        styled = styled.map(_colour_delta, subset=[col])

    st.dataframe(styled, use_container_width=True)
    st.caption(
        f"Values are totals across Car, LCV, HCV, Bus at modelling year {sel_year}. "
        "Δ = Project − Base. Green (negative) = reduction = improvement."
    )


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
    "pavement": "#795548",
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
    "pavement": "Pavement Maintenance Savings",
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
# SESSION STATE INITIALISATION — Step 2
# ─────────────────────────────────────────────────────────────────────────────

def _init_session_state() -> None:
    """Initialise session_state keys for the matrix input UI (run once per session)."""
    if "modelling_years" not in st.session_state:
        st.session_state["modelling_years"] = list(DEFAULT_MODELLING_YEARS)
    if "n_project_cases" not in st.session_state:
        st.session_state["n_project_cases"] = 1
    _ANN_DEFAULT = {"factor": 6.29, "days": 336}
    if "annualisation" not in st.session_state:
        st.session_state["annualisation"] = {vt: dict(_ANN_DEFAULT) for vt in ("Car", "LCV", "HCV", "Bus")}
    else:
        # Migrate older flat structures
        _ann = st.session_state["annualisation"]
        _old_factor = _ann.pop("annualisation_factor", None)
        _old_days = _ann.pop("days_per_year", 336)
        for _vt in ("Car", "LCV", "HCV", "Bus"):
            if not isinstance(_ann.get(_vt), dict):
                _f = float(_ann[_vt]) if _vt in _ann else (_old_factor or 6.29)
                _ann[_vt] = {"factor": _f, "days": int(_old_days)}
    _years = st.session_state["modelling_years"]
    _n = st.session_state["n_project_cases"]
    _case_keys = ["base_case"] + [f"project_{i}" for i in range(1, _n + 1)]
    # Safety $/VKT per case — initialise missing cases with PARAMS defaults
    if "safety_vkt_data" not in st.session_state:
        st.session_state["safety_vkt_data"] = {
            ck: dict(PARAMS["safety_vkt"]) for ck in _case_keys
        }
    else:
        _svd = st.session_state["safety_vkt_data"]
        for ck in _case_keys:
            if ck not in _svd:
                _svd[ck] = dict(PARAMS["safety_vkt"])
    # (Re-)initialise traffic / cost data when structure changes
    td = st.session_state.get("traffic_data")
    needs_reset = (
        td is None
        or td.get("base_case", {}).get("years") != _years
        or f"project_{_n}" not in td
    )
    if needs_reset:
        st.session_state["traffic_data"] = make_traffic_data(_years, _n)
        st.session_state["cost_data"] = make_cost_data(_n)

    st.session_state.setdefault("show_advanced", False)
    st.session_state.setdefault("safety_mode", "General")
    st.session_state.setdefault("env_mode", "General")
    st.session_state.setdefault("reliability_mode", "General")
    st.session_state.setdefault("mc_results", None)


_init_session_state()


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — ALL INPUTS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Transport CBA")
    st.caption(f"v{__version__} · TfNSW EPV Jan 2025 · June 2024 prices")

    # TODO: Save/Load Project — JSON export/import including inputs + results + MC outputs. Implementation deferred.

    # ── Quick Start ───────────────────────────────────────────────────────────
    with st.expander("Quick Start", expanded=True):
        st.caption("Load a sample rural bypass scenario to explore the dashboard without entering data manually.")
        _confirm_load = st.checkbox("I understand this will overwrite all current data", key="confirm_load_sample")
        if st.button("Load Sample Data", use_container_width=True, disabled=not _confirm_load):
            _load_sample_data()

    # ── Save / Load Project ─────────────────────────────────────────────────
    with st.expander("Save / Load Project", expanded=False):
        st.caption("Download your project data as JSON or upload a previously saved file.")
        _proj = _serialise_project()
        _proj_json = json.dumps(_proj, default=str)
        _safe_filename = re.sub(r'[^\w\s-]', '', st.session_state.get("project_name", "cba_project")).strip().replace(' ', '_') or "cba_project"
        st.download_button(
            "Save Project (.json)",
            _proj_json,
            file_name=f"{_safe_filename}.json",
            mime="application/json",
            use_container_width=True,
        )
        _uploaded_project = st.file_uploader(
            "Load Project (.json)", type=["json"], key="load_project_uploader",
            label_visibility="collapsed",
        )
        if _uploaded_project is not None:
            try:
                _loaded = json.loads(_uploaded_project.read().decode("utf-8"))
                _deserialise_project(_loaded)
                st.rerun()
            except Exception as e:
                st.error(f"Error loading project: {e}")

    st.divider()

    # ── Matrix Input Configuration (Step 2) ──────────────────────────────────
    st.markdown("### Modelling Configuration")

    # Number of project cases
    _n_input = st.number_input(
        "Number of Project Cases", min_value=1, max_value=5,
        value=st.session_state["n_project_cases"], step=1,
        help="Number of project alternatives to compare against the Base Case (1–5). Each has its own traffic and cost data.",
    )
    if _n_input != st.session_state["n_project_cases"]:
        st.session_state["n_project_cases"] = _n_input
        _init_session_state()
        st.rerun()

    # Modelling years (comma-separated text input)
    _years_raw = st.text_input(
        "Modelling Years (comma-separated)",
        value=", ".join(str(y) for y in st.session_state["modelling_years"]),
        key="modelling_years_widget",
        help="e.g. 2026, 2031, 2041, 2056",
    )
    try:
        _parsed_years = [int(y.strip()) for y in _years_raw.split(",") if y.strip()]
        _year_errors = []
        if len(_parsed_years) < 2:
            _year_errors.append("At least 2 modelling years are required for CAGR interpolation.")
        else:
            _out_of_range = [y for y in _parsed_years if not (1990 <= y <= 2200)]
            if _out_of_range:
                _year_errors.append(f"Year(s) out of valid range (1990–2200): {_out_of_range}")
            _deduped = sorted(set(_parsed_years))
            if len(_deduped) < len(_parsed_years):
                _year_errors.append("Duplicate years will be removed.")
                _parsed_years = _deduped
            else:
                _parsed_years = sorted(_parsed_years)
        if _year_errors:
            for _msg in _year_errors:
                st.warning(_msg)
        if not _year_errors and _parsed_years != st.session_state["modelling_years"]:
            st.session_state["modelling_years"] = _parsed_years
            _init_session_state()
            st.rerun()
    except ValueError:
        st.error("Invalid year format — enter integers separated by commas.")

    # Annualisation parameters panel
    with st.expander("Annualisation Parameters", expanded=False):
        _ann = st.session_state["annualisation"]
        st.caption("Annualisation factor × days converts modelled-period VHT/VKT to an annual total.")
        _cols = st.columns(4)
        for _vt, _col in zip(("Car", "LCV", "HCV", "Bus"), _cols):
            _col.markdown(f"**{_vt}**")
            _ann[_vt]["factor"] = _col.number_input(
                "Factor", min_value=0.1, max_value=100.0,
                value=float(_ann[_vt]["factor"]), step=0.01,
                key=f"ann_factor_{_vt}",
            )
            _ann[_vt]["days"] = _col.number_input(
                "Days/yr", min_value=1, max_value=365,
                value=int(_ann[_vt]["days"]), step=1,
                key=f"ann_days_{_vt}",
            )
            _col.caption(f"= **{_ann[_vt]['factor'] * _ann[_vt]['days']:.0f}**")
        st.session_state["annualisation"] = _ann

    st.divider()

    # --- Project Details ---
    st.markdown("### Project Details")
    project_name = st.text_input("Project Name", value="Sample Road Upgrade",
        help="A descriptive name for this cost-benefit analysis. Shown in the header and exported CSV.")
    st.session_state["project_name"] = project_name
    col1, col2 = st.columns(2)
    with col1:
        eval_period = st.number_input("Evaluation Period (years)", 1, 50, 30,
            help="Total analysis period in years (typically 20–40). Includes construction and operating years.")
        discount_base_year = st.number_input("Discount Base Year", 2020, 2060, 2026,
            help="Calendar year used as Year 0 for discounting (PV anchor).")
        construction_start_year = st.number_input("Construction Start Year", 2020, 2060, 2026,
            help="Calendar year construction begins. Benefits start after the construction period.")
    with col2:
        const_years = st.number_input("Construction Period (years)", 1, 10, 3,
            help="Number of years over which capital costs are spread. Construction disbenefits apply during this period.")
        discount_rate = st.number_input("Discount Rate (%)", 0.0, 20.0, 5.0, step=0.5,
            help="TfNSW default: 5%. Used to discount future costs and benefits to present values. Higher rates reduce NPV.")
    context = st.selectbox("Context", ["urban", "rural"], format_func=str.title,
        help="Affects VTTS rates, VOC speed tables, emission costs, and air pollution rates. Urban uses higher rates.")
    zero_growth_after_last_year = st.checkbox(
        "Zero growth after last modelling year",
        value=False,
        help="When checked, traffic volumes (and all benefits) are held flat at the last "
             "modelling year's values rather than extrapolating the trend.",
    )

    st.divider()
    show_advanced = st.checkbox(
        "Show advanced analytics",
        key="show_advanced",
        help="Enables Payback Period KPI and Monte Carlo risk simulation in Sensitivity tab.",
    )
    with st.expander("Benefit Estimation Methods"):
        st.radio(
            "Safety Costs", ["General", "Detailed"],
            key="safety_mode",
            help="General: default TfNSW $/VKT rates applied to all cases. "
                 "Detailed: edit per-case safety cost rates in the Data Input tab.",
        )
        st.radio(
            "Environmental Breakdown", ["General", "Detailed"],
            key="env_mode",
            help="General: single combined environmental benefit line. "
                 "Detailed: separate CO₂ emission cost, air quality & noise columns.",
        )
        st.radio(
            "Reliability Benefit", ["General", "Detailed"],
            key="reliability_mode",
            help="General: reliability benefit included in Travel Time Savings total. "
                 "Detailed: shown as a separate line item in charts and cashflow table.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# RUN CALCULATION
# ─────────────────────────────────────────────────────────────────────────────
_matrix_inputs = {
    "context": context,
    "evaluation_period": eval_period,
    "construction_years": const_years,
    "discount_rate": discount_rate,
    "discount_base_year": discount_base_year,
    "construction_start_year": construction_start_year,
    "zero_growth_after_last_year": zero_growth_after_last_year,
    "n_project_cases": st.session_state.n_project_cases,
}
try:
    _eff_params = build_effective_params()
    _cache_key = _stable_hash(_matrix_inputs, st.session_state.traffic_data,
                              st.session_state.cost_data, st.session_state.annualisation,
                              st.session_state.safety_vkt_data, _eff_params)
    matrix_results = _cached_calculate_all_cases(
        _cache_key, _matrix_inputs,
        traffic_data=st.session_state.traffic_data,
        cost_data=st.session_state.cost_data,
        annualisation=st.session_state.annualisation,
        safety_vkt_data=st.session_state.safety_vkt_data,
        params=_eff_params,
    )
except Exception as _calc_err:
    matrix_results = {}
    st.error(f"Calculation error: {_calc_err}. Please check your input data for missing or invalid values.")


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
    <p>{html.escape(project_name)} · TfNSW Framework · {context.title()} · {discount_rate}% discount rate</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# KPI METRICS — Step 10: multi-case aware
# ─────────────────────────────────────────────────────────────────────────────
_n_cases = st.session_state.n_project_cases

if matrix_results and _n_cases > 1:
    # Multi-case: one KPI column per project case
    _case_cols = st.columns(min(_n_cases, 4))
    for _i, _col in enumerate(_case_cols, 1):
        _mr = matrix_results.get(f"project_{_i}", {})
        _pb = f"{_mr['payback_year']} yrs" if _mr.get("payback_year") else "N/A"
        _irr_str = f"{_mr['irr']:.1f}%" if _mr.get("irr") is not None else "N/A"
        _deferral = _mr.get("fyrr_deferral_pass")
        _deferral_delta = ("Proceed" if _deferral else "Consider deferral") if _deferral is not None else ""
        with _col:
            st.markdown(f"**Project {_i}**")
            st.metric("NPV", format_m(_mr.get("npv", 0)),
                      delta="Positive" if _mr.get("npv", 0) >= 0 else "Negative",
                      delta_color="normal" if _mr.get("npv", 0) >= 0 else "inverse")
            st.metric("BCR", f"{_mr.get('bcr', 0):.2f}",
                      delta="≥ 1.0" if _mr.get("bcr", 0) >= 1 else "< 1.0",
                      delta_color="normal" if _mr.get("bcr", 0) >= 1 else "inverse")
            st.metric("IRR", _irr_str)
            st.metric("FYRR", f"{_mr.get('fyrr', 0):.1f}%",
                      delta=_deferral_delta,
                      delta_color="normal" if _deferral else "inverse")
            if show_advanced:
                st.metric("Payback", _pb)
elif matrix_results:
    # Single project case
    _r_kpi = matrix_results["project_1"]
    _irr_val = _r_kpi.get("irr")
    _irr_str = f"{_irr_val:.1f}%" if _irr_val is not None else "N/A"
    _deferral = _r_kpi.get("fyrr_deferral_pass")
    _deferral_delta = ("Proceed" if _deferral else "Consider deferral") if _deferral is not None else ""
    _n_kpi_cols = 7 if show_advanced else 6
    _kpi_cols = st.columns(_n_kpi_cols)
    with _kpi_cols[0]:
        st.metric("Net Present Value", format_m(_r_kpi["npv"]),
                  delta="Positive" if _r_kpi["npv"] >= 0 else "Negative",
                  delta_color="normal" if _r_kpi["npv"] >= 0 else "inverse")
    with _kpi_cols[1]:
        st.metric("Benefit-Cost Ratio", f"{_r_kpi['bcr']:.2f}",
                  delta="Above 1.0" if _r_kpi["bcr"] >= 1 else "Below 1.0",
                  delta_color="normal" if _r_kpi["bcr"] >= 1 else "inverse")
    with _kpi_cols[2]:
        st.metric("PV Benefits", format_m(_r_kpi["pv_benefits"]))
    with _kpi_cols[3]:
        st.metric("PV Costs", format_m(_r_kpi["pv_costs"]))
    with _kpi_cols[4]:
        # IRR: TfNSW CBA framework; ATAP T2 §5.3 (supplementary)
        st.metric("Internal Rate of Return", _irr_str)
    with _kpi_cols[5]:
        # FYRR deferral test: TfNSW CBA Guidelines — proceed if FYRR ≥ discount rate
        st.metric("First Year Rate of Return", f"{_r_kpi['fyrr']:.1f}%",
                  delta=_deferral_delta,
                  delta_color="normal" if _deferral else "inverse")
    if show_advanced:
        with _kpi_cols[6]:
            pb = f"{_r_kpi['payback_year']} years" if _r_kpi["payback_year"] else "N/A"
            st.metric("Payback Period", pb)
else:
    st.info("Enter traffic data in the **Data Input** tab to see results.")

# ─────────────────────────────────────────────────────────────────────────────
# TABBED LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
tab_datainput, tab_dash, tab_cashflow, tab_sensitivity, tab_params, tab_about = st.tabs(
    ["Data Input", "Dashboard", "Detailed Cashflow", "Sensitivity", "Parameters", "About"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 0: DATA INPUT — Step 3 (traffic matrices) + Step 4 (costs)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_datainput:
    st.markdown('<div class="section-header">Traffic & Project Data Entry</div>',
                unsafe_allow_html=True)

    _ann = st.session_state["annualisation"]
    st.caption(
        f"Modelling years: **{', '.join(str(y) for y in st.session_state['modelling_years'])}** · "
        "  ·  ".join(
            f"{vt}: {_ann[vt]['factor']:.2f} × {_ann[vt]['days']} = **{_ann[vt]['factor']*_ann[vt]['days']:.0f}**"
            for vt in ("Car", "LCV", "HCV", "Bus")
        )
    )

    # ── File Upload / Template Download (Step 6) ──────────────────────────
    with st.expander("Import Data from File", expanded=False):
        up_col, tmpl_col = st.columns([2, 1])
        with up_col:
            st.markdown("**Upload CSV or Excel**")
            parse_mode = st.radio(
                "Parse mode",
                ["Template", "Smart parse", "User mapping"],
                horizontal=True,
                help=(
                    "**Template**: upload a file generated by the Download button. "
                    "**Smart parse**: auto-detect year columns and vehicle types. "
                    "**User mapping**: drag-and-drop your column and row names onto the expected fields."
                ),
            )
            MAX_UPLOAD_MB = 50

            uploaded_file = st.file_uploader(
                "Drop file here (max 50 MB)",
                type=["csv", "xlsx"],
                label_visibility="collapsed",
            )
            if uploaded_file is not None:
                if uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
                    st.error(f"File too large. Maximum upload size is {MAX_UPLOAD_MB} MB.")
                else:
                    try:
                        if parse_mode == "Template":
                            _handle_template_upload(uploaded_file)
                        elif parse_mode == "Smart parse":
                            _smart_parse_upload(uploaded_file)
                        else:
                            _render_user_mapping_upload(uploaded_file)
                    except Exception as e:
                        st.error(f"Error parsing file: {e}. Please check the file format and try again.")

        with tmpl_col:
            st.markdown("**Download blank template**")
            tmpl_bytes = generate_template_excel()
            if tmpl_bytes:
                st.download_button(
                    "Download Excel Template",
                    tmpl_bytes,
                    file_name="cba_data_template.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            else:
                # CSV fallback (VHT only) when openpyxl is absent
                _yrs = st.session_state.modelling_years
                _nc = st.session_state.n_project_cases
                _case_labels = ["Base Case"] + [f"Project {i}" for i in range(1, _nc + 1)]
                csv_lines = ["Case,Vehicle Type," + ",".join(str(y) for y in _yrs)]
                for cl in _case_labels:
                    for vt in VTYPES:
                        csv_lines.append(f"{cl},{vt}," + ",".join("0" for _ in _yrs))
                st.download_button(
                    "Download CSV Template (VHT)",
                    "\n".join(csv_lines),
                    file_name="cba_vht_template.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                st.caption("Install openpyxl for the full Excel template.")

    st.divider()

    # ── VHT ───────────────────────────────────────────────────────────────
    with st.expander("VHT — Vehicle Hours Travelled (veh-hrs / peak period)", expanded=True):
        st.caption(
            "Used directly for Travel Time Savings calculation. "
            "Speed = VKT / VHT (derived, not entered)."
        )
        render_traffic_matrix("vht", "veh-hrs / peak period")

    # ── VKT ───────────────────────────────────────────────────────────────
    with st.expander("VKT — Vehicle Kilometres Travelled (veh-km / peak period)", expanded=True):
        st.caption(
            "Used for VOC, emissions, air pollution, and noise calculations. "
            "Speed (km/h) = VKT ÷ VHT."
        )
        render_traffic_matrix("vkt", "veh-km / peak period")

    # ── Demand ────────────────────────────────────────────────────────────
    with st.expander("Demand (person-trips / peak period)", expanded=False):
        st.info(
            "Demand data is captured for reference only. "
            "It does not affect benefit calculations — Travel Time Savings are driven by VHT, not demand."
        )
        render_traffic_matrix("demand", "person-trips / peak period")

    # ── Crashes by Severity ──────────────────────────────────────────────
    with st.expander("Crashes by Severity", expanded=False):
        st.info(
            "Safety benefits currently use blended $/VKT rates (see Parameters tab). "
            "Per-severity crash analysis will be available in a future update. "
            "Enter crash counts by severity and modelling year below for reference."
        )
        _sev_labels = ["Fatal", "Serious", "Moderate", "Minor", "PDO"]
        _case_keys = ["base_case"] + [f"project_{i}" for i in range(1, st.session_state.n_project_cases + 1)]
        _case_labels = ["Base Case"] + [f"Project {i}" for i in range(1, st.session_state.n_project_cases + 1)]
        _years = st.session_state["modelling_years"]
        if "crash_data" not in st.session_state:
            st.session_state["crash_data"] = {
                ck: {sev: [0.0] * len(_years) for sev in _sev_labels}
                for ck in _case_keys
            }
        _cd = st.session_state["crash_data"]
        for _ck, _cl in zip(_case_keys, _case_labels):
            st.markdown(f"**{_cl}**")
            _crash_rows = []
            for sev in _sev_labels:
                _row = {str(y): _cd[_ck].get(sev, [0.0] * len(_years))[yi] for yi, y in enumerate(_years)}
                _row["Severity"] = sev
                _crash_rows.append(_row)
            _crash_df = pd.DataFrame(_crash_rows).set_index("Severity")[[str(y) for y in _years]]
            _edited = st.data_editor(
                _crash_df,
                use_container_width=True,
                key=f"crash_{_ck}_{st.session_state.get('_crash_edit_counter', 0)}",
                num_rows="fixed",
            )
            for _si, sev in enumerate(_sev_labels):
                for _yi, y in enumerate(_years):
                    _cd[_ck][sev][_yi] = float(_edited.iloc[_si][str(y)])
        st.session_state["crash_data"] = _cd

    # ── Safety $/VKT ──────────────────────────────────────────────────────
    if st.session_state.get("safety_mode", "General") == "Detailed":
        with st.expander("Safety $/VKT — Cost rates per vehicle type", expanded=True):
            st.caption(
                "Safety cost rate ($/VKT) per vehicle type for each case. "
                "Benefit = Base VKT × Base rate − Project VKT × Project rate."
            )
            _svd = st.session_state["safety_vkt_data"]
            _sv_case_keys = ["base_case"] + [f"project_{i}" for i in range(1, st.session_state.n_project_cases + 1)]
            _sv_case_labels = ["Base Case"] + [f"Project {i}" for i in range(1, st.session_state.n_project_cases + 1)]
            for _ck, _cl in zip(_sv_case_keys, _sv_case_labels):
                with st.expander(_cl, expanded=True):
                    _cols = st.columns(4)
                    for _vt, _col in zip(VTYPES, _cols):
                        _svd[_ck][_vt] = _col.number_input(
                            _vt, min_value=0.0, max_value=10.0,
                            value=float(_svd[_ck].get(_vt, PARAMS["safety_vkt"][_vt])),
                            step=0.001, format="%.3f",
                            key=f"sv_{_ck}_{_vt}",
                        )
            st.session_state["safety_vkt_data"] = _svd

    # ── Costs ─────────────────────────────────────────────────────────────
    with st.expander("Costs — Capital & Recurrent ($M, undiscounted)", expanded=True):
        st.caption(
            "Per project case. Base Case has no project costs. Construction cost is spread "
            "evenly over the construction period defined in Project Details (sidebar)."
        )
        render_cost_entry(eval_period=eval_period)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: DASHBOARD — Charts
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.markdown('<div class="section-header">Analysis Charts</div>', unsafe_allow_html=True)

    # ── Case selector (Step 10): pick which project case drives pie & waterfall ─
    _n_dash = st.session_state.n_project_cases
    _CASE_PALETTE = ["#0d6efd", "#fd7e14", "#198754", "#dc3545", "#6610f2"]

    if not matrix_results:
        st.info("Enter traffic data in the **Data Input** tab to see charts.")
        st.stop()

    if _n_dash > 1:
        _dash_case = st.selectbox(
            "Project case to display in charts",
            options=[f"project_{i}" for i in range(1, _n_dash + 1)],
            format_func=lambda k: f"Project {k.split('_')[1]}",
            key="dash_case_sel",
        )
        _r = matrix_results[_dash_case]
    else:
        _r = matrix_results["project_1"]

    chart1, chart2 = st.columns(2)

    _reliability_mode = st.session_state.get("reliability_mode", "General")

    with chart1:
        st.subheader("Benefit Composition (PV $M)")
        pv = _r["pv_by_type"]
        # Build display-layer PV dict respecting estimation mode for reliability
        _pv_display = dict(pv)
        if _reliability_mode == "General":
            _pv_display["tts"] = pv.get("tts", 0) + pv.get("reliability", 0)
            _pv_display["reliability"] = 0.0
        if "pavement" not in _pv_display:
            _pv_display["pavement"] = 0.0
        _bar_types = ["tts", "voc", "safety", "env", "active", "pavement"]
        if _reliability_mode != "General":
            _bar_types.insert(1, "reliability")
        _bar_labels = [TYPE_LABELS[t] for t in _bar_types]
        _bar_values = [round(_pv_display.get(t, 0), 2) for t in _bar_types]
        _bar_colors = [COLORS.get(t, "#6c757d") for t in _bar_types]
        fig_bar = go.Figure()
        for i, (lbl, val, clr) in enumerate(zip(_bar_labels, _bar_values, _bar_colors)):
            bar_color = clr if val >= 0 else "#dc3545"
            fig_bar.add_trace(go.Bar(
                y=[lbl], x=[val], orientation="h",
                marker_color=bar_color,
                text=[f"${val:+.1f}M"], textposition="auto",
                textfont_size=11, showlegend=False,
                hovertemplate=f"{lbl}: ${{x:+.2f}}M<extra></extra>",
            ))
        fig_bar.add_vline(x=0, line_width=1, line_color="#888888")
        fig_bar.update_layout(
            height=max(300, 45 * len(_bar_types) + 80),
            margin=dict(t=20, b=30, l=160, r=40),
            xaxis_title="Present Value ($M)",
            bargap=0.35,
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with chart2:
        st.subheader("NPV Waterfall ($M)")
        # Build waterfall series respecting reliability mode
        if _reliability_mode == "General":
            _wf_types = ["tts", "voc", "safety", "env", "active"]
            _wf_labels_benefit = [
                "Travel Time & Reliability", "Vehicle Operating Costs",
                "Safety", "Environmental", "Active Transport",
            ]
        else:
            _wf_types = list(TYPE_LABELS.keys())
            _wf_labels_benefit = list(TYPE_LABELS.values())
        _wf_pv_vals = [_pv_display.get(t, 0) for t in _wf_types]
        wf_labels = _wf_labels_benefit + ["Total Benefits", "Costs", "NPV"]
        wf_values = _wf_pv_vals + [_r["pv_benefits"], -_r["pv_costs"], _r["npv"]]
        wf_measures = ["relative"] * len(_wf_types) + ["total", "relative", "total"]
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

    # ── Row 2: Cashflow & Cumulative ─────────────────────────────────────────
    chart3, chart4 = st.columns(2)
    _years_dash = list(range(construction_start_year, construction_start_year + _r["total_years"]))

    with chart3:
        st.subheader("Annual Net Cashflow ($M, undiscounted)")
        fig_cf = go.Figure()
        if matrix_results and _n_dash > 1:
            # Overlay net cashflow for every project case
            for _i in range(1, _n_dash + 1):
                _mr_i = matrix_results.get(f"project_{_i}", {})
                if _mr_i:
                    fig_cf.add_trace(go.Scatter(
                        x=list(range(construction_start_year, construction_start_year + _mr_i["total_years"])),
                        y=_mr_i["annual_net"],
                        name=f"Project {_i} Net", mode="lines+markers",
                        line=dict(color=_CASE_PALETTE[(_i - 1) % len(_CASE_PALETTE)], width=2),
                        marker=dict(size=4),
                    ))
        else:
            fig_cf.add_trace(go.Bar(
                x=_years_dash, y=[-c for c in _r["annual_costs"]],
                name="Costs", marker_color=COLORS["negative"], opacity=0.7,
            ))
            fig_cf.add_trace(go.Bar(
                x=_years_dash, y=_r["annual_benefits"],
                name="Benefits", marker_color=COLORS["positive"], opacity=0.7,
            ))
            fig_cf.add_trace(go.Scatter(
                x=_years_dash, y=_r["annual_net"],
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
        if matrix_results and _n_dash > 1:
            # Overlay cumulative NPV for every project case
            for _i in range(1, _n_dash + 1):
                _mr_i = matrix_results.get(f"project_{_i}", {})
                if _mr_i:
                    _col_i = _CASE_PALETTE[(_i - 1) % len(_CASE_PALETTE)]
                    fig_cum.add_trace(go.Scatter(
                        x=list(range(construction_start_year, construction_start_year + _mr_i["total_years"])),
                        y=_mr_i["cum_disc_net"],
                        mode="lines", name=f"Project {_i}",
                        line=dict(color=_col_i, width=2),
                    ))
                    if _mr_i.get("payback_year"):
                        fig_cum.add_vline(
                            x=construction_start_year + _mr_i["payback_year"] - 1,
                            line_dash="dot", line_color=_col_i, opacity=0.5,
                        )
        else:
            fig_cum.add_trace(go.Scatter(
                x=_years_dash, y=_r["cum_disc_net"],
                fill="tozeroy", mode="lines",
                line=dict(color=COLORS["neutral"], width=2.5),
                fillcolor="rgba(13, 110, 253, 0.15)",
                name="Cumulative NPV",
            ))
            if _r.get("payback_year"):
                _pb_cal = construction_start_year + _r["payback_year"] - 1
                fig_cum.add_vline(
                    x=_pb_cal, line_dash="dot",
                    line_color=COLORS["positive"], opacity=0.7,
                    annotation_text=f"Payback: {_pb_cal}",
                    annotation_position="top right",
                )
        fig_cum.add_hline(y=0, line_dash="dash", line_color="#6c757d", opacity=0.5)
        fig_cum.update_layout(
            height=400, margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="Year", yaxis_title="$M",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_cum, use_container_width=True)

    # ── Incremental Benefits Summary (Step 11) ───────────────────────────────
    st.divider()
    render_incremental_summary()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: DETAILED CASHFLOW
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cashflow:
    st.markdown('<div class="section-header">Year-by-Year Cashflow</div>', unsafe_allow_html=True)

    if not matrix_results:
        st.info("Enter traffic data in the **Data Input** tab to see cashflow.")
        st.stop()

    _cf_case_keys = list(matrix_results.keys())
    if len(_cf_case_keys) > 1:
        _cf_case_labels = {k: f"Project Case {k.split('_')[1]}" for k in _cf_case_keys}
        _cf_sel = st.selectbox(
            "Project Case",
            options=_cf_case_keys,
            format_func=lambda k: _cf_case_labels[k],
            key="cf_case_sel",
        )
        _cf_filename_suffix = f"-{_cf_sel}"
    else:
        _cf_sel = _cf_case_keys[0]
        _cf_filename_suffix = ""
    _r_cf = matrix_results[_cf_sel]

    view_mode = st.radio("Values", ["Undiscounted", "Discounted"], horizontal=True, key="cf_view")
    years_list = list(range(construction_start_year, construction_start_year + _r_cf["total_years"]))

    tts_breakdown = st.toggle("Show TTS by vehicle type", value=False, key="cf_tts_breakdown")

    _cf_reliability_mode = st.session_state.get("reliability_mode", "General")
    _cf_env_mode = st.session_state.get("env_mode", "General")

    if view_mode == "Undiscounted":
        _bbt = _r_cf["benefits_by_type"]
        _ny = _r_cf["total_years"]
        _tts_cols: dict = {}
        if tts_breakdown:
            _tts_cols = {
                "TTS — Car ($M)": [round(v, 3) for v in _bbt.get("tts_Car", [0.0] * _ny)],
                "TTS — LCV ($M)": [round(v, 3) for v in _bbt.get("tts_LCV", [0.0] * _ny)],
                "TTS — HCV ($M)": [round(v, 3) for v in _bbt.get("tts_HCV", [0.0] * _ny)],
                "TTS — Bus ($M)": [round(v, 3) for v in _bbt.get("tts_Bus", [0.0] * _ny)],
            }
        # Reliability: General → fold into TTS; Detailed → separate column
        if _cf_reliability_mode == "General":
            _tts_vals = [round(t + r, 3) for t, r in zip(_bbt["tts"], _bbt["reliability"])]
            _tts_label = "Travel Time & Reliability ($M)"
            _rel_cols: dict = {}
        else:
            _tts_vals = [round(v, 3) for v in _bbt["tts"]]
            _tts_label = "TTS ($M)"
            _rel_cols = {"Reliability ($M)": [round(v, 3) for v in _bbt["reliability"]]}
        # Environmental: General → single combined column; Detailed → CO₂ + Air & Noise
        _env_emit = _r_cf.get("annual_env_emit", [0.0] * _ny)
        if _cf_env_mode == "General":
            _env_cols = {"Environmental ($M)": [round(v, 3) for v in _bbt["env"]]}
        else:
            _env_cols = {
                "CO₂ Emission Cost ($M)": [round(v, 3) for v in _env_emit],
                "Air Quality & Noise ($M)": [round(e - em, 3) for e, em in zip(_bbt["env"], _env_emit)],
            }
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Costs ($M)": [round(c, 3) for c in _r_cf["annual_costs"]],
            "Benefits ($M)": [round(b, 3) for b in _r_cf["annual_benefits"]],
            _tts_label: _tts_vals,
            **_tts_cols,
            **_rel_cols,
            "VOC ($M)": [round(v, 3) for v in _bbt["voc"]],
            "Safety ($M)": [round(v, 3) for v in _bbt["safety"]],
            **_env_cols,
            "Active Transport ($M)": [round(v, 3) for v in _bbt["active"]],
            "Net ($M)": [round(n, 3) for n in _r_cf["annual_net"]],
        })
    else:
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Costs ($M)": [round(c, 3) for c in _r_cf["disc_costs"]],
            "Benefits ($M)": [round(b, 3) for b in _r_cf["disc_benefits"]],
            "Net ($M)": [round(n, 3) for n in _r_cf["disc_net"]],
            "Cumulative Net ($M)": [round(c, 3) for c in _r_cf["cum_disc_net"]],
        })

    st.dataframe(df_cf, use_container_width=True, hide_index=True)

    # Download for this table
    cf_csv = df_cf.to_csv(index=False)
    _dl_col1, _dl_col2 = st.columns([1, 1])
    with _dl_col1:
        st.download_button(
            f"Download {view_mode} Cashflow CSV",
            cf_csv,
            file_name=f"cashflow-{view_mode.lower()}{_cf_filename_suffix}.csv",
            mime="text/csv",
            key="dl_cashflow",
        )
    with _dl_col2:
        _full_export_r = matrix_results.get(_cf_sel, {})
        if _full_export_r:
            _full_csv = generate_csv(_full_export_r, project_name)
            _case_label = f"project-{_cf_sel.split('_')[1]}" if "_" in _cf_sel else _cf_sel
            st.download_button(
                "Download Full Results CSV",
                _full_csv,
                file_name=f"cba-results-{_case_label}.csv",
                mime="text/csv",
                key="dl_full_results",
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: SENSITIVITY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sensitivity:
    # --- Existing sensitivity charts ---
    st.markdown('<div class="section-header">Sensitivity Analysis</div>', unsafe_allow_html=True)

    if not matrix_results:
        st.info("Enter traffic data in the **Data Input** tab to see sensitivity analysis.")
        st.stop()

    _sens_case_keys = list(matrix_results.keys())
    if len(_sens_case_keys) > 1:
        _sens_case_labels = {k: f"Project Case {k.split('_')[1]}" for k in _sens_case_keys}
        _sens_sel = st.selectbox(
            "Project Case",
            options=_sens_case_keys,
            format_func=lambda k: _sens_case_labels[k],
            key="sens_case_sel",
        )
    else:
        _sens_sel = _sens_case_keys[0]
    _r_sens = matrix_results[_sens_sel]

    sen1, sen2 = st.columns(2)

    with sen1:
        st.subheader("Discount Rate Sensitivity (BCR)")
        dr_rates = sorted(_r_sens["sensitivity_dr"].keys())
        dr_bcrs = [_r_sens["sensitivity_dr"][r]["bcr"] for r in dr_rates]
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
        sw = _r_sens["switching"]
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
                height=420, margin=dict(t=20, b=20, l=180, r=80),
                xaxis_title="% Change Required", showlegend=False,
                **PLOTLY_TRANSPARENT,
            )
            st.plotly_chart(fig_sw, use_container_width=True)
        else:
            st.info("Insufficient data for switching values.")

    # --- Scenario Analysis Table ---
    st.subheader("Scenario Analysis")
    # TfNSW CBA / NSW Treasury TPG23-08 required sensitivity rates
    _tfnsw_required_rates = {5, 7, 10}
    rows = []
    for r_val in sorted(_r_sens["sensitivity_dr"].keys()):
        v = _r_sens["sensitivity_dr"][r_val]
        _req_tag = " ✦" if r_val in _tfnsw_required_rates else ""
        rows.append({
            "Scenario": f"Discount Rate {r_val}%{_req_tag}",
            "PV Benefits ($M)": round(v["pvb"], 1),
            "PV Costs ($M)": round(v["pvc"], 1),
            "NPV ($M)": round(v["npv"], 1),
            "BCR": round(v["bcr"], 2),
        })
    for label, v in _r_sens["scenarios"].items():
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
        _is_base = (f"Discount Rate {discount_rate}%" in row["Scenario"]
                    or f"Discount Rate {int(discount_rate)}%" in row["Scenario"]
                    or row["Scenario"] == "Demand Central")
        if _is_base:
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
    st.caption("✦ TfNSW CBA / NSW Treasury TPG23-08 required sensitivity rates: "
               "4% (low), 7% (base), 10% (high). ATAP T2 (2022) specifies the same core rates. "
               "3.5% = NSW Treasury long-run real risk-free rate (TPP20-07). "
               "Highlighted row = project base case discount rate.")

    # --- Carbon Price Sensitivity ---
    st.subheader("Carbon Price Sensitivity")
    _carbon_sens = _r_sens.get("sensitivity_carbon", {})
    if _carbon_sens:
        _c_labels = list(_carbon_sens.keys())
        _c_bcrs = [_carbon_sens[l]["bcr"] for l in _c_labels]
        _c_npvs = [_carbon_sens[l]["npv"] for l in _c_labels]
        _c_prices = [_carbon_sens[l]["carbon_price"] for l in _c_labels]
        _c_fig = go.Figure()
        _c_fig.add_trace(go.Bar(
            x=_c_labels, y=_c_bcrs,
            marker_color="#198754",
            text=[f"{v:.2f}" for v in _c_bcrs],
            textposition="outside",
        ))
        _c_fig.add_hline(y=1.0, line_dash="dash", line_color="red",
                         annotation_text="BCR = 1.0", annotation_position="top right")
        _c_fig.update_layout(
            yaxis_title="BCR", xaxis_title="Carbon Price Scenario",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=30, b=10), height=320,
        )
        st.plotly_chart(_c_fig, use_container_width=True)

        _c_rows = []
        for _lbl in _c_labels:
            _cv = _carbon_sens[_lbl]
            _c_rows.append({
                "Carbon Price Scenario": _lbl,
                "Carbon Price ($/tCO₂e)": _cv["carbon_price"],
                "PV Benefits ($M)": round(_cv["pvb"], 1),
                "NPV ($M)": round(_cv["npv"], 1),
                "BCR": round(_cv["bcr"], 2),
            })
        _df_c = pd.DataFrame(_c_rows)

        def _highlight_carbon(row):
            styles = [""] * len(row)
            if "Central" in row["Carbon Price Scenario"]:
                styles = ["background-color: rgba(25, 135, 84, 0.1); font-weight: 700"] * len(row)
            _bcr_idx = _df_c.columns.get_loc("BCR")
            if row["BCR"] >= 1:
                styles[_bcr_idx] += "; color: #198754; font-weight: 700"
            else:
                styles[_bcr_idx] += "; color: #dc3545; font-weight: 700"
            return styles

        _styled_c = _df_c.style.apply(_highlight_carbon, axis=1).format({
            "Carbon Price ($/tCO₂e)": "{:.2f}",
            "PV Benefits ($M)": "{:.1f}",
            "NPV ($M)": "{:.1f}",
            "BCR": "{:.2f}",
        })
        st.dataframe(_styled_c, use_container_width=True, hide_index=True)
        st.caption(
            "Scales only the emission_cost (carbon) component of environmental benefits; "
            "air pollution and noise costs are held at base values. "
            "Base: $123/tCO₂e (TfNSW EPV Jan 2025). "
            "Treasury: $135.74/tCO₂e (NSW Treasury TPG24-34). "
            "Highlighted row = Central (base case) carbon price."
        )
    else:
        st.info("No carbon sensitivity data available.")

    # --- Wider Economic Benefits (WEBs) Sensitivity ---
    st.subheader("Wider Economic Benefits (WEBs) Sensitivity")
    st.caption(
        "WEBs represent productivity gains not captured in conventional transport benefits "
        "(agglomeration, labour supply, imperfect competition). TfNSW and ATAP guidelines "
        "treat WEBs as additive to PV Benefits — typically 10–20% of PV Travel Time Savings "
        "for urban projects, lower for rural. "
        "WEBs are shown separately and are **not included in the primary BCR or NPV** reported above."
    )
    _pv_tts = _r_sens["pv_by_type"].get("tts", 0.0)
    _pv_costs_sens = _r_sens["pv_costs"]
    _pv_benefits_sens = _r_sens["pv_benefits"]

    _web_scenarios = [
        ("No WEBs (0%)", 0.0),
        ("Low — Rural / minor road (5%)", 0.05),
        ("Low-Medium — Regional road (10%)", 0.10),
        ("Medium — Urban arterial (15%)", 0.15),
        ("High — Urban strategic corridor (20%)", 0.20),
        ("Very High — Major urban CBD access (30%)", 0.30),
    ]
    _web_rows = []
    for _wlabel, _wfactor in _web_scenarios:
        _web_pvb_add = _pv_tts * _wfactor
        _adj_pvb = _pv_benefits_sens + _web_pvb_add
        _adj_npv = _adj_pvb - _pv_costs_sens
        _adj_bcr = _adj_pvb / _pv_costs_sens if _pv_costs_sens > 0 else 0.0
        _web_rows.append({
            "WEB Scenario": _wlabel,
            "WEB Uplift ($M)": round(_web_pvb_add, 1),
            "Adjusted PV Benefits ($M)": round(_adj_pvb, 1),
            "Adjusted NPV ($M)": round(_adj_npv, 1),
            "Adjusted BCR": round(_adj_bcr, 2),
        })
    _df_web = pd.DataFrame(_web_rows)

    def _highlight_web(row):
        styles = [""] * len(row)
        if "No WEBs" in row["WEB Scenario"]:
            styles = ["background-color: rgba(13, 110, 253, 0.08); font-weight: 700"] * len(row)
        _bcr_idx = _df_web.columns.get_loc("Adjusted BCR")
        if row["Adjusted BCR"] >= 1:
            styles[_bcr_idx] += "; color: #198754; font-weight: 700"
        else:
            styles[_bcr_idx] += "; color: #dc3545; font-weight: 700"
        return styles

    _styled_web = _df_web.style.apply(_highlight_web, axis=1).format({
        "WEB Uplift ($M)": "{:.1f}",
        "Adjusted PV Benefits ($M)": "{:.1f}",
        "Adjusted NPV ($M)": "{:.1f}",
        "Adjusted BCR": "{:.2f}",
    })
    st.dataframe(_styled_web, use_container_width=True, hide_index=True)
    st.caption(
        "WEB uplift = WEB factor × PV Travel Time Savings. "
        "Highlighted row = base case (no WEBs). "
        "Source: TfNSW Infrastructure Investor Assurance Framework; ATAP T2 (2022) §6. "
        "WEB factors are indicative — apply project-specific agglomeration analysis for "
        "major submissions to Infrastructure NSW or NSW Treasury."
    )

    # --- VSL Sensitivity ---
    st.subheader("Value of Statistical Life (VSL) Sensitivity")
    st.caption(
        "Scales only the fatal crash cost component of safety benefits "
        f"({PARAMS['safety_severity_share']['fatal']*100:.0f}% of blended safety PV by default). "
        "Serious injury, minor, and PDO components are held at base values. "
        "Source: TfNSW EPV Jan 2025 — VSL = $8.1M (June 2024 prices)."
    )
    _vsl_sens = _r_sens.get("sensitivity_vsl", {})
    if _vsl_sens:
        _vsl_labels = list(_vsl_sens.keys())
        _vsl_bcrs = [_vsl_sens[l]["bcr"] for l in _vsl_labels]
        _vsl_fig = go.Figure()
        _vsl_fig.add_trace(go.Bar(
            x=_vsl_labels, y=_vsl_bcrs,
            marker_color=COLORS["safety"],
            text=[f"{v:.2f}" for v in _vsl_bcrs],
            textposition="outside",
        ))
        _vsl_fig.add_hline(y=1.0, line_dash="dash", line_color="red",
                           annotation_text="BCR = 1.0", annotation_position="top right")
        _vsl_fig.update_layout(
            yaxis_title="BCR", xaxis_title="VSL Scenario",
            **PLOTLY_TRANSPARENT,
            margin=dict(t=30, b=10), height=320,
        )
        st.plotly_chart(_vsl_fig, use_container_width=True)

        _vsl_rows = []
        for _lbl in _vsl_labels:
            _vv = _vsl_sens[_lbl]
            _vsl_rows.append({
                "VSL Scenario": _lbl,
                "VSL ($M)": _vv["vsl"],
                "PV Benefits ($M)": round(_vv["pvb"], 1),
                "NPV ($M)": round(_vv["npv"], 1),
                "BCR": round(_vv["bcr"], 2),
            })
        _df_vsl = pd.DataFrame(_vsl_rows)

        def _highlight_vsl(row):
            styles = [""] * len(row)
            if "Central" in row["VSL Scenario"]:
                styles = ["background-color: rgba(220, 53, 69, 0.08); font-weight: 700"] * len(row)
            _bcr_idx = _df_vsl.columns.get_loc("BCR")
            if row["BCR"] >= 1:
                styles[_bcr_idx] += "; color: #198754; font-weight: 700"
            else:
                styles[_bcr_idx] += "; color: #dc3545; font-weight: 700"
            return styles

        _styled_vsl = _df_vsl.style.apply(_highlight_vsl, axis=1).format({
            "VSL ($M)": "{:.2f}",
            "PV Benefits ($M)": "{:.1f}",
            "NPV ($M)": "{:.1f}",
            "BCR": "{:.2f}",
        })
        st.dataframe(_styled_vsl, use_container_width=True, hide_index=True)
        st.caption(
            "Highlighted row = Central (base case) VSL. "
            "Only the fatal component of safety benefits is scaled; other severity classes are unchanged. "
            "Source: TfNSW EPV Jan 2025; ATAP T2 (2022) recommends ±30% VSL sensitivity."
        )
    else:
        st.info("No VSL sensitivity data available.")

    # --- First-Year Benefit Breakdown ---
    st.markdown('<div class="section-header">First-Year Benefit Breakdown ($M)</div>', unsafe_allow_html=True)
    fy = _r_sens["first_year"]
    with st.expander("First-Year Detail", expanded=True):
        fy_cols = st.columns(8)
        for i, (key, label) in enumerate(TYPE_LABELS.items()):
            with fy_cols[i]:
                st.metric(label, f"${fy.get(key, 0.0):.2f}M")
        with fy_cols[7]:
            st.metric("Total", f"${fy.get('total', 0.0):.2f}M")

    # --- Monte Carlo Risk Analysis (advanced only) ---
    if show_advanced:
        st.markdown('<div class="section-header">Monte Carlo Risk Analysis</div>', unsafe_allow_html=True)
        st.caption(
            "Simulates outcome uncertainty by sampling key inputs from probability distributions:\n"
            "• VTTS ~ Normal(μ, CV%)\n"
            "• Safety $/VKT ~ Lognormal(μ, CV%)\n"
            "• Traffic volume ~ Normal(μ, CV%)\n"
            "• Capital cost ~ Triangular(min, mode, max)"
        )

        _mc_col1, _mc_col2 = st.columns(2)
        with _mc_col1:
            _mc_n = st.slider("Number of simulations", 10, 50, 50, step=10, key="mc_n")
            _mc_demand = st.slider("Traffic volume uncertainty (CV %)", 1, 30, 15, key="mc_demand",
                                   help="Coefficient of variation for traffic VHT/VKT (normal distribution). 15% → roughly ±30% at 2σ.")
            _mc_vtts = st.slider("VTTS uncertainty (CV %)", 1, 30, 20, key="mc_vtts",
                                 help="Coefficient of variation for Value of Travel Time Savings (normal distribution).")
        with _mc_col2:
            _mc_safety = st.slider("Safety rate uncertainty (CV %)", 1, 50, 30, key="mc_safety",
                                   help="Coefficient of variation for safety $/VKT rates (lognormal distribution).")
            _mc_cost = st.slider("Capital cost overrun max %", 0, 100, 40, key="mc_cost",
                                 help="Maximum capital cost overrun as % above base. Triangular distribution: base, +½max, +max.")

        if st.button("Run Monte Carlo", key="mc_run"):
            _mc_case_keys = list(matrix_results.keys())
            _mc_all_results: dict = {}
            _eff_params = build_effective_params()
            _cost_overrun_max = 1.0 + _mc_cost / 100
            _cost_overrun_mode = 1.0 + _mc_cost / 200
            _mc_progress = st.progress(0, text=f"Running Monte Carlo simulation (0/{len(_mc_case_keys)} cases)…")
            for _mc_idx, _mc_ck in enumerate(_mc_case_keys):
                    _mc_result = run_monte_carlo(
                        case_key=_mc_ck,
                        inputs=_matrix_inputs,
                        traffic_data=st.session_state.traffic_data,
                        cost_data=st.session_state.cost_data,
                        annualisation=st.session_state.annualisation,
                        safety_vkt_data=st.session_state.safety_vkt_data,
                        params=_eff_params,
                        n_simulations=_mc_n,
                        vtts_cv=_mc_vtts / 100,
                        safety_cv=_mc_safety / 100,
                        traffic_cv=_mc_demand / 100,
                        cost_overrun_min=1.0,
                        cost_overrun_mode=_cost_overrun_mode,
                        cost_overrun_max=_cost_overrun_max,
                    )
                    # Convert numpy arrays to lists for JSON-serialisable session state
                    _mc_all_results[_mc_ck] = {
                        **_mc_result,
                        "npv": list(_mc_result["npv"]),
                        "bcr": list(_mc_result["bcr"]),
                    }
                    _mc_progress.progress((_mc_idx + 1) / len(_mc_case_keys),
                        text=f"Running Monte Carlo simulation ({_mc_idx + 1}/{len(_mc_case_keys)} cases)…")
            st.session_state["mc_results"] = _mc_all_results

        if st.session_state.get("mc_results"):
            _mc_res = st.session_state["mc_results"]
            _mc_display_key = _sens_sel if len(_mc_res) > 1 else list(_mc_res.keys())[0]
            if _mc_display_key not in _mc_res:
                _mc_display_key = list(_mc_res.keys())[0]
            _mc_r = _mc_res[_mc_display_key]
            _npvs = _mc_r["npv"]
            _bcrs = _mc_r["bcr"]
            _npv_pct = _mc_r["npv_percentiles"]
            _bcr_pct = _mc_r["bcr_percentiles"]
            _p10_npv, _p50_npv, _p90_npv = _npv_pct["p10"], _npv_pct["p50"], _npv_pct["p90"]
            _p10_bcr, _p50_bcr, _p90_bcr = _bcr_pct["p10"], _bcr_pct["p50"], _bcr_pct["p90"]
            _prob_pos_npv = _mc_r["prob_npv_positive"] * 100
            _prob_bcr_ge1 = _mc_r["prob_bcr_gt1"] * 100
            _n_total = _mc_r["n_simulations"]
            _mean_npv = sum(_npvs) / _n_total
            _mean_bcr = sum(_bcrs) / _n_total

            _mc_chart1, _mc_chart2 = st.columns(2)
            with _mc_chart1:
                st.subheader("NPV Distribution ($M)")
                fig_mc_npv = go.Figure()
                fig_mc_npv.add_trace(go.Histogram(
                    x=_npvs, nbinsx=40, name="NPV",
                    marker_color=COLORS["tts"], opacity=0.75,
                ))
                for _pct_val, _pct_label, _pct_color in [
                    (_p10_npv, "P10", "#dc3545"),
                    (_p50_npv, "P50", "#fd7e14"),
                    (_p90_npv, "P90", "#198754"),
                ]:
                    fig_mc_npv.add_vline(
                        x=_pct_val, line_dash="dash", line_color=_pct_color,
                        annotation_text=f"{_pct_label}: ${_pct_val:.1f}M",
                        annotation_position="top right",
                    )
                fig_mc_npv.add_vline(x=0, line_dash="dot", line_color="#6c757d",
                                     annotation_text="NPV = 0")
                fig_mc_npv.update_layout(
                    height=350, xaxis_title="NPV ($M)", yaxis_title="Count",
                    showlegend=False, margin=dict(t=30, b=20, l=20, r=20),
                    **PLOTLY_TRANSPARENT,
                )
                st.plotly_chart(fig_mc_npv, use_container_width=True)

            with _mc_chart2:
                st.subheader("BCR Distribution")
                fig_mc_bcr = go.Figure()
                fig_mc_bcr.add_trace(go.Histogram(
                    x=_bcrs, nbinsx=40, name="BCR",
                    marker_color=COLORS["voc"], opacity=0.75,
                ))
                for _pct_val, _pct_label, _pct_color in [
                    (_p10_bcr, "P10", "#dc3545"),
                    (_p50_bcr, "P50", "#fd7e14"),
                    (_p90_bcr, "P90", "#198754"),
                ]:
                    fig_mc_bcr.add_vline(
                        x=_pct_val, line_dash="dash", line_color=_pct_color,
                        annotation_text=f"{_pct_label}: {_pct_val:.2f}",
                        annotation_position="top right",
                    )
                fig_mc_bcr.add_vline(x=1.0, line_dash="dot", line_color="#6c757d",
                                     annotation_text="BCR = 1.0")
                fig_mc_bcr.update_layout(
                    height=350, xaxis_title="BCR", yaxis_title="Count",
                    showlegend=False, margin=dict(t=30, b=20, l=20, r=20),
                    **PLOTLY_TRANSPARENT,
                )
                st.plotly_chart(fig_mc_bcr, use_container_width=True)

            # Tornado chart
            _tornado = _mc_r.get("tornado", {})
            if _tornado:
                st.subheader("Tornado Chart — NPV sensitivity (P10/P90 of each input)")
                _central_npv = _mc_r.get("central_npv", 0)
                _t_params = list(_tornado.keys())
                _t_low  = [_tornado[p][0] - _central_npv for p in _t_params]
                _t_high = [_tornado[p][1] - _central_npv for p in _t_params]
                # Sort by total swing descending
                _t_order = sorted(range(len(_t_params)),
                                  key=lambda i: abs(_t_high[i] - _t_low[i]), reverse=True)
                _t_params = [_t_params[i] for i in _t_order]
                _t_low    = [_t_low[i]    for i in _t_order]
                _t_high   = [_t_high[i]   for i in _t_order]
                fig_tornado = go.Figure()
                fig_tornado.add_trace(go.Bar(
                    y=_t_params, x=_t_low, orientation="h",
                    name="P10 effect", marker_color=COLORS["negative"],
                ))
                fig_tornado.add_trace(go.Bar(
                    y=_t_params, x=_t_high, orientation="h",
                    name="P90 effect", marker_color=COLORS["positive"],
                ))
                fig_tornado.update_layout(
                    barmode="overlay", height=300,
                    xaxis_title="NPV change vs central ($M)", yaxis_title="",
                    margin=dict(t=20, b=20, l=20, r=20),
                    **PLOTLY_TRANSPARENT,
                )
                st.plotly_chart(fig_tornado, use_container_width=True)

            # Summary statistics table
            _mc_stats = pd.DataFrame({
                "Statistic": ["Mean", "P10 (pessimistic)", "P50 (median)", "P90 (optimistic)",
                              "P(positive outcome)"],
                "NPV ($M)": [f"{_mean_npv:.1f}", f"{_p10_npv:.1f}", f"{_p50_npv:.1f}",
                             f"{_p90_npv:.1f}", f"{_prob_pos_npv:.0f}%"],
                "BCR": [f"{_mean_bcr:.2f}", f"{_p10_bcr:.2f}", f"{_p50_bcr:.2f}",
                        f"{_p90_bcr:.2f}", f"{_prob_bcr_ge1:.0f}%"],
            })
            st.dataframe(_mc_stats, use_container_width=True, hide_index=True)
            st.caption(
                f"{_n_total} simulations · "
                f"Traffic CV {st.session_state.get('mc_demand', 15)}% · "
                f"VTTS CV {st.session_state.get('mc_vtts', 20)}% · "
                f"Safety CV {st.session_state.get('mc_safety', 30)}% · "
                f"Cost overrun max +{st.session_state.get('mc_cost', 40)}%"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: PARAMETERS (EDITABLE)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_params:
    st.markdown('<div class="section-header">Economic Parameters</div>', unsafe_allow_html=True)
    st.caption("Edit values below. Changes take effect immediately in all calculations. "
               "Source: TfNSW Economic Parameter Values (January 2025), June 2024 prices.")

    _confirm_reset = st.checkbox("I understand this will reset all parameters to TfNSW defaults", key="confirm_reset_params")
    if st.button("Reset All to Defaults", key="reset_params", disabled=not _confirm_reset):
        for _k in list(st.session_state.keys()):
            if _k.startswith("param_"):
                del st.session_state[_k]
        st.rerun()

    # ── Value of Travel Time Savings ─────────────────────────────────────────
    with st.expander("Value of Travel Time Savings ($/person-hour)", expanded=True):
        _src_vtts = "TfNSW EPV Jan 2025, Table 3"
        st.caption("Applied per vehicle type: Car/Bus use commute rate; LCV/HCV use business rate.")
        for _ctx in ("urban", "rural"):
            st.markdown(f"**{_ctx.title()}**")
            for _vt, _label in [("Car", "Car"), ("LCV", "Light Commercial (LCV)"),
                                 ("HCV", "Heavy Commercial (HCV)"), ("Bus", "Bus")]:
                param_editor(
                    label=f"{_label} — {_ctx.title()}",
                    key=f"param_vtts_{_ctx}_{_vt}",
                    default=PARAMS["vtts"][_ctx][_vt],
                    min_val=0.0, max_val=10000.0, step=0.5,
                    unit="$/person-hr", source=_src_vtts,
                )

    # ── Vehicle Occupancy ────────────────────────────────────────────────────
    with st.expander("Vehicle Occupancy (persons/vehicle)"):
        _src_occ = "TfNSW EPV Jan 2025, Tables 2.4/2.5; ATAP 2016 PV2 (rural)"
        st.caption(
            "Converts VHT savings (vehicle-hours) to person-hours before applying VTTS. "
            "Car/Bus urban from 2014/15 HTS; rural from ATAP 2016 PV2. "
            "LCV = commercial driver (±1 passenger); HCV = driver only."
        )
        for _ctx in ("urban", "rural"):
            st.markdown(f"**{_ctx.title()}**")
            for _vt, _label in [("Car", "Car"), ("LCV", "Light Commercial (LCV)"),
                                 ("HCV", "Heavy Commercial (HCV)"), ("Bus", "Bus")]:
                param_editor(
                    label=f"{_label} — {_ctx.title()}",
                    key=f"param_occupancy_{_ctx}_{_vt}",
                    default=PARAMS["occupancy"][_ctx][_vt],
                    min_val=0.1, max_val=100.0, step=0.01,
                    unit="persons/veh", source=_src_occ,
                )

    # ── Reliability Ratio ────────────────────────────────────────────────────
    with st.expander("Reliability Ratio"):
        param_editor(
            label="Passenger Reliability Ratio — Car / Bus (of VTTS)",
            key="param_reliability_ratio",
            default=PARAMS["reliability_ratio"],
            min_val=0.0, max_val=2.0, step=0.05,
            unit="ratio", source="TfNSW EPV Jan 2025, §4.3",
        )
        param_editor(
            label="Freight Reliability Ratio — LCV / HCV (of VTTS)",
            key="param_reliability_ratio_freight",
            default=PARAMS["reliability_ratio_freight"],
            min_val=0.0, max_val=2.0, step=0.05,
            unit="ratio",
            source="TfNSW EPV Jan 2025 — freight travel-time variability has lower relative VTTS than passenger",
        )

    # ── Safety Cost ($/VKT) ───────────────────────────────────────────────────
    with st.expander("Safety Cost ($/VKT by vehicle type)"):
        st.caption("Safety benefit = (Base VKT − Project VKT) × rate × annualisation factor")
        for _vt in VTYPES:
            _default = PARAMS["safety_vkt"][_vt]
            param_editor(
                label=_vt,
                key=f"param_safety_vkt_{_vt}",
                default=_default,
                min_val=0.0, max_val=5.0, step=0.001,
                unit="$/VKT", source="Agency default",
            )
        st.markdown("**Crash Severity Shares** *(informational — used for VSL sensitivity only)*")
        _sev = PARAMS["safety_severity_share"]
        _sev_cols = st.columns(4)
        for _col, (_sev_key, _sev_label) in zip(
            _sev_cols,
            [("fatal", "Fatal"), ("serious", "Serious Injury"),
             ("minor", "Minor Injury"), ("pdo", "PDO")],
        ):
            _col.metric(_sev_label, f"{_sev[_sev_key]*100:.0f}%")
        st.caption(
            "These proportions decompose the blended $/VKT safety rate by crash severity class. "
            "They do not affect the core safety benefit — only the VSL sensitivity table in the "
            "Sensitivity tab. Source: TfNSW EPV Jan 2025 crash unit costs × NSW crash rate distribution."
        )

    # ── Emission Costs (CO₂) ─────────────────────────────────────────────────
    with st.expander("Emission Costs — CO₂ ($/veh-km)"):
        _src_emit = "TfNSW EPV Jan 2025, Table 14"
        for _ctx in ("urban", "rural"):
            st.markdown(f"**{_ctx.title()}**")
            for _vt, _label in [("car", "Car"), ("lgv", "LGV"), ("rigid", "Rigid Truck"), ("bus", "Bus")]:
                param_editor(
                    label=f"{_label} — {_ctx.title()}",
                    key=f"param_emission_{_ctx}_{_vt}",
                    default=PARAMS["emission_cost"][_ctx][_vt],
                    min_val=0.0, max_val=1.0, step=0.001,
                    unit="$/veh-km", source=_src_emit,
                )

    # ── Air Pollution ────────────────────────────────────────────────────────
    with st.expander("Air Pollution Costs ($/veh-km)"):
        _src_air = "TfNSW EPV Jan 2025, Table 15"
        for _ctx in ("urban", "rural"):
            st.markdown(f"**{_ctx.title()}**")
            for _vt, _label in [("car", "Car"), ("lgv", "LGV"), ("rigid", "Rigid Truck"), ("artic", "Articulated Truck")]:
                param_editor(
                    label=f"{_label} — {_ctx.title()}",
                    key=f"param_air_{_ctx}_{_vt}",
                    default=PARAMS["air_pollution"][_ctx][_vt],
                    min_val=0.0, max_val=1.0, step=0.001,
                    unit="$/veh-km", source=_src_air,
                )

    # ── Noise ────────────────────────────────────────────────────────────────
    with st.expander("Noise Costs ($/veh-km)"):
        _src_noise = "TfNSW EPV Jan 2025, Table 16"
        for _ctx in ("urban", "rural"):
            st.markdown(f"**{_ctx.title()}**")
            for _vt, _label in [("car", "Car"), ("lgv", "LGV"), ("rigid", "Rigid Truck"), ("artic", "Articulated Truck")]:
                param_editor(
                    label=f"{_label} — {_ctx.title()}",
                    key=f"param_noise_{_ctx}_{_vt}",
                    default=PARAMS["noise"][_ctx][_vt],
                    min_val=0.0, max_val=1.0, step=0.001,
                    unit="$/veh-km", source=_src_noise,
                )

    # ── Active Transport Health Benefits ─────────────────────────────────────
    with st.expander("Active Transport Health Benefits ($/person-km)"):
        _src_health = "TfNSW EPV Jan 2025, Table 18"
        param_editor(
            label="Walking",
            key="param_health_walking",
            default=PARAMS["health_benefits"]["walking"],
            min_val=0.0, max_val=5.0, step=0.01,
            unit="$/person-km", source=_src_health,
        )
        param_editor(
            label="Cycling",
            key="param_health_cycling",
            default=PARAMS["health_benefits"]["cycling"],
            min_val=0.0, max_val=5.0, step=0.01,
            unit="$/person-km", source=_src_health,
        )

    # ── VOC Speed Tables (read-only reference) ───────────────────────────────
    with st.expander("Vehicle Operating Costs — Urban ($/veh-km, read-only)"):
        speeds_urban = sorted(set().union(*[PARAMS["voc"]["urban"][v].keys() for v in ("car", "lgv", "rigid", "artic")]))
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

    with st.expander("Vehicle Operating Costs — Rural ($/veh-km, read-only)"):
        speeds_rural = sorted(set().union(*[PARAMS["voc"]["rural"][v].keys() for v in ("car", "lgv", "rigid", "artic")]))
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

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5: ABOUT
# ═══════════════════════════════════════════════════════════════════════════════
with tab_about:
    st.markdown("## About This Tool")
    st.markdown(
        "This dashboard helps CBA practitioners and business case writers in NSW "
        "assess the economic viability of transport infrastructure projects. "
        "It implements the **TfNSW Economic Parameter Values (January 2025, June 2024 prices)** "
        "framework and produces the standard outputs required for NSW Government business cases: "
        "Net Present Value (NPV), Benefit–Cost Ratio (BCR), and sensitivity analysis."
    )

    st.divider()

    # ── What the model calculates ────────────────────────────────────────────
    st.markdown("### What the Model Calculates")
    st.markdown(
        "The tool compares a **Base Case** (do-minimum, typically the existing network) "
        "against up to five **Project Cases** (proposed interventions). "
        "All benefits are *incremental* — the difference between each project case and the base case. "
        "Costs and benefits are discounted to a common base year, summed over the appraisal period, "
        "and expressed as:"
    )
    col_npv, col_bcr, col_pv = st.columns(3)
    with col_npv:
        st.info("**Net Present Value (NPV)**\nPV Benefits minus PV Costs. Positive NPV indicates the project returns more to society than it costs.")
    with col_bcr:
        st.info("**Benefit–Cost Ratio (BCR)**\nPV Benefits ÷ PV Costs. A BCR above 1.0 means benefits exceed costs. NSW Treasury typically requires BCR ≥ 1.5 for strong cases.")
    with col_pv:
        st.info("**Present Value of Benefits by Type**\nBreaks the total benefit into its components so you can see which categories drive the result.")

    st.divider()

    # ── Benefit categories ───────────────────────────────────────────────────
    st.markdown("### Benefit Categories")
    st.markdown(
        "The model quantifies five categories of economic benefit, all derived from changes in traffic "
        "volumes, travel times, and speeds between the base case and each project case:"
    )

    benefit_rows = [
        ("Travel Time Savings (TTS)", "tts", "blue",
         "The most significant benefit in most road projects. "
         "Calculated from the reduction in vehicle-hours travelled (VHT), multiplied by vehicle occupancy "
         "and the Value of Travel Time Savings (VTTS) rate. "
         "Car and Bus passengers use the personal travel rate (~$19.76/person-hr urban); "
         "freight vehicles (LCV, HCV) use the business rate (~$54.87/person-hr urban). "
         "Source: TfNSW EPV Table 3."),
        ("Vehicle Operating Costs (VOC)", "voc", "orange",
         "Savings in fuel, tyres, maintenance, and depreciation when a project changes vehicle speeds. "
         "Rates depend on speed (km/h) and are interpolated from TfNSW lookup tables "
         "(different tables for urban and rural contexts). "
         "Faster travel on a new bypass, for example, typically reduces VOC per kilometre. "
         "Source: TfNSW EPV Tables 5–8."),
        ("Safety", "safety", "red",
         "Reduction in crash costs when vehicle-kilometres travelled (VKT) change. "
         "Rates are expressed in dollars per vehicle-kilometre by vehicle type "
         "(e.g. Car: $0.153/veh-km). These already incorporate the Value of a Statistical Life "
         "(VSL: $8.1 million) blended across crash severity distributions. "
         "Source: TfNSW EPV Table 11."),
        ("Environmental", "env", "green",
         "Three components, all calculated per change in VKT: "
         "(1) **Carbon emissions** — fleet-average CO₂ factors × carbon price ($123/tonne); "
         "(2) **Air pollution** — local pollutants (NOx, PM2.5) priced at health damage costs; "
         "(3) **Noise** — annoyance and health impacts on surrounding residents. "
         "Urban rates are higher than rural for all three. "
         "Source: TfNSW EPV Tables 13–15."),
        ("Active Transport Health Benefits", "active", "purple",
         "Benefits from additional walking or cycling induced by the project, "
         "valued using health monetisation rates (Walking: $3.17/person-km; Cycling: $1.60/person-km). "
         "This component is zero unless demand data includes active mode trips. "
         "Source: TfNSW EPV Table 18."),
    ]

    for name, key, colour, explanation in benefit_rows:
        with st.expander(f"**{name}**"):
            st.markdown(explanation)

    st.divider()

    # ── How costs are treated ────────────────────────────────────────────────
    st.markdown("### How Costs Are Treated")
    st.markdown(
        "Project costs are entered in the **sidebar** and cover four categories:"
    )
    cost_data = {
        "Cost Category": [
            "Planning & design",
            "Land acquisition",
            "Construction",
            "Contingency",
            "Operating & maintenance (annual)",
            "Residual value",
        ],
        "How it is used": [
            "Treated as a lump-sum expenditure in the first year of the appraisal period.",
            "Treated as a lump-sum expenditure in the first year of the appraisal period.",
            "Spread evenly across the construction period and discounted.",
            "Applied as a percentage uplift on the sum of planning, land, and construction costs.",
            "Repeated each year over the appraisal period and discounted.",
            "A negative cost (credit) applied in the final year, representing the remaining useful life of assets.",
        ],
    }
    st.dataframe(pd.DataFrame(cost_data), hide_index=True, use_container_width=True)

    st.divider()

    # ── Discounting ─────────────────────────────────────────────────────────
    st.markdown("### Discounting")
    st.markdown(
        "All future cash flows are converted to present-value terms using a **start-of-year** "
        "discount convention: a dollar in year *n* is worth `1 / (1 + r)^n` today, "
        "where *r* is the discount rate. "
        "The default rate is **7%** per annum, consistent with NSW Treasury guidance for transport "
        "infrastructure. Sensitivity analysis automatically re-runs the model at 4% and 10% "
        "so you can report the standard three-rate range required by Infrastructure Australia "
        "and NSW Treasury."
    )

    st.divider()

    # ── Annualisation ───────────────────────────────────────────────────────
    st.markdown("### From Model Years to Annual Traffic")
    st.markdown(
        "Traffic models typically produce results for a small number of **modelling years** "
        "(e.g. 2026, 2031, 2041, 2056). The tool interpolates between these years using "
        "**compound annual growth rate (CAGR)** — the geometric mean — rather than straight-line "
        "interpolation. This better reflects how traffic volumes typically grow."
    )
    st.markdown(
        "Peak-period model outputs are converted to annual totals using an "
        "**annualisation factor** and **days per year** for each vehicle type. "
        "These defaults reflect typical NSW peak-period survey expansion factors "
        "and can be adjusted in the sidebar."
    )

    st.divider()

    # ── Sensitivity analysis ─────────────────────────────────────────────────
    st.markdown("### Sensitivity Analysis")
    st.markdown(
        "The **Sensitivity** tab reports three types of analysis automatically:"
    )
    sens_rows = [
        ("Discount rate sensitivity", "Re-runs NPV and BCR at 4%, 7%, and 10% to show how sensitive the result is to the choice of discount rate."),
        ("Switching values", "Calculates how far key inputs (benefits, costs, demand) would have to move before the BCR falls below 1.0. This tells decision-makers the margin of safety in the result."),
        ("Scenario analysis", "Applies optimistic (+20% benefits, –10% costs) and pessimistic (–20% benefits, +20% costs) scenarios to bound the likely range of outcomes."),
    ]
    sens_df = pd.DataFrame(sens_rows, columns=["Analysis", "What it shows"])
    st.dataframe(sens_df, hide_index=True, use_container_width=True)

    st.divider()

    # ── Parameter sources ────────────────────────────────────────────────────
    st.markdown("### Parameter Sources and Overrides")
    st.markdown(
        "All default parameter values are sourced from the "
        "**TfNSW Economic Parameter Values, January 2025 (June 2024 prices)**. "
        "These are the values that should be used in NSW Government business cases unless "
        "a project-specific study has been approved by TfNSW."
    )
    st.markdown(
        "The **Parameters** tab lets you view and override individual values "
        "(e.g. VTTS rates, VOC tables, carbon price) if your business case has approved "
        "project-specific values. Overrides are applied at calculation time and do not "
        "permanently alter the default parameters."
    )

    st.divider()

    # ── Limitations ──────────────────────────────────────────────────────────
    st.markdown("### Limitations and Appropriate Use")
    st.warning(
        "**This tool supports, but does not replace, professional CBA judgement.** "
        "It does not cover all benefit categories recognised in the TfNSW framework — "
        "for example, wider economic benefits (agglomeration, labour market impacts), "
        "public transport fare revenue, or land-use change benefits are not modelled. "
        "For large or complex projects, outputs should be reviewed by an accredited "
        "transport economist before inclusion in a formal business case.",
        icon="⚠️",
    )

    st.markdown(
        "| Suitable for | Not suitable for |\n"
        "|---|---|\n"
        "| Early-stage option screening | Final submission to Infrastructure Australia |\n"
        "| Sensitivity and switching value testing | Projects with significant PT or active-mode mode shift |\n"
        "| Checking third-party CBA outputs | Projects requiring wider economic benefit analysis |\n"
        "| Internal workshop and briefing support | Projects where NTC emission factors may be materially inaccurate |"
    )

    st.divider()

    # ── Reference ────────────────────────────────────────────────────────────
    st.markdown("### Key References")
    st.markdown(
        "- Transport for NSW — *Economic Parameter Values*, January 2025 (June 2024 prices)\n"
        "- NSW Treasury — *NSW Government Guide to Cost-Benefit Analysis* (TPP17-03)\n"
        "- Infrastructure Australia — *Assessment Framework*, 2021\n"
        "- National Transport Commission — *Australian Fleet Emission Factors*, 2023\n"
        "- Department of Infrastructure, Transport, Regional Development, Communications and the Arts — "
        "*Australian Transport Assessment and Planning (ATAP) Guidelines*"
    )

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Transport CBA Dashboard · Parameters based on TfNSW Economic Parameter Values (Jan 2025) · For practitioner use · Not for public distribution")
