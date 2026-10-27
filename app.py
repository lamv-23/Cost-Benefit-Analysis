"""
Transport Cost-Benefit Analysis Dashboard
Parameters based on TfNSW Economic Parameter Values (January 2025)
All monetary values in June 2026 prices (AUD)
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

from cba_engine import (  # noqa: E402,F401
    PARAMS, VTYPES, PRICE_YEAR, PRICE_LABEL, CPI_JUNE_2024_TO_2026,
    crash_cost_per_vkt, project_price_year, index_costs, ASSET_LIVES,
    DEFAULT_MODELLING_YEARS, TYPE_LABELS, CARBON_VALUES,
    make_traffic_case, make_traffic_data, make_cost_data,
    COST_FORMAT_VERSION, CAPEX_CATEGORIES, clean_row, make_base_case_costs,
    fit_cost_rows, build_cost_schedule, validate_project_file,
    discount_factor, interpolate_voc, _cagr_interpolate, interpolate_modelling_years,
    calculate_matrix, calculate_all_cases, run_required_sensitivities,
    run_monte_carlo, generate_csv, appraisal_summary, format_summary_value,
)

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
    initial_sidebar_state="auto",
)


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
    standard = case_labels(n)
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
# SAMPLE DATA LOADER
# ─────────────────────────────────────────────────────────────────────────────

def _clear_safety_inputs() -> None:
    """Drop the per-case safety rate inputs so they redraw from safety_vkt_data."""
    for k in [k for k in st.session_state.keys() if str(k).startswith("sv_")]:
        del st.session_state[k]


def _apply_asset_life(i: int) -> None:
    """Selectbox callback: set option ``i``'s asset life from EPV Table 12.1."""
    label = st.session_state.get(f"cost_asset_type_{i}")
    for name, low, high in ASSET_LIVES:
        if name == label:
            st.session_state.cost_data[f"project_{i}"]["construction_asset_life"] = round((low + high) / 2)
            # The life input redraws from the new value
            st.session_state.pop(f"cost_asset_life_{i}", None)


def _index_pending_costs() -> None:
    """Button callback: index a June 2024 project's costs to June 2026 (CPI Sydney)."""
    index_costs(st.session_state.cost_data, st.session_state.base_case_costs,
                CPI_JUNE_2024_TO_2026)
    # Cost inputs redraw from the indexed values
    for k in [k for k in st.session_state.keys()
              if str(k).startswith("cost_") and k != "cost_data"]:
        del st.session_state[k]
    st.session_state.pop("_price_year_pending", None)


def _request_sample() -> None:
    """Button callback: load the sample at the top of the next run, before any widget renders."""
    st.session_state["_sample_requested"] = True


def _load_sample_data() -> None:
    """Pre-populate session state with a generic road upgrade.

    Car-dominant traffic with moderate HCV freight. Base case = the existing road;
    Option 1 = an upgraded road that is shorter and faster with fewer stops. It
    uses whatever context (urban or rural) is set in Setup.
    All values are illustrative only (not based on any real project).
    """
    years = [2026, 2031, 2041, 2056]
    st.session_state["modelling_years"] = years
    st.session_state["n_project_cases"] = 1
    # The sample sets the project name and the periods its cost rows assume.
    # Setting these widget keys is legal: it runs (via _sample_requested) at the
    # top of the script, before any widget renders.
    st.session_state["const_years"] = 3
    st.session_state["eval_period"] = 30
    st.session_state["construction_start_year"] = 2026
    st.session_state["project_name"] = "Sample Road Upgrade"
    # Re-arm the overwrite confirmation. The rerun below starts before the
    # checkbox renders, so its old value would otherwise be dropped while the
    # browser still shows it ticked (leaving the button disabled).
    st.session_state["confirm_load_sample"] = False

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

    # ── Option 1 (upgrade: shorter route, fewer stops, faster) ──────────
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

    # ── Costs (Project 1): 3 construction years + 30-year appraisal period ──
    # Real $M by year. Timeline index 0-2 = construction, 3-32 = operation.
    _n_years = 3 + 30
    _recurrent = [1.2] * 3 + [2.2] * 30      # existing road kept during construction
    for _t in (12, 22, 32):                   # operating years 10, 20, 30: resurfacing
        _recurrent[_t] = 2.2 + 6.0
    _base_recurrent = [1.2] * _n_years
    for _t in (8, 18, 28):                    # base case periodic resurfacing
        _base_recurrent[_t] = 1.2 + 5.0
    _p1_costs = make_cost_data(1, 3, 30)["project_1"]
    _p1_costs.update({
        "capex_base": {
            "planning": [10.0, 3.0, 2.0],
            "land": [25.0, 5.0, 0.0],
            "construction": [60.0, 120.0, 80.0],
        },
        "contingency_p50": [8.0, 20.0, 17.0],
        "contingency_p90": [14.0, 35.0, 29.0],
        "recurrent": _recurrent,
        "upfront_carbon_t": 45000.0,
        "outturn_p50_nominal": 395.0,
        "outturn_p90_nominal": 432.0,
        "residual": 0.0,                  # 0 = use auto-calculated residual
        "construction_disbenefit_annual": 0.0,
        "construction_asset_life": 40,
        "walk_pkm_day": 800.0, "cycle_pkm_day": 400.0,
        "generated_demand_pct_global": 0.0,
    })
    st.session_state["cost_data"] = {"project_1": _p1_costs}
    st.session_state["base_case_costs"] = {"recurrent": _base_recurrent}

    # ── Safety rates: EPV default for the context, single carriageway ──────
    _case_keys = ["base_case", "project_1"]
    _road = f"{st.session_state.get('context', 'urban')}_single"
    for ck in _case_keys:
        st.session_state[f"sv_road_{ck}"] = _road
    st.session_state["safety_vkt_data"] = {ck: _epv_safety_rates(_road) for ck in _case_keys}
    _clear_safety_inputs()
    st.session_state.pop("_price_year_pending", None)

    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# SAVE / LOAD PROJECT
# ─────────────────────────────────────────────────────────────────────────────

# Default crash cost rates ($/VKT) before EPV 2026.1, only to migrate old files
OLD_SAFETY_DEFAULTS = {"Car": 0.153, "LCV": 0.098, "HCV": 0.198, "Bus": 0.167}
# Parameter override keys from before EPV 2026.1 that no longer map to a parameter
_OBSOLETE_PARAM_PREFIXES = ("param_vtts_", "param_occupancy_", "param_air_", "param_noise_",
                            "param_safety_vkt_")


def _is_obsolete_param_key(key: str) -> bool:
    return (key.startswith(_OBSOLETE_PARAM_PREFIXES)
            or (key.startswith("param_emission_") and key != "param_emission_change_pct"))


SAFETY_ROADS = {
    "urban_divided": "Urban, divided", "urban_single": "Urban, single carriageway",
    "rural_divided": "Rural, divided", "rural_single": "Rural, single carriageway",
    "custom": "Custom rates",
}


def _epv_safety_rates(road: str) -> dict:
    """EPV default crash cost per vkt for ``road`` (e.g. "urban_single"), every vehicle type."""
    env, carriageway = road.split("_")
    rate = crash_cost_per_vkt(env, carriageway, st.session_state.get("funding", "nsw"),
                              build_effective_params())
    return {vt: rate for vt in VTYPES}


def _serialise_project() -> dict:
    """Serialise all project state to a JSON-compatible dict."""
    keys_to_save = [
        "traffic_data", "cost_data", "base_case_costs", "safety_vkt_data", "crash_data",
        "annualisation", "modelling_years", "n_project_cases",
        "env_mode", "reliability_mode", "show_advanced",
        "project_name", "const_years", "eval_period", "construction_start_year",
        "discount_rate", "discount_base_year", "context", "zero_growth_after_last_year",
        "include_reliability", "include_road_damage", "funding", "voc_road_type",
        "include_stop_voc",
    ]
    data = {"version": __version__, "type": "cba_project",
            "cost_format": COST_FORMAT_VERSION, "price_year": PRICE_YEAR}
    for k in keys_to_save:
        if k in st.session_state:
            data[k] = st.session_state[k]
    for k in list(st.session_state.keys()):
        if _is_param_value_key(k) or str(k).startswith("sv_road_"):
            data[k] = st.session_state[k]
    return data


def _deserialise_project(data: dict) -> bool:
    """Restore project state from a JSON dict. Returns False if nothing was loaded."""
    _err = validate_project_file(data)
    if _err:
        st.error(_err)
        return False
    if data.get("version") != __version__:
        st.warning(f"File version {data.get('version')} differs from app version {__version__}. Some data may not load correctly.")
    for k in ("traffic_data", "cost_data", "base_case_costs", "safety_vkt_data", "crash_data",
              "annualisation", "modelling_years", "n_project_cases",
              "env_mode", "reliability_mode", "show_advanced",
              # Period settings fix the meaning of the yearly cost rows. These are
              # widget keys; setting them is legal because the uploader renders
              # before those widgets (the name box is filled after it).
              "const_years", "eval_period", "construction_start_year",
              # Appraisal settings change every result, so they travel with the file.
              "discount_rate", "discount_base_year", "context",
              "zero_growth_after_last_year", "project_name"):
        if k in data:
            st.session_state[k] = data[k]
    _clear_safety_inputs()
    # Settings added later: files without them get the defaults
    for k, default in (("include_reliability", True), ("include_road_damage", True),
                       ("funding", "nsw"), ("voc_road_type", "stop_start"),
                       ("include_stop_voc", False)):
        st.session_state[k] = data.get(k, default)
    # Each case's safety road type. Older files have none: their per-case rates
    # are kept as custom values, except files in the old General mode, which used
    # one set of default rates for every case and now get the EPV default.
    _old_general = data.get("safety_mode") == "General"
    _general_overrides = {vt: data[f"param_safety_vkt_{vt}"] for vt in VTYPES
                          if f"param_safety_vkt_{vt}" in data}
    _cases = list(st.session_state.get("safety_vkt_data") or {"base_case": None})
    for ck in _cases:
        rk = f"sv_road_{ck}"
        if rk in data:
            st.session_state[rk] = data[rk]
        elif _old_general and not _general_overrides:
            st.session_state[rk] = f"{st.session_state.get('context', 'urban')}_single"
        else:
            st.session_state[rk] = "custom"
    if _old_general and _general_overrides:
        _general = {vt: float(_general_overrides.get(vt, OLD_SAFETY_DEFAULTS[vt])) for vt in VTYPES}
        st.session_state["safety_vkt_data"] = {ck: dict(_general) for ck in _cases}
    # Costs saved in another price year are flagged for indexing on the Costs tab
    _file_year = project_price_year(data)
    if _file_year != PRICE_YEAR:
        st.session_state["_price_year_pending"] = _file_year
    else:
        st.session_state.pop("_price_year_pending", None)
    # Saves hold only changed parameters, so clear every override first: the
    # file alone decides which values differ from the TfNSW defaults. Overrides
    # from another price year, or of parameters that no longer exist, are dropped.
    for k in [k for k in st.session_state.keys() if k.startswith("param_")]:
        del st.session_state[k]
    _dropped = []
    for k in list(data.keys()):
        if not _is_param_value_key(k):
            continue
        if _file_year != PRICE_YEAR or _is_obsolete_param_key(k):
            _dropped.append(k)
        else:
            st.session_state[k] = data[k]
    if _dropped:
        st.warning(f"{len(_dropped)} parameter change(s) in this file were for an older set of "
                   "parameter values and have been reset to the TfNSW EPV 2026.1 defaults.")
    _bump_param_tables()
    st.session_state["n_project_cases"] = data.get("n_project_cases", 1)
    st.success("Project loaded successfully!")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────



def format_m(value: float) -> str:
    if abs(value) >= 1000:
        return f"${value / 1000:.1f}B"
    return f"${value:.1f}M"


def fmt_bcr(bcr, dp: int = 2) -> str:
    """BCR to ``dp`` places, or "–" when it is not defined (PV costs zero or negative)."""
    return "–" if bcr is None else f"{bcr:.{dp}f}"


def signed_m(value: float) -> str:
    """Signed label for chart bars, in the same units as format_m: +$22.9M / −$1.2B."""
    return ("−" if value < 0 else "+") + format_m(abs(value))


def case_label(case_key: str) -> str:
    """Display name for a case key: 'base_case' → 'Base Case', 'project_2' → 'Option 2'."""
    return "Base Case" if case_key == "base_case" else f"Option {case_key.split('_')[1]}"


def case_labels(n: int) -> list:
    """Display names for the base case and ``n`` options, in case-key order."""
    return [case_label("base_case")] + [case_label(f"project_{i}") for i in range(1, n + 1)]




# ─────────────────────────────────────────────────────────────────────────────
# MATRIX UI HELPERS — Step 3
# ─────────────────────────────────────────────────────────────────────────────

# Traffic metrics where a fall (project below base) is an improvement
_REDUCTION_IS_GOOD = ("vht", "vkt", "stops")


def _style_change(val):
    """Colour a Project − Base change: reductions green, increases red."""
    if isinstance(val, (int, float)):
        if val < 0:
            return "background-color:rgba(25,135,84,0.12);color:#198754"
        if val > 0:
            return "background-color:rgba(220,53,69,0.12);color:#dc3545"
    return ""


def render_traffic_matrix(metric: str, unit_label: str) -> None:
    """Render st.data_editor tables for one traffic metric across all cases.

    Displays one editable table per case (Base Case + N options), then a
    colour-coded read-only incremental table (Project − Base) beneath.
    Reads and writes ``st.session_state.traffic_data`` in-place.

    Args:
        metric:     One of "vht", "vkt", "stops", "demand".
        unit_label: Human-readable unit string shown in the table header.
    """
    years: list = st.session_state.modelling_years
    n: int = st.session_state.n_project_cases
    case_keys = ["base_case"] + [f"project_{i}" for i in range(1, n + 1)]

    col_cfg = {
        str(y): st.column_config.NumberColumn(str(y), min_value=0.0, format="localized")
        for y in years
    }

    # ── Editable input tables ──────────────────────────────────────────────
    for case_key in case_keys:
        st.markdown(f"**{case_label(case_key)}** &nbsp;·&nbsp; <small>{unit_label}</small>",
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
            "Total · " + " · ".join(f"{y}: {totals[str(y)]:,.0f}" for y in years)
        )

    # ── Incremental tables (Option − Base) ────────────────────────────────
    if n >= 1:
        st.divider()
        st.markdown("**Change from base case (Option − Base)**")
        if metric in _REDUCTION_IS_GOOD:
            st.caption("Green = lower than the base case (an improvement); red = higher.")

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
            incr_df.loc["Total"] = incr_df.sum()

            if n > 1:
                st.caption(f"{case_label(f'project_{i}')} − Base")

            _styled = incr_df.style.format("{:+,.0f}")
            if metric in _REDUCTION_IS_GOOD:
                _styled = _styled.map(_style_change)
            st.dataframe(_styled, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# CRASH MATRIX UI HELPER — Step 4
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# COST ENTRY UI HELPER — Step 5
# ─────────────────────────────────────────────────────────────────────────────

_CAPEX_ROWS = [
    ("Planning & design", "planning"),
    ("Land", "land"),
    ("Construction", "construction"),
    ("Contingency to P50", "contingency_p50"),
    ("Contingency to P90", "contingency_p90"),
]


def _edit_year_rows(rows: dict, years: list, key: str) -> dict:
    """Render one ``st.data_editor`` with a row per entry of ``rows`` over ``years``.

    Returns ``{row_label: [float per year]}``, with blank or pasted non-numbers as 0.0.
    """
    cols = [str(y) for y in years]
    df = pd.DataFrame([list(v) for v in rows.values()], index=list(rows), columns=cols)
    edited = st.data_editor(
        df, num_rows="fixed", key=key, use_container_width=True,
        column_config={c: st.column_config.NumberColumn(c, format="%.2f")
                       for c in cols},
    )
    return {label: clean_row([edited.loc[label, c] for c in cols]) for label in rows}


def render_cost_entry(const_years: int, eval_period: int, start_year: int) -> None:
    """Render yearly cost tables: the shared base case, then each option.

    Capital rows cover the construction years; recurrent rows cover the whole
    timeline (construction + appraisal period), starting at ``start_year``.
    All values are real $M. Updates ``st.session_state`` cost dicts in place.
    """
    n = st.session_state.n_project_cases
    base = st.session_state.base_case_costs
    fit_cost_rows(base, const_years, eval_period)
    for i in range(1, n + 1):
        fit_cost_rows(st.session_state.cost_data[f"project_{i}"], const_years, eval_period)

    build_years = list(range(start_year, start_year + const_years))
    all_years = list(range(start_year, start_year + const_years + eval_period))

    _t_capital, _t_recurrent = st.tabs(["Capital and other", "Recurrent by year"])

    # ── Recurrent costs: one table, a row per year and a column per case ──────
    with _t_recurrent:
        st.caption(
            "Operations, maintenance and periodic renewals by year ($M, real). The base case "
            "column is the existing road if no option goes ahead, shared by all options. Only "
            "each option's difference from it counts: a net increase is a cost, a net saving a "
            "benefit. In construction years, enter each option's cost of maintaining the "
            "existing road. Paste a column from Excel."
        )
        _rec_keys = ["base_case"] + [f"project_{i}" for i in range(1, n + 1)]
        _rec_rows = {k: (base if k == "base_case" else st.session_state.cost_data[k])["recurrent"]
                     for k in _rec_keys}
        _rec_df = pd.DataFrame({case_label(k): _rec_rows[k] for k in _rec_keys},
                               index=pd.Index([str(y) for y in all_years], name="Year"))
        _rec_edit = st.data_editor(
            _rec_df, num_rows="fixed", use_container_width=True,
            # Tall enough to show every year without an inner scrollbar
            height=35 * (len(all_years) + 1) + 3,
            key=f"cost_recurrent_{n}_{start_year}_{len(all_years)}",
            column_config={c: st.column_config.NumberColumn(c, format="%.2f") for c in _rec_df.columns},
        )
        for k in _rec_keys:
            _row = clean_row(_rec_edit[case_label(k)].tolist())
            if k == "base_case":
                base["recurrent"] = _row
            else:
                st.session_state.cost_data[k]["recurrent"] = _row

    for i in range(1, n + 1):
        case_key = f"project_{i}"
        cd = st.session_state.cost_data[case_key]

        with _t_capital, st.expander(f"{case_label(case_key)} — costs", expanded=(i == 1)):
            st.markdown("**Capital costs by construction year ($M, real)**")
            st.caption(
                "Base estimates (no contingency) for planning & design, land and construction, "
                "plus the contingency that takes the base to P50 and to P90. Paste a row from Excel."
            )
            _cap_in = {
                label: (cd["capex_base"][k] if k in CAPEX_CATEGORIES else cd[k])
                for label, k in _CAPEX_ROWS
            }
            _cap_out = _edit_year_rows(_cap_in, build_years, key=f"cost_capex_{i}")
            for label, k in _CAPEX_ROWS:
                if k in CAPEX_CATEGORIES:
                    cd["capex_base"][k] = _cap_out[label]
                else:
                    cd[k] = _cap_out[label]

            _sched_p50 = build_cost_schedule(cd, base, const_years, eval_period)
            _sched_p90 = build_cost_schedule(cd, base, const_years, eval_period, capital="p90")
            _t1, _t2 = st.columns(2)
            _t1.metric("P50 capital ($M, real)", format_m(_sched_p50["capital_total"]),
                       help="Base estimate rows + contingency to P50. Used in the core result.")
            _t2.metric("P90 capital ($M, real)", format_m(_sched_p90["capital_total"]),
                       help="Base estimate rows + contingency to P90. Used as a sensitivity test.")

            st.markdown("**Upfront carbon and outturn capital**")
            _u1, _u2, _u3 = st.columns(3)
            with _u1:
                cd["upfront_carbon_t"] = st.number_input(
                    "Upfront carbon (tCO₂e)", min_value=0.0,
                    value=float(cd.get("upfront_carbon_t", 0.0) or 0.0), step=100.0,
                    key=f"cost_upfront_carbon_{i}",
                    help=(
                        "Embodied carbon from construction. Spread over the construction years "
                        "in proportion to P50 capital and valued at the NSW Carbon Value for "
                        "each year (TPG24-34). Reported as a disbenefit."
                    ),
                )
            with _u2:
                cd["outturn_p50_nominal"] = st.number_input(
                    "P50 outturn capital (nominal $M)", min_value=0.0,
                    value=cd.get("outturn_p50_nominal"), step=1.0,
                    key=f"cost_outturn_p50_{i}",
                    help="Copied from the cost estimate. Reporting only; never used in the calculation.",
                )
            with _u3:
                cd["outturn_p90_nominal"] = st.number_input(
                    "P90 outturn capital (nominal $M)", min_value=0.0,
                    value=cd.get("outturn_p90_nominal"), step=1.0,
                    key=f"cost_outturn_p90_{i}",
                    help="Copied from the cost estimate. Reporting only; never used in the calculation.",
                )
            _nominal_p50 = cd.get("outturn_p50_nominal")
            if _nominal_p50 and _sched_p50["capital_total"] >= 0.98 * _nominal_p50:
                st.warning(
                    f"Real P50 capital ({format_m(_sched_p50['capital_total'])}) is close to or "
                    f"above the nominal outturn ({format_m(_nominal_p50)}). The yearly rows must "
                    f"be real {PRICE_LABEL} dollars; an escalated (outturn) estimate overstates costs."
                )

            # ── Residual value ───────────────────────────────────────────────
            st.markdown("**Residual value**")
            _a0, _a1, _a2 = st.columns(3)
            with _a0:
                st.selectbox(
                    "Asset type (EPV Table 12.1)", ["—"] + [a[0] for a in ASSET_LIVES],
                    key=f"cost_asset_type_{i}", on_change=_apply_asset_life, args=(i,),
                    help="Fills the asset life with the EPV economic life (the midpoint where "
                         "the EPV gives a range). Edit the life if the project differs.",
                )
            with _a1:
                cd["construction_asset_life"] = st.number_input(
                    "Construction asset life (years)",
                    min_value=1, max_value=200,
                    value=int(cd.get("construction_asset_life", 40)),
                    step=5, key=f"cost_asset_life_{i}",
                    help=(
                        "Useful life of the constructed asset — used to auto-calculate residual "
                        "value at end of evaluation period (straight-line depreciation). "
                        "Typical values: sealed rural road 40–60 yr · urban arterial 30–50 yr · "
                        "bridge/major structure 80–100 yr · flexible road surface 25–35 yr · "
                        "unsealed road 15–20 yr · ITS/signals 15–25 yr. "
                        "Land acquisition always retains full value regardless of this setting."
                    ),
                )
            with _a2:
                cd["residual"] = st.number_input(
                    "Manual residual override ($M)",
                    min_value=0.0,
                    value=float(cd["residual"]), step=0.1, key=f"cost_residual_{i}",
                    help=(
                        "Leave at $0 to use the auto-calculated residual shown below. "
                        "Enter a value > $0 to override the auto-calculation entirely. "
                        "Source: TfNSW CBA Guidelines — residual value = "
                        "(remaining asset life / total asset life) × capital cost."
                    ),
                )

            _life = int(cd.get("construction_asset_life", 40))
            _rem_frac = max(0.0, (_life - eval_period) / _life) if _life > 0 else 0.0
            _by_cat = _sched_p50["capital_by_category"]
            _land_res = _by_cat["land"]
            _const_res = _by_cat["construction"] * _rem_frac
            _auto_res = _land_res + _const_res
            _override = cd.get("residual", 0.0) > 0.0
            _rc1, _rc2, _rc3 = st.columns(3)
            _rc1.metric(
                "Land residual ($M)", f"${_land_res:.2f}M",
                help="Land (with its pro-rata share of P50 contingency) retains full value.",
            )
            _rc2.metric(
                "Construction residual ($M)", f"${_const_res:.2f}M",
                help=(
                    f"{_rem_frac*100:.0f}% of P50 construction cost (incl. its pro-rata share of "
                    f"contingency) remaining after the {eval_period}-yr appraisal period "
                    f"(asset life {_life} yr). "
                    "Formula: cost × max(0, (asset_life − appraisal_period) / asset_life)."
                ),
            )
            _rc3.metric(
                "Auto residual ($M)" + (" — overridden" if _override else ""),
                f"${_auto_res:.2f}M",
                help=(
                    "Sum of land + construction residuals. "
                    "Planning/design has no residual value (professional services). "
                    "Overridden if the manual residual override is > $0."
                ),
            )

            st.markdown("**Construction disruption**")
            _d1, _ = st.columns(2)
            with _d1:
                cd["construction_disbenefit_annual"] = st.number_input(
                    "Traffic disruption during construction ($M/yr)",
                    min_value=0.0,
                    value=float(cd.get("construction_disbenefit_annual", 0.0)),
                    step=0.1,
                    key=f"cost_const_disb_{i}",
                    help=(
                        "Annual road-user delay cost during construction (e.g. detour travel time, "
                        "VOC on diversion routes). Applied each year of the construction period and "
                        "reported as a disbenefit (Construction disruption). Source: TfNSW CBA "
                        "Guidelines — model delays using affected AADT × detour delay × VTTS, or use "
                        "a lump-sum estimate."
                    ),
                )

            st.session_state.cost_data[case_key] = cd


def render_benefit_assumptions() -> None:
    """Render each option's generated-demand (rule-of-half) and active-transport inputs.

    These live in ``cost_data`` (they travel with each option) but are benefit
    assumptions, so they are shown on the Traffic sub-tab.
    """
    n = st.session_state.n_project_cases
    for i in range(1, n + 1):
        case_key = f"project_{i}"
        cd = st.session_state.cost_data[case_key]

        with st.expander(f"{case_label(case_key)} — benefit assumptions", expanded=(i == 1)):
            st.markdown("**Generated demand (rule-of-half)**")
            st.caption(
                "Share of the option's traffic that is new (generated) rather than redistributed. "
                "The generated share of travel time, reliability and VOC benefits counts at half "
                "value; safety and environment count in full. Default 0%. This approximates the "
                "rule-of-half on network totals; with a variable-demand model the VHT change "
                "already includes new trips, so leave it at 0% unless the model is fixed-demand."
            )
            cd["generated_demand_pct_global"] = st.slider(
                "Generated demand, all vehicle types (%)",
                min_value=0, max_value=100, step=5,
                value=int(cd.get("generated_demand_pct_global", 0)),
                key=f"gend_demand_global_{i}",
                help=(
                    "Apply this % globally to all vehicle types unless overridden below. "
                    "Rule-of-Half: new (generated) trips receive half the per-trip user benefit "
                    "of existing trips. Source: ATAP T2; TfNSW CBA Guidelines."
                ),
            )

            with st.expander("Per-vehicle-type overrides", expanded=False):
                st.caption("Enable and set custom % for individual vehicle types (overrides global setting)")
                for vtype in VTYPES:
                    c_check, c_slider = st.columns([1, 3])
                    with c_check:
                        override_enabled = st.checkbox(
                            f"{vtype} override",
                            value=(cd["generated_demand_pct_override"].get(vtype) is not None),
                            key=f"gend_demand_override_check_{i}_{vtype}",
                        )
                    with c_slider:
                        if override_enabled:
                            override_val = cd["generated_demand_pct_override"].get(vtype, 0)
                            cd["generated_demand_pct_override"][vtype] = st.slider(
                                f"{vtype} generated demand (%)",
                                min_value=0, max_value=100, step=5,
                                value=int(override_val if override_val is not None else 0),
                                key=f"gend_demand_override_val_{i}_{vtype}",
                                label_visibility="collapsed",
                            )
                        else:
                            cd["generated_demand_pct_override"][vtype] = None
                            st.caption(f"Using global setting ({cd['generated_demand_pct_global']}%)")

            st.markdown("**Active transport (health benefits)**")
            at1, at2 = st.columns(2)
            with at1:
                cd["walk_pkm_day"] = st.number_input(
                    "Additional walking (person-km/day)", min_value=0.0,
                    value=float(cd.get("walk_pkm_day", 0.0)), step=1.0,
                    key=f"cost_walk_{i}",
                    help=(
                        "New walking person-km/day generated by this option vs. base case "
                        "(e.g. new footpaths, bridge crossings). "
                        f"Benefit = person-km/day × ${PARAMS['health_benefits']['walking']:.2f}/km × 365. "
                        "Source: TfNSW EPV 2026.1, Table 7.1."
                    ),
                )
            with at2:
                cd["cycle_pkm_day"] = st.number_input(
                    "Additional cycling (person-km/day)", min_value=0.0,
                    value=float(cd.get("cycle_pkm_day", 0.0)), step=1.0,
                    key=f"cost_cycle_{i}",
                    help=(
                        "New cycling person-km/day generated by this option vs. base case "
                        "(e.g. new shared paths, separated lanes). "
                        f"Benefit = person-km/day × ${PARAMS['health_benefits']['cycling']:.2f}/km × 365. "
                        "Source: TfNSW EPV 2026.1, Table 7.1."
                    ),
                )
            _car_sav = {m: sum(PARAMS["active_car_savings"][m].values()) for m in ("walking", "cycling")}
            cd["active_car_share_pct"] = st.number_input(
                "Share of these km that replace car trips (%)", min_value=0.0, max_value=100.0,
                value=float(cd.get("active_car_share_pct", 0.0) or 0.0), step=5.0,
                key=f"cost_active_car_share_{i}",
                help=(
                    "Former car trips also save decongestion, VOC, crash, externality, road "
                    f"provision and parking costs: walking ${_car_sav['walking']:.2f}/km, cycling "
                    f"${_car_sav['cycling']:.2f}/km (EPV 2026.1 Table 7.1). Leave at 0% if the "
                    "traffic model already removes those car trips, or they are counted twice."
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

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # One sheet per traffic metric
        for metric in ["VHT", "VKT", "Stops", "Demand"]:
            rows = []
            for case_key in case_keys:
                for vt in VTYPES:
                    row = {"Case": case_label(case_key), "Vehicle Type": vt}
                    for y in years:
                        row[str(y)] = 0.0
                    rows.append(row)
            pd.DataFrame(rows).to_excel(writer, sheet_name=metric, index=False)

    return buf.getvalue()


def _apply_template_df(df: pd.DataFrame, metric: str, years: list, n: int) -> None:
    """Write a parsed template DataFrame into ``st.session_state.traffic_data``."""
    case_labels_map = {
        "Base Case": "base_case",
        **{f"Option {i}": f"project_{i}" for i in range(1, n + 1)},
        # Templates downloaded before options were renamed
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
            **{f"{word}{sep}{i}": f"Option {i}"
               for word in ("option", "project") for sep in (" ", "_", "")
               for i in range(1, n + 1)},
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
                             ("case", "scenario", "option", "project")), None)
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
    std_cases = case_labels(n)

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
    case_col = next((c for c in df.columns if c.lower() in ("case", "scenario", "option", "project")), None)
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
                                base_case_costs: dict,
                                annualisation: dict, safety_vkt_data: dict,
                                params: dict) -> dict:
    return calculate_all_cases(
        inputs=inputs,
        traffic_data=traffic_data,
        cost_data=cost_data,
        base_case_costs=base_case_costs,
        annualisation=annualisation,
        safety_vkt_data=safety_vkt_data,
        params=params,
    )


@st.cache_data(show_spinner=False)
def _cached_required_sensitivities(_cache_key: str, inputs: dict,
                                   base_traffic: dict, proj_traffic: dict,
                                   cost: dict, base_costs: dict,
                                   annualisation: dict,
                                   safety_vkt_base: dict, safety_vkt_proj: dict,
                                   params: dict) -> list:
    return run_required_sensitivities(
        inputs, base_traffic, proj_traffic, cost, base_costs, annualisation,
        safety_vkt_base=safety_vkt_base, safety_vkt_proj=safety_vkt_proj,
        params=params,
    )


def _required_rows_for(case_key: str) -> list:
    """Required TfNSW sensitivity rows for one option, cached.

    Single place that builds the cache key and calls the cache, so the
    Sensitivity tab and the CSV download always share the same cached run.
    Reads the current calculation globals (_matrix_inputs, _calc_safety_vkt,
    _eff_params), which are set before any tab renders.
    """
    safety = _calc_safety_vkt or {}
    base_safety = safety.get("base_case")
    proj_safety = safety.get(case_key)
    ss = st.session_state
    key = _stable_hash(_matrix_inputs, case_key,
                       ss.traffic_data["base_case"], ss.traffic_data[case_key],
                       ss.cost_data[case_key], ss.base_case_costs, ss.annualisation,
                       base_safety, proj_safety, _eff_params)
    try:
        return _cached_required_sensitivities(
            key, _matrix_inputs,
            base_traffic=ss.traffic_data["base_case"],
            proj_traffic=ss.traffic_data[case_key],
            cost=ss.cost_data[case_key],
            base_costs=ss.base_case_costs,
            annualisation=ss.annualisation,
            safety_vkt_base=base_safety,
            safety_vkt_proj=proj_safety,
            params=_eff_params,
        )
    except Exception as err:
        st.error(f"Sensitivity calculation error: {err}")
        return []








# ─────────────────────────────────────────────────────────────────────────────
# PARAMETER EDITOR HELPERS — Phase 0e
# ─────────────────────────────────────────────────────────────────────────────

def _is_param_value_key(key: str) -> bool:
    """True for a parameter override key (``param_*``), not an old widget key."""
    return key.startswith("param_") and not key.endswith(("_num", "_sl"))


def _bump_param_tables() -> None:
    """Give every parameter table a fresh widget so it redraws from session values."""
    st.session_state["_ptbl_ver"] = st.session_state.get("_ptbl_ver", 0) + 1


def _param_table_changed(editor_key: str, rows: list, cells: dict) -> None:
    """on_change callback: copy edited cells to their ``param_*`` keys.

    Runs before the script, so the calculation (which renders before the
    Parameters tab) uses the new values on the same run. A cleared cell
    returns that parameter to its default.
    """
    for r, changes in st.session_state[editor_key]["edited_rows"].items():
        for col, val in changes.items():
            param_key = cells.get((rows[int(r)], col), (None,))[0]
            if param_key is None:
                continue
            if val is None:
                st.session_state.pop(param_key, None)
            else:
                st.session_state[param_key] = float(val)
    _bump_param_tables()


def param_table(name: str, cells: dict, unit: str, source: str,
                fmt: str = "%.2f", min_val: float = 0.0, max_val: float = None) -> None:
    """Render one editable table of economic parameters.

    ``cells`` maps ``(row_label, column_label)`` → ``(param_key, default)``.
    Values come from ``st.session_state[param_key]`` when overridden, else the
    default. Changed values are listed under the table.
    """
    rows = list(dict.fromkeys(r for r, _ in cells))
    cols = list(dict.fromkeys(c for _, c in cells))
    df = pd.DataFrame(
        [[float(st.session_state.get(cells[(r, c)][0], cells[(r, c)][1]))
          if (r, c) in cells else None for c in cols] for r in rows],
        index=rows, columns=cols,
    )
    editor_key = f"ptbl_{name}_{st.session_state.get('_ptbl_ver', 0)}"
    st.data_editor(
        df, key=editor_key, num_rows="fixed", use_container_width=True,
        column_config={c: st.column_config.NumberColumn(
            c, format=fmt, min_value=min_val, max_value=max_val, help=unit) for c in cols},
        on_change=_param_table_changed, args=(editor_key, rows, cells),
    )
    _changed = [
        f"{r} {c}: {d:g} → {float(st.session_state[k]):g}"
        for (r, c), (k, d) in cells.items()
        if k in st.session_state and float(st.session_state[k]) != float(d)
    ]
    st.caption(f"{unit} · {source}"
               + (" · **Changed from default:** " + "; ".join(_changed) if _changed else ""))


def build_effective_params() -> dict:
    """Return a deep copy of PARAMS with any session_state overrides applied.

    The Parameters tab writes overrides to session_state under ``param_*`` keys.
    This function merges those back into the canonical PARAMS structure so that
    ``calculate_matrix()`` uses user-edited values without mutating the global.
    """
    p = copy.deepcopy(PARAMS)
    ss = st.session_state

    def _set(key: str, target: dict, field, scale: float = 1.0) -> None:
        if key in ss:
            target[field] = float(ss[key]) * scale

    for _ctx in ("urban", "rural"):
        for _vt in VTYPES:
            _set(f"param_vtt_{_ctx}_{_vt}", p["vtt_vehicle_hr"][_ctx], _vt)
            _set(f"param_ext_{_ctx}_{_vt}", p["externality_cents_vkt"][_ctx], _vt)
        for _cw in ("divided", "single"):
            _set(f"param_crash_rate_{_ctx}_{_cw}", p["crash_rate_per_100mvkt"][_ctx], _cw)
        for _fund in ("nsw", "joint"):
            _set(f"param_crash_cost_{_fund}_{_ctx}", p["cost_per_crash"][_fund], _ctx)
    for _vt in VTYPES:
        # Entered in kg CO2-e per vkt, held in tonnes
        _set(f"param_carbon_kg_{_vt}", p["carbon_t_per_vkt"], _vt, scale=1e-3)
        _set(f"param_road_damage_{_vt}", p["road_damage_cents_vkt"], _vt)
        _set(f"param_voc_stop_{_vt}", p["voc_per_stop"], _vt)
    # Scalar parameters: session key → PARAMS key
    for _k, _pk in (("param_reliability_ratio", "reliability_ratio"),
                    ("param_reliability_ratio_freight", "reliability_ratio_freight"),
                    ("param_reliability_share", "reliability_share_of_tts"),
                    ("param_emission_change_pct", "emission_factor_change_pct"),
                    ("param_road_damage_share", "road_damage_maintenance_share")):
        _set(_k, p, _pk)
    for _mode in ("walking", "cycling"):
        _set(f"param_health_{_mode}", p["health_benefits"], _mode)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def render_rule_of_half_assumptions(cost_case: dict) -> None:
    """Display Rule-of-Half assumptions from cost data for an option.

    Extracts and displays the generated demand percentage(s) and any per-vehicle-type
    overrides to show users what appraisal methodology was applied.
    """
    gen_pct_global = cost_case.get("generated_demand_pct_global", 0.0)
    gen_pct_override = cost_case.get("generated_demand_pct_override", {})

    # Check if any settings are non-zero
    has_overrides = any(v is not None for v in gen_pct_override.values())
    has_global = gen_pct_global > 0

    if has_global or has_overrides:
        # Build info message with overrides if present
        if has_overrides:
            override_parts = []
            for vt in VTYPES:
                if gen_pct_override.get(vt) is not None:
                    override_parts.append(f"{vt}: {gen_pct_override[vt]}%")
            overrides_str = ", ".join(override_parts)
            msg = f"**Rule-of-half (generated demand):** {gen_pct_global}% all vehicle types (overrides: {overrides_str})"
        else:
            msg = f"**Rule-of-half (generated demand):** {gen_pct_global}% all vehicle types"
        msg += " — applied to travel time, reliability and VOC; safety and environment counted in full"
        st.caption(msg)
    else:
        # No Rule-of-Half applied
        st.caption("**Rule-of-half:** not applied (0% generated demand — all traffic is redistributed)")


ANNUALISATION_DEFAULT = {"factor": 6.29, "days": 336}


def _annualisation_is_default() -> bool:
    """True while every vehicle type still has the generic annualisation default."""
    ann = st.session_state.get("annualisation", {})
    return all(
        float(ann.get(vt, {}).get("factor", 0)) == ANNUALISATION_DEFAULT["factor"]
        and int(ann.get(vt, {}).get("days", 0)) == ANNUALISATION_DEFAULT["days"]
        for vt in VTYPES
    )


def _bcr_metric(container, label: str, bcr, above: str, below: str) -> None:
    """NPV-style card for a BCR; "–" with a note when the BCR is not defined."""
    if bcr is None:
        container.metric(label, fmt_bcr(bcr), delta="Not defined", delta_color="off",
                         help="PV costs are zero or negative, so the BCR is not defined. Use NPV.")
        return
    container.metric(label, fmt_bcr(bcr), delta=above if bcr >= 1 else below,
                     delta_color="normal" if bcr >= 1 else "inverse")


def _result_checks(results: dict) -> list:
    """Plain-language checks on inputs and results that a reviewer would raise."""
    checks = []
    if _annualisation_is_default():
        checks.append("Annualisation is still the generic default (6.29 × 336 days); use "
                      "factors from your traffic model or counts (Inputs → Setup).")
    ss = st.session_state
    if ss.get("_price_year_pending"):
        checks.append(f"Costs were saved in June {ss['_price_year_pending']} dollars; index them "
                      f"to {PRICE_LABEL} or confirm they already are (Inputs → Costs).")
    if any(ss.get(f"sv_road_{k}") == "custom" for k in ss.get("safety_vkt_data", {})):
        checks.append("Some cases use custom crash cost rates; keep the evidence for them "
                      "(Inputs → Traffic → Safety rates).")
    if ss["discount_base_year"] > ss["construction_start_year"]:
        checks.append("The discount base year is after construction starts, so earlier costs "
                      "are grown forward rather than treated as sunk.")
    for key, r in results.items():
        name = case_label(key)
        for vt, (lo, hi) in r.get("voc_speed_out_of_range", {}).items():
            checks.append(f"{name}: {vt} average speed {lo:.0f}–{hi:.0f} km/h is outside the "
                          "VOC table, so VOC uses the table's end value.")
        nominal = ss.cost_data.get(key, {}).get("outturn_p50_nominal")
        real = r.get("capital_p50_total", 0.0)
        if nominal and real >= 0.98 * nominal:
            checks.append(f"{name}: real P50 capital ({format_m(real)}) is close to or above the "
                          f"nominal outturn ({format_m(nominal)}). Check the cost rows are real "
                          f"{PRICE_LABEL} dollars, not escalated.")
    return checks


def _has_inputs() -> bool:
    """True once any traffic or cost figure has been entered (is non-zero)."""
    for _case in st.session_state.traffic_data.values():
        for _vt in VTYPES:
            if any(any(v for v in _vals) for _vals in _case.get(_vt, {}).values()):
                return True
    for _cost in st.session_state.cost_data.values():
        _rows = list(_cost.get("capex_base", {}).values()) + [
            _cost.get("contingency_p50", []), _cost.get("recurrent", [])]
        if any(any(v for v in _row) for _row in _rows):
            return True
    return any(st.session_state.base_case_costs.get("recurrent", []))


# ─────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────────────────────
COLORS = {
    "tts": "#0d6efd",
    "reliability": "#6610f2",
    "voc": "#fd7e14",
    "safety": "#dc3545",
    "env": "#198754",
    "active": "#6f42c1",
    "recurrent_savings": "#20c997",
    "upfront_carbon": "#6c757d",
    "construction_disruption": "#adb5bd",
    "residual": "#795548",
    "cost": "#6c757d",
    "positive": "#198754",
    "negative": "#dc3545",
    "neutral": "#0d6efd",
}



# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS — theme-aware (works in both light and dark mode)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Headline result cards (NPV, BCR) */
    div[data-testid="stMetric"] {
        background: rgba(128, 128, 128, 0.06);
        border: 1px solid rgba(128, 128, 128, 0.18);
        border-radius: 0.75rem;
        padding: 1rem 1.25rem;
    }
    div[data-testid="stMetric"] label {
        font-size: 0.8rem !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.7;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.9rem !important;
        font-weight: 700;
    }
    /* Slim page title */
    .app-title { margin: 0 0 0.75rem 0; }
    .app-title h1 { margin: 0; padding: 0; font-size: 1.7rem; font-weight: 700; }
    .app-title p { margin: 0.15rem 0 0 0; opacity: 0.6; font-size: 0.9rem; }
    /* Main tabs: large pills, active one filled with the accent colour */
    div[data-baseweb="tab-list"] {
        gap: 0.5rem;
        flex-wrap: wrap;
        padding-bottom: 0.25rem;
    }
    div[data-baseweb="tab-list"] button[data-baseweb="tab"] {
        border-radius: 999px;
        padding: 0.55rem 1.15rem;
        border: 1px solid rgba(128, 128, 128, 0.25);
        background: transparent;
        height: auto;
    }
    div[data-baseweb="tab-list"] button[data-baseweb="tab"] p {
        font-size: 1.02rem;
        font-weight: 600;
    }
    div[data-baseweb="tab-list"] button[data-baseweb="tab"]:hover {
        border-color: #0066CC;
    }
    div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {
        background: #0066CC;
        border-color: #0066CC;
        color: #ffffff;
    }
    div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] p {
        color: #ffffff;
    }
    div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] { display: none; }
    /* Sub-tabs inside a tab (Inputs: Setup / Traffic / Costs) stay plain and smaller */
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] { gap: 1.25rem; }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"] {
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        padding: 0.3rem 0.1rem;
    }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"] p {
        font-size: 0.95rem;
    }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {
        background: transparent;
        border-bottom-color: #0066CC;
        color: #0066CC;
    }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] p {
        color: #0066CC;
    }
    /* Third level (Traffic metrics, Costs sections): small segmented buttons */
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] {
        gap: 0.35rem;
    }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"] {
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 0.5rem;
        padding: 0.2rem 0.75rem;
    }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"] p {
        font-size: 0.85rem;
        font-weight: 500;
    }
    div[data-baseweb="tab-panel"] div[data-baseweb="tab-panel"] div[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {
        background: rgba(0, 102, 204, 0.1);
        border-color: #0066CC;
    }
    /* Section headings: plain bold text with a thin rule */
    .section-header {
        border-bottom: 1px solid rgba(128, 128, 128, 0.2);
        padding: 0 0 0.35rem 0;
        margin: 1.5rem 0 0.75rem 0;
        font-size: 1.1rem;
        font-weight: 600;
    }
    /* Empty state on the results tabs */
    .empty-state { text-align: center; padding: 2.5rem 1rem 1rem 1rem; }
    .empty-state h3 { margin-bottom: 0.25rem; }
    .empty-state p { opacity: 0.65; }
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
    if "annualisation" not in st.session_state:
        st.session_state["annualisation"] = {vt: dict(ANNUALISATION_DEFAULT) for vt in ("Car", "LCV", "HCV", "Bus")}
    else:
        # Migrate older flat structures
        _ann = st.session_state["annualisation"]
        _old_factor = _ann.pop("annualisation_factor", None)
        _old_days = _ann.pop("days_per_year", 336)
        for _vt in ("Car", "LCV", "HCV", "Bus"):
            if not isinstance(_ann.get(_vt), dict):
                _f = float(_ann[_vt]) if _vt in _ann else (_old_factor or 6.29)
                _ann[_vt] = {"factor": _f, "days": int(_old_days)}
    # Period and appraisal settings are Setup-tab widget keys (project name is in
    # the sidebar). Store them as plain session values every run so an st.rerun()
    # fired before every widget renders does not clear them back to defaults.
    for _k, _default in (("eval_period", 30), ("const_years", 3),
                         ("construction_start_year", 2026),
                         ("discount_rate", 5.0), ("discount_base_year", 2026),
                         ("context", "urban"), ("zero_growth_after_last_year", True),
                         ("include_reliability", True), ("include_road_damage", True),
                         ("funding", "nsw"), ("voc_road_type", "stop_start"),
                         ("include_stop_voc", False),
                         ("project_name", "Untitled project")):
        st.session_state[_k] = st.session_state.get(_k, _default)
    _years = st.session_state["modelling_years"]
    _n = st.session_state["n_project_cases"]
    _project_keys = [f"project_{i}" for i in range(1, _n + 1)]
    _case_keys = ["base_case"] + _project_keys
    # Safety $/VKT per case: each case's road type (widget key, written back every
    # run) defaults to the context's single carriageway; missing cases get its rate
    _svd = st.session_state.setdefault("safety_vkt_data", {})
    for ck in _case_keys:
        _rk = f"sv_road_{ck}"
        st.session_state[_rk] = st.session_state.get(
            _rk, f"{st.session_state['context']}_single")
        if ck not in _svd:
            _svd[ck] = _epv_safety_rates(st.session_state[_rk])
    # Traffic rows are indexed by modelling year: reset them when the years
    # change; otherwise only add zeroed entries for new options.
    td = st.session_state.get("traffic_data")
    if td is None or td.get("base_case", {}).get("years") != _years:
        st.session_state["traffic_data"] = make_traffic_data(_years, _n)
    else:
        for _ck in _project_keys:
            if _ck not in td:
                td[_ck] = make_traffic_case(_years)
    # Cost rows are indexed by construction/appraisal year, not modelling year:
    # keep every existing option's costs and add entries only for new options.
    _cost_data = st.session_state.get("cost_data") or {}
    _missing = [_ck for _ck in _project_keys if _ck not in _cost_data]
    if _missing:
        _fresh = make_cost_data(_n, st.session_state["const_years"],
                                st.session_state["eval_period"])
        for _ck in _missing:
            _cost_data[_ck] = _fresh[_ck]
    st.session_state["cost_data"] = _cost_data
    # Base case costs are shared by all options and survive option-count changes
    if "base_case_costs" not in st.session_state:
        st.session_state["base_case_costs"] = make_base_case_costs(
            st.session_state["const_years"], st.session_state["eval_period"],
        )

    st.session_state.setdefault("show_advanced", False)
    st.session_state.setdefault("env_mode", "General")
    st.session_state.setdefault("reliability_mode", "General")
    st.session_state.setdefault("mc_results", None)


_init_session_state()


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — project name, project file and sample data
# ─────────────────────────────────────────────────────────────────────────────
# The Results empty-state button asks for the sample here, before any period
# widget renders, so _load_sample_data may set their keys.
if st.session_state.pop("_sample_requested", False):
    _load_sample_data()

with st.sidebar:
    st.markdown("## Transport CBA")
    st.caption(f"v{__version__} · TfNSW EPV 2026.1 · {PRICE_LABEL} prices")

    # Shown first, filled after the project uploader so a loaded file can set it.
    _name_slot = st.container()

    st.markdown("**Project file**")
    # Filled after the Inputs tab, so the file includes edits made this run.
    _save_slot = st.container()
    _uploaded_project = st.file_uploader(
        "Open a saved project (.json)", type=["json"], key="load_project_uploader",
    )
    # The uploader keeps returning the file on every run; apply each upload
    # once so later edits are not overwritten and st.rerun() does not loop.
    if (_uploaded_project is not None
            and st.session_state.get("_loaded_project_id") != _uploaded_project.file_id):
        try:
            _loaded = json.loads(_uploaded_project.read().decode("utf-8"))
            if _deserialise_project(_loaded):
                st.session_state["_loaded_project_id"] = _uploaded_project.file_id
                st.rerun()
        except Exception as e:
            st.error(f"Error loading project: {e}")

    with _name_slot:
        # Value comes from session state (no value=; set in _init_session_state)
        # so a loaded project can set it without a duplicate-default warning.
        project_name = st.text_input("Project name", key="project_name",
            help="Shown in the page title and the exported CSV.")

    st.divider()
    with st.expander("Load sample project", expanded=False):
        st.caption("A generic road upgrade, to explore the tool without entering data.")
        _confirm_load = st.checkbox("I understand this will overwrite all current data", key="confirm_load_sample")
        st.button("Load sample project", key="sidebar_load_sample", use_container_width=True, disabled=not _confirm_load,
                  on_click=_request_sample)

    st.divider()
    st.caption("For practitioner use · Not for public distribution")


# ─────────────────────────────────────────────────────────────────────────────
# PLOTLY LAYOUT DEFAULTS (transparent background for theme compatibility)
# ─────────────────────────────────────────────────────────────────────────────
PLOTLY_TRANSPARENT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")


# ─────────────────────────────────────────────────────────────────────────────
# TITLE — reserved above the tabs, filled after Setup (which holds its settings)
# ─────────────────────────────────────────────────────────────────────────────
_title_slot = st.container()

# ─────────────────────────────────────────────────────────────────────────────
# TABBED LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
tab_inputs, tab_results, tab_cashflow, tab_sensitivity, tab_params, tab_about = st.tabs([
    ":material/edit_note: Inputs",
    ":material/insights: Results",
    ":material/table_chart: Cashflow",
    ":material/tune: Sensitivity",
    ":material/settings: Parameters",
    ":material/info: About",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB: INPUTS — Setup, Traffic (matrices) and Costs
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inputs:
    st.markdown(
        "Appraise a road project against a base case using the TfNSW CBA Guide. "
        "Work through **Setup**, **Traffic** and **Costs**; results update as you go."
    )
    st.caption("New here? Open **Load sample project** in the sidebar to see a worked example.")

    sub_setup, sub_traffic, sub_costs = st.tabs(["1 · Setup", "2 · Traffic", "3 · Costs"])

    # ── Setup ─────────────────────────────────────────────────────────────
    with sub_setup:
        st.caption("Timing, discount rate and how modelled peak periods become annual totals.")

        # These widgets take their values from session state (no value=/index=; set in
        # _init_session_state) so a loaded project can set them without a
        # duplicate-default warning.
        st.markdown('<div class="section-header">Appraisal period</div>', unsafe_allow_html=True)
        _p1, _p2, _p3, _p4 = st.columns(4)
        with _p1:
            construction_start_year = st.number_input("Construction start year", 2020, 2060,
                key="construction_start_year", help="Calendar year construction begins. Benefits start after the construction period.")
        with _p2:
            const_years = st.number_input("Construction period (years)", 1, 10, key="const_years",
                help="Number of construction years; capital is entered by year. Construction disbenefits apply during this period.")
        with _p3:
            eval_period = st.number_input("Evaluation period (years)", 1, 50, key="eval_period",
                help="Appraisal period in years, counted from opening (TfNSW default: 30 years; maximum 50). Construction years are added before it.")
        with _p4:
            discount_base_year = st.number_input("Discount base year", 2020, 2060,
                key="discount_base_year", help="Calendar year used as Year 0 for discounting (PV anchor).")
        if discount_base_year > construction_start_year:
            st.warning(
                f"The discount base year ({discount_base_year}) is after construction starts "
                f"({construction_start_year}). Costs in earlier years are grown forward to "
                "the base year rather than treated as sunk; leave out costs already spent."
            )

        st.markdown('<div class="section-header">Economic settings</div>', unsafe_allow_html=True)
        _e1, _e2, _e3 = st.columns(3)
        with _e1:
            discount_rate = st.number_input("Discount rate (%)", 0.0, 20.0, step=0.5,
                key="discount_rate", help="TfNSW default: 5%. Used to discount future costs and benefits to present values. Higher rates reduce NPV.")
        with _e2:
            context = st.selectbox("Context", ["urban", "rural"], format_func=str.title,
                key="context", help="Affects VTTS rates, VOC speed tables, emission costs, and air pollution rates. Urban uses higher rates.")
        with _e3:
            st.write("")
            zero_growth_after_last_year = st.checkbox(
                "Zero growth after last modelling year",
                key="zero_growth_after_last_year",
                help="On by default: traffic (and the benefits it drives) is held at the last "
                     "modelling year rather than extrapolating the growth trend for the rest of "
                     "the appraisal. Untick only if continued growth is evidenced.",
            )
        _f1, _f2 = st.columns(2)
        with _f1:
            st.radio(
                "Funding", ["nsw", "joint"], key="funding", horizontal=True,
                format_func={"nsw": "NSW-funded", "joint": "NSW and federal"}.get,
                help="Sets the cost per crash (EPV Table 3.18) and the value of a statistical "
                     "life for the VSL test (NSW $7.3M; ATAP $9.7M for joint funding). Jointly "
                     "funded projects of $100m or more also report the National carbon BCR.",
            )
        with _f2:
            st.radio(
                "Urban VOC model", ["stop_start", "freeway"], key="voc_road_type",
                horizontal=True, disabled=context == "rural",
                format_func={"stop_start": "Stop-start (arterial)", "freeway": "Freeway"}.get,
                help="TfNSW depreciation-adjusted VOC model (EPV Tables 3.9 and 3.10). Rural "
                     "roads use the freeway model with the regional vehicle mix, as an "
                     "approximation (the EPV gives rural VOC only as REVS parameters).",
            )

        st.markdown('<div class="section-header">Options and modelling years</div>', unsafe_allow_html=True)
        _o1, _o2 = st.columns([1, 2])
        with _o1:
            # Number of options
            _n_input = st.number_input(
                "Number of options", min_value=1, max_value=5,
                value=st.session_state["n_project_cases"], step=1,
                help="Number of options to compare against the base case (1–5). Each has its own traffic and cost data.",
            )
            if _n_input != st.session_state["n_project_cases"]:
                # _init_session_state() fits traffic and costs at the top of the rerun;
                # calling it here would set widget keys that have already rendered.
                st.session_state["n_project_cases"] = _n_input
                st.rerun()
        with _o2:
            # Modelling years (comma-separated text input)
            _years_raw = st.text_input(
                "Modelling years (comma-separated)",
                value=", ".join(str(y) for y in st.session_state["modelling_years"]),
                key="modelling_years_widget",
                help="Years your traffic model reports, e.g. 2026, 2031, 2041, 2056. Values in between are interpolated.",
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
                st.rerun()
        except ValueError:
            st.error("Invalid year format — enter integers separated by commas.")

        st.write("")
        # Annualisation parameters panel
        with st.expander("Annualisation — peak period to annual totals", expanded=False):
            _ann = st.session_state["annualisation"]
            st.caption("Factor × days per year converts modelled-period VHT/VKT to an annual total.")
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
        if _annualisation_is_default():
            st.warning(
                "Annualisation is still the generic default (6.29 × 336 days for every vehicle "
                "type). It scales every traffic benefit, so use factors from your traffic model "
                "or counts before reporting."
            )

        st.markdown('<div class="section-header">Benefits included</div>', unsafe_allow_html=True)
        _b1, _b2, _b3 = st.columns(3)
        with _b3:
            st.checkbox(
                "VOC from stops", key="include_stop_voc",
                help="Adds change in stops (Inputs → Traffic → Stops) × EPV VOC per stop "
                     "(Table 3.14). Off by default: the speed-based VOC models already reflect "
                     "typical stopping, so use it only where stops change without a matching "
                     "change in average speed (e.g. intersection works, freeway model).",
            )
        with _b1:
            st.checkbox(
                "Reliability benefits", key="include_reliability",
                help="A proxy: travel time savings × reliability ratio × a share (0.3 by default, "
                     "set in Parameters). No published source for the share has been verified, "
                     "so the BCR without reliability is always reported too.",
            )
        with _b2:
            st.checkbox(
                "Road damage savings", key="include_road_damage",
                help="Change in VKT × TfNSW EPV road maintenance cost per vkt (Table 8.1), "
                     "maintenance share only. Don't also enter the same network-wide wear in "
                     "the recurrent costs, or it is counted twice.",
            )

        with st.expander("How benefits are reported", expanded=False):
            st.caption("Choose how much detail to show for environment and reliability.")
            _m2, _m3 = st.columns(2)
            with _m2:
                st.radio(
                    "Environmental breakdown", ["General", "Detailed"],
                    key="env_mode",
                    help="General: single combined environmental benefit line. "
                         "Detailed: separate CO₂ emission cost, air quality & noise columns.",
                )
            with _m3:
                st.radio(
                    "Reliability benefit", ["General", "Detailed"],
                    key="reliability_mode",
                    help="General: reliability benefit included in Travel Time Savings total. "
                         "Detailed: shown as a separate line item in charts and cashflow table.",
                )

        show_advanced = st.checkbox(
            "Show advanced analytics",
            key="show_advanced",
            help="Adds the Monte Carlo risk simulation to the Sensitivity tab.",
        )

    # ── Traffic ───────────────────────────────────────────────────────────
    with sub_traffic:
        st.caption(
            "Peak-period outputs from your traffic model for the base case and each option, "
            f"for modelling years **{', '.join(str(y) for y in st.session_state['modelling_years'])}**. "
            "Annualisation is set in Setup."
        )

        # ── File Upload / Template Download (Step 6) ──────────────────────────
        with st.expander("Import data from file", expanded=False):
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
                        "Download Excel template",
                        tmpl_bytes,
                        file_name="cba_data_template.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                else:
                    # CSV fallback (VHT only) when openpyxl is absent
                    _yrs = st.session_state.modelling_years
                    _nc = st.session_state.n_project_cases
                    _case_labels = case_labels(_nc)
                    csv_lines = ["Case,Vehicle Type," + ",".join(str(y) for y in _yrs)]
                    for cl in _case_labels:
                        for vt in VTYPES:
                            csv_lines.append(f"{cl},{vt}," + ",".join("0" for _ in _yrs))
                    st.download_button(
                        "Download CSV template (VHT)",
                        "\n".join(csv_lines),
                        file_name="cba_vht_template.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                    st.caption("Install openpyxl for the full Excel template.")

        # One metric at a time, so the page stays short as options are added
        _t_vht, _t_vkt, _t_stops, _t_demand, _t_crash, _t_safety, _t_benefit = st.tabs(
            ["VHT", "VKT", "Stops", "Demand", "Crashes", "Safety rates", "Benefit assumptions"])

        # ── Stops ─────────────────────────────────────────────────────────────
        with _t_stops:
            st.caption(
                "Vehicle stops per peak period. Used only when **VOC from stops** is on in "
                "Setup (EPV VOC per stop, Table 3.14)."
            )
            render_traffic_matrix("stops", "stops / peak period")

        # ── VHT ───────────────────────────────────────────────────────────────
        with _t_vht:
            st.caption(
                "Vehicle hours travelled (veh-hrs / peak period). Drives travel time savings; "
                "speed = VKT ÷ VHT (derived, not entered)."
            )
            render_traffic_matrix("vht", "veh-hrs / peak period")

        # ── VKT ───────────────────────────────────────────────────────────────
        with _t_vkt:
            st.caption(
                "Vehicle kilometres travelled (veh-km / peak period). Drives VOC, safety, "
                "emissions, air pollution and noise."
            )
            render_traffic_matrix("vkt", "veh-km / peak period")

        # ── Demand ────────────────────────────────────────────────────────────
        with _t_demand:
            st.caption(
                "Person-trips per peak period, for reference only — benefits are driven by VHT "
                "and VKT, not demand."
            )
            render_traffic_matrix("demand", "person-trips / peak period")

        # ── Crashes by severity ──────────────────────────────────────────────
        with _t_crash:
            st.caption(
                "Crash counts by severity, for reference only — safety benefits use the blended "
                "$/VKT rates in the Parameters tab."
            )
            _sev_labels = ["Fatal", "Serious", "Moderate", "Minor", "PDO"]
            _case_keys = ["base_case"] + [f"project_{i}" for i in range(1, st.session_state.n_project_cases + 1)]
            _case_labels = case_labels(st.session_state.n_project_cases)
            _years = st.session_state["modelling_years"]
            if "crash_data" not in st.session_state:
                st.session_state["crash_data"] = {
                    ck: {sev: [0.0] * len(_years) for sev in _sev_labels}
                    for ck in _case_keys
                }
            _cd = st.session_state["crash_data"]
            # Fit stored data to current cases and years (both can change after init)
            for _ck in _case_keys:
                _cd.setdefault(_ck, {})
                for sev in _sev_labels:
                    _cd[_ck][sev] = (list(_cd[_ck].get(sev, [])) + [0.0] * len(_years))[:len(_years)]
            for _ck, _cl in zip(_case_keys, _case_labels):
                st.markdown(f"**{_cl}**")
                _crash_rows = []
                for sev in _sev_labels:
                    _row = {str(y): _cd[_ck][sev][yi] for yi, y in enumerate(_years)}
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

        # ── Safety $/VKT per case ─────────────────────────────────────────────
        with _t_safety:
            st.caption(
                "Crash cost per vkt for each case. Pick the road type for the EPV default "
                "(crash rate, Table 5.5 × cost per crash, Table 3.18, for the funding basis "
                "in Setup) or enter custom rates with evidence. Benefit = base VKT × base rate "
                "− option VKT × option rate."
            )
            _svd = st.session_state["safety_vkt_data"]
            _sv_case_keys = ["base_case"] + [f"project_{i}" for i in range(1, st.session_state.n_project_cases + 1)]
            _sv_case_labels = case_labels(st.session_state.n_project_cases)
            for _ck, _cl in zip(_sv_case_keys, _sv_case_labels):
                _r1, _r2 = st.columns([1, 2])
                with _r1:
                    # Value from session state (written back in _init_session_state)
                    _road = st.selectbox(_cl, list(SAFETY_ROADS), format_func=SAFETY_ROADS.get,
                                         key=f"sv_road_{_ck}")
                with _r2:
                    if _road != "custom":
                        _svd[_ck] = _epv_safety_rates(_road)
                        # Custom inputs start again from these rates if chosen later
                        for _vt in VTYPES:
                            st.session_state.pop(f"sv_{_ck}_{_vt}", None)
                        st.write("")
                        st.caption(f"EPV default: **${_svd[_ck]['Car']:.4f} per vkt** "
                                   "for every vehicle type")
                    else:
                        _cols = st.columns(4)
                        for _vt, _col in zip(VTYPES, _cols):
                            _svd[_ck][_vt] = _col.number_input(
                                _vt, min_value=0.0, max_value=10.0,
                                value=float(_svd[_ck].get(_vt, 0.0)),
                                step=0.001, format="%.4f",
                                key=f"sv_{_ck}_{_vt}",
                            )
            st.session_state["safety_vkt_data"] = _svd

            if all(_svd[_ck] == _svd["base_case"] for _ck in _sv_case_keys):
                st.info("Every case uses the same rates, so the safety benefit comes only "
                        "from the change in VKT.")

        # ── Benefit assumptions (stored with each option's cost data) ─────────
        with _t_benefit:
            st.caption("Generated demand and new walking and cycling for each option.")
            render_benefit_assumptions()

    # ── Costs ─────────────────────────────────────────────────────────────
    with sub_costs:
        st.caption(
            f"Capital and recurrent costs as yearly cashflows in real {PRICE_LABEL} $M. Year columns "
            "follow the construction start year, construction period and appraisal period in Setup."
        )
        _pending_year = st.session_state.get("_price_year_pending")
        if _pending_year:
            st.warning(
                f"This project was saved in June {_pending_year} dollars; the tool now uses "
                f"{PRICE_LABEL} prices (TfNSW EPV 2026.1). Index its costs by CPI Sydney "
                f"(× {CPI_JUNE_2024_TO_2026:.4f}), or keep them if they are already "
                f"{PRICE_LABEL} dollars. Nominal outturn figures are not changed."
            )
            _i1, _i2, _ = st.columns([1, 1, 1])
            _i1.button(f"Index costs to {PRICE_LABEL}", key="index_costs_2026", type="primary",
                       on_click=_index_pending_costs, use_container_width=True)
            _i2.button("Keep as entered", key="keep_costs_as_entered",
                       on_click=lambda: st.session_state.pop("_price_year_pending", None),
                       use_container_width=True)
        render_cost_entry(const_years, eval_period, construction_start_year)


# ─────────────────────────────────────────────────────────────────────────────
# TITLE — slim line above the tabs
# ─────────────────────────────────────────────────────────────────────────────
with _title_slot:
    st.markdown(f"""
<div class="app-title">
    <h1>{html.escape(project_name or "Transport Cost-Benefit Analysis")}</h1>
    <p>{context.title()} · {discount_rate:g}% discount rate · {eval_period}-year appraisal · {const_years}-year construction from {construction_start_year} · {PRICE_LABEL} $</p>
</div>
""", unsafe_allow_html=True)

_matrix_inputs = {
    "context": context,
    "evaluation_period": eval_period,
    "construction_years": const_years,
    "discount_rate": discount_rate,
    "discount_base_year": discount_base_year,
    "construction_start_year": construction_start_year,
    "zero_growth_after_last_year": zero_growth_after_last_year,
    "include_reliability": st.session_state["include_reliability"],
    "include_road_damage": st.session_state["include_road_damage"],
    "carbon_basis": "nsw",
    "funding": st.session_state["funding"],
    "voc_road_type": st.session_state["voc_road_type"],
    "include_stop_voc": st.session_state["include_stop_voc"],
    "n_project_cases": st.session_state.n_project_cases,
}
# Each case's safety rates (Inputs → Traffic → Safety rates)
_calc_safety_vkt = st.session_state.safety_vkt_data


# ─────────────────────────────────────────────────────────────────────────────
# RUN CALCULATION — after Inputs so edits made this run are included
# ─────────────────────────────────────────────────────────────────────────────
_calc_error = None
try:
    _eff_params = build_effective_params()
    _cache_key = _stable_hash(_matrix_inputs, st.session_state.traffic_data,
                              st.session_state.cost_data, st.session_state.base_case_costs,
                              st.session_state.annualisation,
                              _calc_safety_vkt, _eff_params)
    matrix_results = _cached_calculate_all_cases(
        _cache_key, _matrix_inputs,
        traffic_data=st.session_state.traffic_data,
        cost_data=st.session_state.cost_data,
        base_case_costs=st.session_state.base_case_costs,
        annualisation=st.session_state.annualisation,
        safety_vkt_data=_calc_safety_vkt,
        params=_eff_params,
    )
except Exception as _err:
    matrix_results = {}
    _calc_error = _err

# Checked once per run, after Inputs so this run's edits count
_inputs_present = _has_inputs()

# ── Save Project button (sidebar slot reserved above) ─────────────────────────
with _save_slot:
    _proj_json = json.dumps(_serialise_project(), default=str)
    _safe_filename = re.sub(r'[^\w\s-]', '', st.session_state.get("project_name", "cba_project")).strip().replace(' ', '_') or "cba_project"
    st.download_button(
        "Save project (.json)",
        _proj_json,
        file_name=f"{_safe_filename}.json",
        mime="application/json",
        use_container_width=True,
        # Nothing to save until some traffic or cost has been entered
        disabled=not _inputs_present,
        help=None if _inputs_present else "Enter traffic or costs, or load the sample, first.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB: PARAMETERS (EDITABLE)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_params:
    st.caption("TfNSW economic values used in every calculation. Edit a cell to override it; "
               "clear a cell to return it to the default. Source: TfNSW Economic Parameter "
               "Values 2026.1 (July 2026), June 2026 prices.")

    _r1, _r2 = st.columns([3, 1])
    with _r1:
        _confirm_reset = st.checkbox("I understand this will reset all parameters to TfNSW defaults",
                                     key="confirm_reset_params")
    with _r2:
        if st.button("Reset all to defaults", key="reset_params", disabled=not _confirm_reset,
                     use_container_width=True):
            for _k in list(st.session_state.keys()):
                if _k.startswith("param_"):
                    del st.session_state[_k]
            _bump_param_tables()
            st.rerun()

    _CTX = (("urban", "Urban"), ("rural", "Rural"))
    _VT_ROWS = [("Car", "Car"), ("LCV", "Light commercial (LCV)"),
                ("HCV", "Heavy commercial (HCV)"), ("Bus", "Bus")]

    # ── Value of travel time ─────────────────────────────────────────────────
    with st.expander("Value of travel time ($ per vehicle-hour)", expanded=True):
        st.caption("Average value per vehicle-hour, weighted by vehicle mix: includes the "
                   "private/business car split, freight value for trucks, and a bus driver "
                   "with 20 passengers.")
        param_table("vtt", {
            (_label, _ctx_label): (f"param_vtt_{_ctx}_{_vt}", PARAMS["vtt_vehicle_hr"][_ctx][_vt])
            for _vt, _label in _VT_ROWS for _ctx, _ctx_label in _CTX
        }, unit="$/vehicle-hr", source="EPV 2026.1 Tables 2.2 (urban), 2.3 (rural)",
            max_val=5000.0)

    # ── Reliability ──────────────────────────────────────────────────────────
    with st.expander("Reliability"):
        st.caption("Reliability benefit = travel time savings × ratio × share. The ratio is "
                   "TfNSW's recommended reliability ratio; the share is a proxy with no "
                   "published source verified, so the BCR without reliability is always "
                   "reported and Setup can leave reliability out.")
        param_table("reliability", {
            ("Passenger — Car / Bus", "Ratio"):
                ("param_reliability_ratio", PARAMS["reliability_ratio"]),
            ("Freight — LCV / HCV", "Ratio"):
                ("param_reliability_ratio_freight", PARAMS["reliability_ratio_freight"]),
        }, unit="ratio", source="EPV 2026.1 Table 11.8 (TfNSW recommended 1.0)", max_val=3.0)
        param_table("reliability_share", {
            ("Share of travel time savings", "Share"):
                ("param_reliability_share", PARAMS["reliability_share_of_tts"]),
        }, unit="share", source="Tool default (unverified proxy)", max_val=1.0)

    # ── Safety ───────────────────────────────────────────────────────────────
    with st.expander("Safety — crash rates and costs"):
        st.caption("Default crash cost per vkt = crash rate × cost per crash. Each case picks "
                   "its road type on Inputs → Traffic → Safety rates; Setup sets the funding.")
        param_table("crash_rate", {
            (_cw_label, _ctx_label): (f"param_crash_rate_{_ctx}_{_cw}",
                                      PARAMS["crash_rate_per_100mvkt"][_ctx][_cw])
            for _cw, _cw_label in (("divided", "Divided"), ("single", "Single carriageway"))
            for _ctx, _ctx_label in _CTX
        }, unit="crashes per 100 million vkt", source="EPV 2026.1 Table 5.5", max_val=1000.0)
        param_table("crash_cost", {
            (_f_label, _ctx_label): (f"param_crash_cost_{_fund}_{_ctx}",
                                     PARAMS["cost_per_crash"][_fund][_ctx])
            for _fund, _f_label in (("nsw", "NSW-funded"), ("joint", "NSW and federal"))
            for _ctx, _ctx_label in _CTX
        }, unit="$ per crash", source="EPV 2026.1 Table 3.18", fmt="%.0f", max_val=1e7)
        _vsl = PARAMS["vsl"]
        st.caption(f"Value of a statistical life (VSL sensitivity only): NSW "
                   f"${_vsl['nsw'] / 1e6:.2f}M, ATAP-based ${_vsl['atap'] / 1e6:.2f}M (EPV Table "
                   "5.1). The fatal share of crash costs used for that test is a tool "
                   f"assumption ({PARAMS['safety_severity_share']['fatal']:.0%}).")

    # ── Carbon ───────────────────────────────────────────────────────────────
    with st.expander("Carbon — emissions per vehicle-km"):
        st.caption("Operating carbon per vehicle-km, valued at the carbon value for each year "
                   "(see Carbon values).")
        param_table("carbon", {
            (_label, "kg CO₂-e/vkt"): (f"param_carbon_kg_{_vt}",
                                       PARAMS["carbon_t_per_vkt"][_vt] * 1000)
            for _vt, _label in _VT_ROWS
        }, unit="kg CO₂-e per vkt", fmt="%.4f", max_val=10.0,
            source="EPV 2026.1 Tables 6.2 (car, bus) and 6.3 (LCV, HV) at the FY2026 core value")
        param_table("emission_change", {
            ("Emissions per veh-km", "% change a year"):
                ("param_emission_change_pct", PARAMS["emission_factor_change_pct"]),
        }, unit="% a year from FY2026 (negative = falling)", min_val=-20.0, max_val=20.0,
            source="Tool default 0% (enter a sourced fleet projection)")

    with st.expander("Carbon values ($/tCO₂-e by year)"):
        st.caption("The core result uses NSW Carbon Values (NSW Treasury TPG24-34); the BCR "
                   "with National Carbon Values is reported alongside. EPV 2026.1 Table 6.1 "
                   "FY2026 value × Table 6.4 factors, June 2026 $. Years after 2050 hold the "
                   "2050 value.")
        _cy = sorted(set(CARBON_VALUES["nsw"]["central"]) | set(CARBON_VALUES["national"]["central"]))
        st.dataframe(pd.DataFrame({
            f"{'NSW' if _b == 'nsw' else 'National'} {_c}": [CARBON_VALUES[_b][_c].get(_y) for _y in _cy]
            for _b in ("nsw", "national") for _c in CARBON_VALUES[_b] if _c != "label"
        }, index=pd.Index(_cy, name="Financial year")), use_container_width=True, height=300)

    # ── Other externalities ──────────────────────────────────────────────────
    with st.expander("Other externalities (cents/veh-km)"):
        st.caption("Air pollution, well-to-tank emissions, noise, soil and water, nature and "
                   "landscape, urban effects and biodiversity, per vehicle-km.")
        param_table("externalities", {
            (_label, _ctx_label): (f"param_ext_{_ctx}_{_vt}", PARAMS["externality_cents_vkt"][_ctx][_vt])
            for _vt, _label in _VT_ROWS for _ctx, _ctx_label in _CTX
        }, unit="cents/veh-km (total)", source="EPV 2026.1 Tables 6.5–6.8", max_val=500.0)
        st.caption("Breakdown of the defaults (cents/veh-km):")
        _brk = PARAMS["externality_breakdown_cents_vkt"]
        st.dataframe(pd.DataFrame({
            f"{_vt} {_ctx}": _brk[_ctx][_vt] for _ctx in ("urban", "rural") for _vt in VTYPES
        }), use_container_width=True)

    # ── Road damage ──────────────────────────────────────────────────────────
    with st.expander("Road damage (cents/veh-km)"):
        st.caption("Road damage savings = change in VKT × rate × maintenance share. HCV uses "
                   "the heavy-vehicle sub-total; Bus the bus average.")
        param_table("road_damage", {
            (_vt, "c/veh-km"): (f"param_road_damage_{_vt}", PARAMS["road_damage_cents_vkt"][_vt])
            for _vt in VTYPES
        }, unit="cents/veh-km", source="EPV 2026.1 Table 8.1", max_val=100.0)
        param_table("road_damage_share", {
            ("Maintenance share counted", "Share"):
                ("param_road_damage_share", PARAMS["road_damage_maintenance_share"]),
        }, unit="share", max_val=1.0,
            source="EPV Table 8.1 note: 46% repair and maintenance, 54% road provision")

    # ── Active Transport Health Benefits ─────────────────────────────────────
    with st.expander("Active transport health benefits ($/km)"):
        param_table("health", {
            (_label, "$/km"): (f"param_health_{_mode}", PARAMS["health_benefits"][_mode])
            for _mode, _label in [("walking", "Walking"), ("cycling", "Cycling")]
        }, unit="$/km", source="EPV 2026.1 Table 7.1 (NSW Ministry of Health)", max_val=20.0)
        st.caption("Extra savings per km when the walking or cycling replaces a car trip "
                   "(applied to each option's car-trip share; EPV 2026.1 Table 7.1, former car "
                   "users). TfNSW does not recommend valuing travel time for active transport.")
        st.dataframe(pd.DataFrame(PARAMS["active_car_savings"]).rename(columns=str.title),
                     use_container_width=True)

    # ── VOC tables (read-only reference) ─────────────────────────────────────
    for _model, _title in (("stop_start", "urban stop-start (Table 3.9)"),
                           ("freeway", "urban freeway (Table 3.10)"),
                           ("rural", "rural — freeway model, regional mix")):
        with st.expander(f"Vehicle operating costs — {_title} ($/veh-km, read-only)"):
            _voc = PARAMS["voc"][_model]
            st.dataframe(pd.DataFrame(_voc).rename_axis("Speed (km/h)"),
                         use_container_width=True)
    with st.expander("VOC per stop ($/stop)"):
        st.caption("Used only when VOC from stops is on in Setup. LCV uses the EPV light "
                   "truck; HCV and Bus the heavy truck.")
        param_table("voc_stop", {
            (_label, "$/stop"): (f"param_voc_stop_{_vt}", PARAMS["voc_per_stop"][_vt])
            for _vt, _label in _VT_ROWS
        }, unit="$ per stop, incl. fuel", fmt="%.4f", max_val=20.0,
            source="EPV 2026.1 Table 3.14")

    with st.expander("Asset lives (years, read-only)"):
        st.caption("Economic life by asset class, for the residual value asset life "
                   "(Inputs → Costs). Source: EPV 2026.1 Table 12.1 (ATAP 2018, TfNSW).")
        st.dataframe(pd.DataFrame(
            [{"Asset class": a, "Life (years)": f"{lo}" if lo == hi else f"{lo}–{hi}"}
             for a, lo, hi in ASSET_LIVES]), hide_index=True, use_container_width=True)

    st.caption("VOC: TfNSW depreciation-adjusted resource-cost models. Car = medium car; LCV = "
               "courier van/utility and 4WD; HCV = all rigid, articulated and combination "
               "trucks; LCV and HCV weighted by the EPV vehicle mix (Table 3.19).")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB: ABOUT
# ═══════════════════════════════════════════════════════════════════════════════
with tab_about:
    st.markdown("## About this tool")
    st.markdown(
        "This dashboard helps CBA practitioners and business case writers in NSW "
        "assess the economic viability of transport infrastructure projects. "
        "It implements the **TfNSW Economic Parameter Values 2026.1 (July 2026, June 2026 prices)** "
        "framework and produces the standard outputs required for NSW Government business cases: "
        "net present value (NPV), benefit–cost ratio (BCR), and sensitivity analysis."
    )

    st.divider()

    # ── What the model calculates ────────────────────────────────────────────
    st.markdown("### What the model calculates")
    st.markdown(
        "The tool compares a **Base Case** (do-minimum, typically the existing network) "
        "against up to five **options** (proposed interventions). "
        "All benefits are *incremental* — the difference between each option and the base case. "
        "Costs and benefits are discounted to a common base year, summed over the appraisal period, "
        "and expressed as:"
    )
    col_npv, col_bcr, col_pv = st.columns(3)
    with col_npv:
        st.info("**Net present value (NPV)**\nPV benefits minus PV costs. Positive NPV indicates the project returns more to society than it costs.")
    with col_bcr:
        st.info("**Benefit–cost ratio (BCR)**\nPV benefits ÷ PV costs. BCR ≥ 1.0 indicates benefits ≥ costs. Higher values indicate greater relative economic returns.")
    with col_pv:
        st.info("**Present value of benefits by type**\nBreaks the total benefit into its components so you can see which categories drive the result.")

    st.divider()

    # ── Benefit categories ───────────────────────────────────────────────────
    st.markdown("### Benefit categories")
    st.markdown(
        "The model quantifies five categories of transport benefit, all derived from changes in traffic "
        "volumes, travel times, and speeds between the base case and each option. "
        "Further lines follow the TfNSW Guide: reliability (a proxy), road damage savings, "
        "recurrent cost savings, upfront carbon and construction disruption (disbenefits), "
        "and residual value:"
    )

    benefit_rows = [
        ("Travel time savings (TTS)", "tts", "blue",
         "The most significant benefit in most road projects. "
         "The reduction in vehicle-hours travelled (VHT) × the average value of travel time per "
         "vehicle-hour, which already includes occupancy, the private/business car split, "
         "freight value for trucks and bus passengers (urban: car $37.75, LCV $46.29, HCV "
         "$76.71, bus $498.05 per vehicle-hour). Source: TfNSW EPV 2026.1 Tables 2.2 and 2.3."),
        ("Vehicle operating costs (VOC)", "voc", "orange",
         "Savings in fuel, tyres, maintenance, and depreciation when a project changes vehicle speeds. "
         "Rates depend on average speed (VKT ÷ VHT) and come from the TfNSW depreciation-"
         "adjusted resource-cost models: stop-start (arterial) or freeway for urban roads, set in "
         "Setup. Rural roads use the freeway model with the regional vehicle mix, an "
         "approximation because the EPV gives rural VOC only as REVS model parameters. Car is a "
         "medium car; LCV, HCV and bus use their EPV vehicle classes weighted by the EPV vehicle "
         "mix. Speeds outside 20–110 km/h use the table's end value (flagged on Results). "
         "Optionally (Setup, off by default), the change in stops × EPV VOC per stop (Table "
         "3.14) is added — only where stops change without a matching change in speed, as the "
         "speed-based models already reflect typical stopping. "
         "Source: TfNSW EPV 2026.1 Tables 3.9, 3.10 and 3.19."),
        ("Reliability", "reliability", "indigo",
         "A proxy: travel time savings × reliability ratio (1.0, TfNSW recommended, EPV "
         "Table 11.8) × a share of 0.3. No published source for the 0.3 share has been verified, so the BCR "
         "without reliability is always reported and Setup can leave reliability out. The "
         "TfNSW Guide values reliability from the change in travel-time variability."),
        ("Safety", "safety", "red",
         "Base VKT × base crash cost per vkt − option VKT × option crash cost per vkt. Each "
         "case picks its road type (urban or rural, divided or single carriageway) for the EPV "
         "default = crash rate (Table 5.5) × average cost per crash (Table 3.18, NSW-funded or "
         "jointly funded), or enters custom rates (Inputs → Traffic → Safety rates). A safer "
         "design (e.g. divided road) therefore gets credit through a lower rate."),
        ("Environmental", "env", "green",
         "Calculated per change in VKT: (1) **Operating carbon** — kg CO₂-e per vehicle-km "
         "(EPV Tables 6.2, 6.3) valued at the NSW Carbon Value for each year (TPG24-34, June "
         "2026 $: $139.66/t in 2026 rising to $373.13/t from 2039); (2) **other externalities** "
         "— air pollution, well-to-tank emissions, noise, soil and water, nature and landscape, "
         "urban effects and biodiversity (EPV Tables 6.5–6.8, urban and rural)."),
        ("Active transport health benefits", "active", "purple",
         "Benefits from additional walking or cycling induced by the project, "
         f"valued at the NSW Health rates (walking ${PARAMS['health_benefits']['walking']:.2f}/km; "
         f"cycling ${PARAMS['health_benefits']['cycling']:.2f}/km). "
         "The share of those km that replaces car trips also earns the EPV savings for "
         "former car users (decongestion, VOC, crashes, externalities, road provision, "
         "parking; walking $1.15/km, cycling $1.25/km) — leave it at 0% if the traffic model "
         "already removes those car trips. No travel time value, per TfNSW. "
         "Source: TfNSW EPV 2026.1 Table 7.1."),
        ("Road damage savings", "road_damage", "brown",
         "Change in VKT × TfNSW road maintenance cost per vehicle-km (EPV 2026.1 Table 8.1: "
         "Car and LCV 5.61c, heavy vehicles 19.28c, buses 10.55c) × the 46% maintenance share. Can be switched off in Setup; don't also put the same "
         "network-wide wear in the recurrent costs."),
        ("Recurrent cost savings", "recurrent_savings", "teal",
         "Recurrent costs are net of the base case. When the option is cheaper to run and "
         "maintain than the base case (in PV terms), the saving is this benefit; when it costs "
         "more, the increase is a cost. TfNSW CBA Guide (2024) §6.8 prefers cost savings as a "
         "benefit."),
        ("Upfront carbon emissions", "upfront_carbon", "grey",
         "Embodied carbon from construction (tonnes CO\u2082e) is spread across the construction "
         "years in proportion to the P50 capital cashflow and valued at the NSW Carbon Value "
         "for each year. Reported as a disbenefit (negative benefit)."),
        ("Construction disruption", "construction_disruption", "grey",
         "The annual cost of traffic disruption during construction, reported as a disbenefit "
         "in each construction year."),
        ("Residual value", "residual", "brown",
         "Remaining value of the assets at the end of the appraisal period, credited at the "
         "end of the final year (discounted one year further than that year's other flows). "
         "The asset life can be filled from EPV Table 12.1 (e.g. asphalt pavement 30–40 "
         "years, concrete bridges 120). "
         "Land keeps its full value; construction (including its share of "
         "contingency) depreciates straight-line over the asset life; planning and design "
         "have none. A manual residual value overrides the calculation."),
    ]

    for name, key, colour, explanation in benefit_rows:
        with st.expander(f"**{name}**"):
            st.markdown(explanation)

    st.divider()

    # ── How costs are treated ────────────────────────────────────────────────
    st.markdown("### How costs are treated")
    st.markdown(
        f"Costs are entered as **yearly cashflows** in real {PRICE_LABEL} dollars, so the model "
        "never spreads a total over the years for you. Paste a row from Excel into each table."
    )
    cost_data = {
        "Cost": [
            "Capital (P50)",
            "Capital (P90)",
            "Project recurrent costs",
            "Base case recurrent costs",
            "Upfront carbon",
            "Outturn capital (nominal)",
        ],
        "How it is used": [
            "Planning and design, land and construction base estimates plus the yearly contingency "
            "that takes the base to P50, entered over the construction years. This is the capital "
            "cost in the core result.",
            "The same base estimates plus the contingency that takes them to P90. Used only in the "
            "'P90 capital cost' sensitivity test.",
            "Operations, maintenance and periodic renewals by year for each option, over the whole "
            "timeline including construction. Only the difference from the base case counts: a net "
            "increase is a cost, a net saving the 'Recurrent cost savings' benefit.",
            "The same, for the do-minimum base case, shared by all options. Each option's recurrent "
            "costs are compared with it.",
            "Tonnes CO\u2082e for each option, valued at the NSW Carbon Value for each year and "
            "reported as a disbenefit.",
            "P50 and P90 outturn capital in nominal dollars, copied from the cost estimate. Shown in "
            "the appraisal summary and CSV only; never used in a calculation.",
        ],
    }
    st.table(pd.DataFrame(cost_data).set_index("Cost"))

    st.divider()

    # ── Discounting ─────────────────────────────────────────────────────────
    st.markdown("### Discounting")
    st.markdown(
        "All future cash flows are converted to present-value terms using a **start-of-year** "
        "discount convention: a dollar in year *n* is worth `1 / (1 + r)^n` today, "
        "where *r* is the discount rate. "
        "The default rate is **5%** per annum. The required sensitivity table always re-runs "
        "the model at 3%, 4% and 7% (4% for federal submissions), whatever the central rate is. "
        "Residual value is discounted from the end of the final year. Costs before the discount "
        "base year are grown forward, so leave out costs already spent (sunk)."
    )

    st.divider()

    # ── Annualisation ───────────────────────────────────────────────────────
    st.markdown("### From model years to annual traffic")
    st.markdown(
        "Traffic models typically produce results for a small number of **modelling years** "
        "(e.g. 2026, 2031, 2041, 2056). The tool interpolates between these years using "
        "**compound annual growth rate (CAGR)** — the geometric mean — rather than straight-line "
        "interpolation. This better reflects how traffic volumes typically grow."
    )
    st.markdown(
        "Peak-period model outputs are converted to annual totals using an "
        "**annualisation factor** and **days per year** for each vehicle type. "
        "The defaults are generic, so replace them with factors from your traffic model or "
        "counts in **Inputs → Setup** (Results warns while they are unchanged). After the last "
        "modelling year traffic is held flat by default rather than extrapolated."
    )

    st.divider()

    # ── Sensitivity analysis ─────────────────────────────────────────────────
    st.markdown("### Sensitivity analysis")
    st.markdown(
        "The **Sensitivity** tab opens with the **TfNSW required sensitivity tests** table, "
        "with the central row highlighted, so a reviewer can see every required test was run:"
    )
    sens_rows = [
        ("Discount rate", "3%, 4% and 7%, whatever the central rate is."),
        ("Costs and benefits", "Project costs and transport benefits at +20%, \u221220%, +40% and \u221240%. Residual value follows capital; recurrent cost savings, upfront carbon and construction disruption are not scaled."),
        ("P90 capital cost", "Capital at base plus the P90 contingency in every year."),
        ("Opening delayed", "Opening delayed by 1 year and by 3 years, with benefits recalculated for the delayed calendar years."),
        ("Traffic growth", "No traffic growth, and half the forecast traffic growth, from the opening year."),
        ("Other analyses", "Switching values, the discount rate chart, carbon values (NSW and National, low/central/high), VSL and WEBs sensitivity, and Monte Carlo risk analysis (advanced mode)."),
    ]
    sens_df = pd.DataFrame(sens_rows, columns=["Analysis", "What it shows"])
    st.table(sens_df.set_index("Analysis"))

    st.divider()

    # ── Parameter sources ────────────────────────────────────────────────────
    st.markdown("### Parameter sources and overrides")
    st.markdown(
        "All default parameter values are sourced from the "
        "**TfNSW Economic Parameter Values 2026.1, July 2026 (June 2026 prices)**. "
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
    st.markdown("### Limitations and appropriate use")
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
    st.markdown("### Key references")
    st.markdown(
        "- Transport for NSW — *Economic Parameter Values 2026.1*, July 2026 (June 2026 prices)\n"
        "- Transport for NSW — *Implementation of NSW Government Business Case Guidelines and "
        "Carbon*, October 2025\n"
        "- Transport for NSW — *Cost-Benefit Analysis Guide*, August 2024\n"
        "- NSW Treasury — *NSW Government Guide to Cost-Benefit Analysis* (TPG23-08)\n"
        "- Infrastructure Australia — *Assessment Framework*, 2021\n"
        "- National Transport Commission — *Australian Fleet Emission Factors*, 2023\n"
        "- Department of Infrastructure, Transport, Regional Development, Communications and the Arts — "
        "*Australian Transport Assessment and Planning (ATAP) Guidelines*"
    )

# ─────────────────────────────────────────────────────────────────────────────
# EMPTY STATE — nothing entered yet (or the calculation failed): the result tabs
# show a prompt instead. Parameters and About are drawn above, so st.stop() is safe.
# ─────────────────────────────────────────────────────────────────────────────
if _calc_error is not None or not _inputs_present:
    for _tab, _where in ((tab_results, "results"), (tab_cashflow, "cashflow"),
                         (tab_sensitivity, "sensitivity")):
        with _tab:
            if _calc_error is not None:
                st.error(f"Calculation error: {_calc_error}. Please check your input data "
                         "for missing or invalid values.")
                continue
            st.markdown(
                '<div class="empty-state"><h3>No results yet</h3>'
                f'<p>Enter traffic and costs in the Inputs tab to see the {_where} here.</p></div>',
                unsafe_allow_html=True,
            )
            if _where == "results":
                _b1, _b2, _b3 = st.columns([2, 1, 2])
                _b2.button("Load sample project", key="empty_load_sample", type="primary",
                           use_container_width=True, on_click=_request_sample,
                           help="Fills the inputs with an illustrative generic road upgrade.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB: RESULTS — headline NPV / BCR cards, appraisal summary, charts
# ═══════════════════════════════════════════════════════════════════════════════
with tab_results:
    st.caption(
        f"Each option against the base case, in real {PRICE_LABEL} dollars discounted at {discount_rate:g}%."
    )
    _n_cases = st.session_state.n_project_cases

    if _n_cases > 1:
        # One compact card pair per option, two options per row
        for _row_start in range(1, _n_cases + 1, 2):
            _row_cases = list(range(_row_start, min(_row_start + 2, _n_cases + 1)))
            for _i, _col in zip(_row_cases, st.columns(2, gap="large")):
                _mr = matrix_results.get(f"project_{_i}", {})
                with _col:
                    st.markdown(f"**{case_label(f'project_{_i}')}**")
                    _c_npv, _c_bcr = st.columns(2)
                    _c_npv.metric("NPV", format_m(_mr.get("npv", 0)),
                                  delta="Positive" if _mr.get("npv", 0) >= 0 else "Negative",
                                  delta_color="normal" if _mr.get("npv", 0) >= 0 else "inverse")
                    _bcr_metric(_c_bcr, "BCR", _mr.get("bcr"), "≥ 1.0", "< 1.0")
    else:
        _r_kpi = matrix_results["project_1"]
        _k1, _k2, _k3 = st.columns([1, 1, 1.4])
        with _k1:
            st.metric("Net present value", format_m(_r_kpi["npv"]),
                      delta="Positive" if _r_kpi["npv"] >= 0 else "Negative",
                      delta_color="normal" if _r_kpi["npv"] >= 0 else "inverse")
        with _k2:
            _bcr_metric(st, "Benefit-cost ratio", _r_kpi["bcr"], "Above 1.0", "Below 1.0")
        with _k3:
            # Escape $ so Markdown does not read the amounts as LaTeX
            _pvb_md = format_m(_r_kpi["pv_benefits"]).replace("$", "\\$")
            _pvc_md = format_m(_r_kpi["pv_costs"]).replace("$", "\\$")
            st.caption(f"PV benefits **{_pvb_md}** · PV costs **{_pvc_md}**")
            st.caption("NPV is PV benefits minus PV costs. A BCR above 1.0 means benefits exceed costs.")
            st.caption(f"BCR without reliability **{fmt_bcr(_r_kpi['bcr_without_reliability'])}** · "
                       f"with National carbon values **{fmt_bcr(_r_kpi['bcr_national_carbon'])}**")

    # Checks a reviewer would ask about, for every option
    _checks = _result_checks(matrix_results)
    if _checks:
        st.warning("**Check before reporting**\n\n" + "\n".join(f"- {c}" for c in _checks))

    # ── Case selector (Step 10): pick which option drives the charts & waterfall ─
    _n_dash = st.session_state.n_project_cases
    _CASE_PALETTE = ["#0d6efd", "#fd7e14", "#198754", "#dc3545", "#6610f2"]

    # ── Appraisal summary: one column per option ─────────────────────────────
    st.markdown('<div class="section-header">Appraisal summary</div>', unsafe_allow_html=True)
    _summ_cols: dict = {}
    for _sk, _sr in matrix_results.items():
        _summ = appraisal_summary(_sr, st.session_state.cost_data.get(_sk, {}))
        _summ_cols[case_label(_sk)] = [
            format_summary_value(_k, _v, screen=True) for _k, _v in _summ.items()
        ]
    st.dataframe(pd.DataFrame(_summ_cols, index=list(_summ.keys())),
                 use_container_width=True,
                 height=35 * (len(_summ) + 1) + 3)  # every row, no inner scroll
    st.caption(
        "Outturn capital is nominal $M, copied from the cost estimate and never used in "
        f"the calculation. All other figures are real {PRICE_LABEL} dollars."
    )

    st.markdown('<div class="section-header">Charts</div>', unsafe_allow_html=True)
    if _n_dash > 1:
        _dash_case = st.selectbox(
            "Option to display in charts",
            options=[f"project_{i}" for i in range(1, _n_dash + 1)],
            format_func=case_label,
            key="dash_case_sel",
        )
        _r = matrix_results[_dash_case]
    else:
        _r = matrix_results["project_1"]
        _dash_case = "project_1"

    # Display Rule-of-Half assumptions for transparency
    _cost_data = st.session_state.get("cost_data", {})
    _case_cost = _cost_data.get(_dash_case, {})
    render_rule_of_half_assumptions(_case_cost)

    _reliability_mode = st.session_state.get("reliability_mode", "General")
    # PV by benefit line, with reliability folded into travel time in General mode
    pv = _r["pv_by_type"]
    _pv_display = dict(pv)
    if _reliability_mode == "General":
        _pv_display["tts"] = pv.get("tts", 0) + pv.get("reliability", 0)
        _pv_display["reliability"] = 0.0

    # One chart for the benefit lines: green adds to NPV, red subtracts, blue is a total
    with st.container():
        st.markdown("**Benefits, costs and NPV (PV $M)**")
        # Build waterfall series respecting reliability mode
        if _reliability_mode == "General":
            _wf_types = ["tts", "voc", "safety", "env", "road_damage", "active",
                         "recurrent_savings", "upfront_carbon", "construction_disruption",
                         "residual"]
            _wf_labels_benefit = ["Travel time and reliability"] + [
                TYPE_LABELS[t] for t in _wf_types[1:]
            ]
        else:
            _wf_types = list(TYPE_LABELS.keys())
            _wf_labels_benefit = list(TYPE_LABELS.values())
        # Lines that are exactly zero (e.g. no construction disruption entered) are
        # left out to keep the axis readable and named in a caption instead
        _wf_items = [(lbl, _pv_display.get(t, 0))
                     for t, lbl in zip(_wf_types, _wf_labels_benefit)
                     if abs(_pv_display.get(t, 0)) > 1e-9]
        _wf_zero = [lbl for t, lbl in zip(_wf_types, _wf_labels_benefit)
                    if abs(_pv_display.get(t, 0)) <= 1e-9]
        wf_labels = [lbl for lbl, _ in _wf_items] + ["Total benefits", "Costs", "NPV"]
        wf_values = [v for _, v in _wf_items] + [_r["pv_benefits"], -_r["pv_costs"], _r["npv"]]
        wf_measures = ["relative"] * len(_wf_items) + ["total", "relative", "total"]
        wf_text = ([signed_m(v) for v in wf_values[:-3]]
                   + [format_m(_r["pv_benefits"]), signed_m(-_r["pv_costs"]), format_m(_r["npv"])])
        # Horizontal so the line names stay readable
        fig_wf = go.Figure(go.Waterfall(
            orientation="h",
            y=wf_labels, x=wf_values, measure=wf_measures,
            connector={"line": {"color": "#ced4da"}},
            increasing={"marker": {"color": COLORS["positive"]}},
            decreasing={"marker": {"color": COLORS["negative"]}},
            totals={"marker": {"color": COLORS["neutral"]}},
            textposition="outside", textfont_size=11,
            text=wf_text, cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra></extra>",
        ))
        fig_wf.update_layout(
            height=max(300, 34 * len(wf_labels) + 80),
            margin=dict(t=20, b=30, l=190, r=80),
            xaxis_title="$M", showlegend=False,
            yaxis=dict(autorange="reversed"),
            **PLOTLY_TRANSPARENT,
        )
        st.plotly_chart(fig_wf, use_container_width=True)
        if _wf_zero:
            st.caption("No value in this appraisal: " + ", ".join(_wf_zero) + ".")

    # ── Row 2: Cashflow & Cumulative ─────────────────────────────────────────
    chart3, chart4 = st.columns(2)
    _years_dash = list(range(construction_start_year, construction_start_year + _r["total_years"]))

    with chart3:
        st.markdown("**Annual net cashflow ($M, undiscounted)**")
        fig_cf = go.Figure()
        if matrix_results and _n_dash > 1:
            # Overlay net cashflow for every option
            for _i in range(1, _n_dash + 1):
                _mr_i = matrix_results.get(f"project_{_i}", {})
                if _mr_i:
                    fig_cf.add_trace(go.Scatter(
                        x=list(range(construction_start_year, construction_start_year + _mr_i["total_years"])),
                        y=_mr_i["annual_net"],
                        name=f"{case_label(f'project_{_i}')} net", mode="lines+markers",
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
        st.markdown("**Cumulative discounted net benefits ($M)**")
        fig_cum = go.Figure()
        if matrix_results and _n_dash > 1:
            # Overlay cumulative NPV for every option
            for _i in range(1, _n_dash + 1):
                _mr_i = matrix_results.get(f"project_{_i}", {})
                if _mr_i:
                    _col_i = _CASE_PALETTE[(_i - 1) % len(_CASE_PALETTE)]
                    fig_cum.add_trace(go.Scatter(
                        x=list(range(construction_start_year, construction_start_year + _mr_i["total_years"])),
                        y=_mr_i["cum_disc_net"],
                        mode="lines", name=case_label(f"project_{_i}"),
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


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: DETAILED CASHFLOW
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cashflow:
    st.caption("Year-by-year costs and benefits for one option, undiscounted or discounted. "
               "Download the table or the full results as CSV.")

    _cf_case_keys = list(matrix_results.keys())
    if len(_cf_case_keys) > 1:
        _cf_sel = st.selectbox(
            "Option",
            options=_cf_case_keys,
            format_func=case_label,
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
            _tts_label = "Travel time & reliability ($M)"
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
                "CO₂ emission cost ($M)": [round(v, 3) for v in _env_emit],
                "Air quality & noise ($M)": [round(e - em, 3) for e, em in zip(_bbt["env"], _env_emit)],
            }
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Capital ($M)": [round(c, 3) for c in _r_cf["annual_capital"]],
            "Net recurrent ($M)": [round(c, 3) for c in _r_cf["annual_recurrent"]],
            "Benefits ($M)": [round(b, 3) for b in _r_cf["annual_benefits"]],
            # Net sits beside the totals so it is visible without scrolling
            "Net ($M)": [round(n, 3) for n in _r_cf["annual_net"]],
            _tts_label: _tts_vals,
            **_tts_cols,
            **_rel_cols,
            "VOC ($M)": [round(v, 3) for v in _bbt["voc"]],
            "Safety ($M)": [round(v, 3) for v in _bbt["safety"]],
            **_env_cols,
            "Road damage savings ($M)": [round(v, 3) for v in _bbt["road_damage"]],
            "Active transport ($M)": [round(v, 3) for v in _bbt["active"]],
            "Recurrent cost savings ($M)": [round(v, 3) for v in _bbt["recurrent_savings"]],
            "Upfront carbon ($M)": [round(v, 3) for v in _bbt["upfront_carbon"]],
            "Construction disruption ($M)": [round(v, 3) for v in _bbt["construction_disruption"]],
            "Residual value ($M)": [round(v, 3) for v in _bbt["residual"]],
        })
    else:
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Costs ($M)": [round(c, 3) for c in _r_cf["disc_costs"]],
            "Benefits ($M)": [round(b, 3) for b in _r_cf["disc_benefits"]],
            "Net ($M)": [round(n, 3) for n in _r_cf["disc_net"]],
            "Cumulative net ($M)": [round(c, 3) for c in _r_cf["cum_disc_net"]],
        })

    # Shown to 2 dp; the CSV download keeps 3 dp
    st.dataframe(
        df_cf, use_container_width=True, hide_index=True,
        column_config={
            "Year": st.column_config.NumberColumn("Year", format="%d", pinned=True),
            **{c: st.column_config.NumberColumn(c, format="%.2f") for c in df_cf.columns if c != "Year"},
        },
    )

    # Download for this table
    cf_csv = df_cf.to_csv(index=False)
    _dl_col1, _dl_col2, _ = st.columns([1, 1, 1])
    with _dl_col1:
        st.download_button(
            f"Download {view_mode.lower()} cashflow CSV",
            cf_csv,
            file_name=f"cashflow-{view_mode.lower()}{_cf_filename_suffix}.csv",
            mime="text/csv",
            key="dl_cashflow",
            use_container_width=True,
        )
    with _dl_col2:
        _full_export_r = matrix_results.get(_cf_sel, {})
        if _full_export_r:
            _csv_cost = st.session_state.cost_data[_cf_sel]
            _csv_rows = _required_rows_for(_cf_sel)
            _full_csv = generate_csv(
                _full_export_r, project_name,
                appraisal_summary(_full_export_r, _csv_cost), _csv_rows)
            _case_label = f"project-{_cf_sel.split('_')[1]}" if "_" in _cf_sel else _cf_sel
            st.download_button(
                "Download full results CSV",
                _full_csv,
                file_name=f"cba-results-{_case_label}.csv",
                mime="text/csv",
                key="dl_full_results",
                use_container_width=True,
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: SENSITIVITY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sensitivity:
    st.caption("How robust the result is. The TfNSW required tests come first; "
               "open a panel below for the other analyses.")

    _sens_case_keys = list(matrix_results.keys())
    if len(_sens_case_keys) > 1:
        _sens_sel = st.selectbox(
            "Option",
            options=_sens_case_keys,
            format_func=case_label,
            key="sens_case_sel",
        )
    else:
        _sens_sel = _sens_case_keys[0]
    _r_sens = matrix_results[_sens_sel]

    # --- TfNSW required sensitivity tests (one row per test) ---
    st.markdown('<div class="section-header">TfNSW required sensitivity tests</div>',
                unsafe_allow_html=True)
    _req_rows = _required_rows_for(_sens_sel)

    if _req_rows:
        df_req = pd.DataFrame([{
            "Test": r["test"],
            "PV benefits ($M)": r["pvb"],
            "PV costs ($M)": r["pvc"],
            "NPV ($M)": r["npv"],
            "BCR": r["bcr"],
        } for r in _req_rows])
        _central_tests = {r["test"] for r in _req_rows if r["central"]}

        def _highlight_required(row):
            styles = [""] * len(row)
            if row["Test"] in _central_tests:
                styles = ["background-color: rgba(13, 110, 253, 0.1); font-weight: 700"] * len(row)
            bcr_idx = df_req.columns.get_loc("BCR")
            if pd.notna(row["BCR"]):
                styles[bcr_idx] += ("; color: #198754; font-weight: 700" if row["BCR"] >= 1
                                    else "; color: #dc3545; font-weight: 700")
            return styles

        st.dataframe(
            df_req.style.apply(_highlight_required, axis=1).format({
                "PV benefits ($M)": "{:.1f}", "PV costs ($M)": "{:.1f}",
                "NPV ($M)": "{:.1f}",
                "BCR": lambda b: fmt_bcr(None if pd.isna(b) else b),
            }),
            use_container_width=True, hide_index=True,
            height=35 * (len(df_req) + 1) + 3,  # all 17 rows, no inner scroll
        )
        st.caption("Highlighted row = central case (P50 capital, central discount rate). "
                   "Discount rates 3%, 4% and 7% are always shown; 4% is for federal (PPR) "
                   "submissions. Cost tests scale capital and recurrent costs; benefit tests "
                   "scale transport benefits only. A manual residual value is kept in every test.")

    # --- Discount rate and switching values ---
    with st.expander("Discount rate and switching values — how far inputs can move before BCR falls to 1", expanded=False):
        sen1, sen2 = st.columns(2)

        with sen1:
            st.subheader("Discount rate sensitivity (BCR)")
            # Central rate once, plus the required 3%, 4% and 7% rows
            _dr_points = {}
            for _row in _req_rows:
                if _row["central"]:
                    _dr_points[_r_sens["dr"]] = _row["bcr"]
            for _row in _req_rows:
                if _row["test"].startswith("Discount rate "):
                    _dr_points.setdefault(float(_row["test"].split()[-1].rstrip("%")), _row["bcr"])
            # A BCR that is not defined (PV costs <= 0) has no bar
            dr_rates = sorted(r for r in _dr_points if _dr_points[r] is not None)
            dr_bcrs = [_dr_points[r] for r in dr_rates]
            bar_colors = [COLORS["positive"] if b >= 1 else COLORS["negative"] for b in dr_bcrs]
            fig_dr = go.Figure(go.Bar(
                x=[f"{r:g}%" for r in dr_rates], y=dr_bcrs,
                marker_color=bar_colors,
                text=[f"{b:.2f}" for b in dr_bcrs], textposition="outside",
            ))
            fig_dr.add_hline(y=1.0, line_dash="dash", line_color="#6c757d",
                             annotation_text="BCR = 1.0", annotation_position="bottom right")
            fig_dr.update_layout(
                height=380, margin=dict(t=20, b=20, l=20, r=20),
                xaxis_title="Discount rate", yaxis_title="BCR", showlegend=False,
                **PLOTLY_TRANSPARENT,
            )
            st.plotly_chart(fig_dr, use_container_width=True)

        with sen2:
            st.subheader("Switching values (% change for BCR = 1.0)")
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
                    xaxis_title="% change required", showlegend=False,
                    **PLOTLY_TRANSPARENT,
                )
                st.plotly_chart(fig_sw, use_container_width=True)
            else:
                st.info("Insufficient data for switching values.")

    # --- Carbon value sensitivity ---
    with st.expander("Carbon values — BCR under each carbon value schedule", expanded=False):
        _carbon_sens = _r_sens.get("sensitivity_carbon", {})
        if _carbon_sens:
            _c_labels = list(_carbon_sens.keys())
            _c_bcrs = [_carbon_sens[l]["bcr"] for l in _c_labels]
            _c_fig = go.Figure(go.Bar(
                x=_c_labels, y=[b if b is not None else 0 for b in _c_bcrs],
                marker_color=["#0066CC" if _carbon_sens[l]["core"] else "#198754"
                              for l in _c_labels],
                text=[fmt_bcr(b) for b in _c_bcrs], textposition="outside",
            ))
            _c_fig.add_hline(y=1.0, line_dash="dash", line_color="#6c757d",
                             annotation_text="BCR = 1.0", annotation_position="top right")
            _c_fig.update_layout(
                yaxis_title="BCR", xaxis_title="Carbon value schedule",
                margin=dict(t=30, b=10), height=320, **PLOTLY_TRANSPARENT,
            )
            st.plotly_chart(_c_fig, use_container_width=True)

            _df_c = pd.DataFrame([{
                "Carbon values": _lbl,
                "PV benefits ($M)": _carbon_sens[_lbl]["pvb"],
                "NPV ($M)": _carbon_sens[_lbl]["npv"],
                "BCR": _carbon_sens[_lbl]["bcr"],
                "Core": _carbon_sens[_lbl]["core"],
            } for _lbl in _c_labels])

            def _highlight_carbon(row):
                styles = [""] * len(row)
                if row["Core"]:
                    styles = ["background-color: rgba(13, 110, 253, 0.1); font-weight: 700"] * len(row)
                return styles

            st.dataframe(
                _df_c.style.apply(_highlight_carbon, axis=1).format({
                    "PV benefits ($M)": "{:,.1f}", "NPV ($M)": "{:,.1f}", "BCR": fmt_bcr,
                }),
                use_container_width=True, hide_index=True,
                column_config={"Core": None},
            )
            st.caption(
                "Operating carbon (from the change in VKT) and upfront carbon are revalued at "
                "each schedule; other externalities are unchanged. Highlighted row = core "
                "result (NSW Carbon Values, central). All schedules are EPV 2026.1 Table 6.1 × "
                "Table 6.4, June 2026 $. For jointly funded projects of $100m or more report "
                "the National central BCR too."
            )
        else:
            st.info("No carbon sensitivity data available.")

    # --- Wider Economic Benefits (WEBs) Sensitivity ---
    with st.expander("Wider economic benefits — indicative uplift, not in the headline BCR", expanded=False):
        st.caption(
            "WEBs represent productivity gains not captured in conventional transport benefits "
            "(agglomeration, labour supply, imperfect competition). TfNSW and ATAP guidelines "
            "treat WEBs as additive to PV benefits — typically 10–20% of PV travel time savings "
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
            ("Very high — Major urban CBD access (30%)", 0.30),
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
                "Adjusted PV benefits ($M)": round(_adj_pvb, 1),
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
            "Adjusted PV benefits ($M)": "{:.1f}",
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
    with st.expander("Value of statistical life — fatal crash costs scaled", expanded=False):
        st.caption(
            "Scales only the fatal crash cost component of safety benefits "
            f"({PARAMS['safety_severity_share']['fatal']*100:.0f}% of blended safety PV by default). "
            "Serious injury, minor, and PDO components are held at base values. "
            "VSL: NSW value for NSW-funded projects, ATAP-based value for jointly funded "
            "(EPV 2026.1 Table 5.1, set by the funding basis in Setup)."
        )
        _vsl_sens = _r_sens.get("sensitivity_vsl", {})
        if _vsl_sens:
            _vsl_labels = list(_vsl_sens.keys())
            _vsl_bcrs = [_vsl_sens[l]["bcr"] for l in _vsl_labels]
            _vsl_fig = go.Figure()
            _vsl_fig.add_trace(go.Bar(
                x=_vsl_labels, y=[v if v is not None else 0 for v in _vsl_bcrs],
                marker_color=COLORS["safety"],
                text=[fmt_bcr(v) for v in _vsl_bcrs],
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
                    "PV benefits ($M)": round(_vv["pvb"], 1),
                    "NPV ($M)": round(_vv["npv"], 1),
                    "BCR": _vv["bcr"],
                })
            _df_vsl = pd.DataFrame(_vsl_rows)

            def _highlight_vsl(row):
                styles = [""] * len(row)
                if "Central" in row["VSL Scenario"]:
                    styles = ["background-color: rgba(220, 53, 69, 0.08); font-weight: 700"] * len(row)
                _bcr_idx = _df_vsl.columns.get_loc("BCR")
                if pd.notna(row["BCR"]):
                    styles[_bcr_idx] += ("; color: #198754; font-weight: 700" if row["BCR"] >= 1
                                         else "; color: #dc3545; font-weight: 700")
                return styles

            _styled_vsl = _df_vsl.style.apply(_highlight_vsl, axis=1).format({
                "VSL ($M)": "{:.2f}",
                "PV benefits ($M)": "{:.1f}",
                "NPV ($M)": "{:.1f}",
                "BCR": lambda b: fmt_bcr(None if pd.isna(b) else b),
            })
            st.dataframe(_styled_vsl, use_container_width=True, hide_index=True)
            st.caption(
                "Highlighted row = Central (base case) VSL. "
                "Only the fatal component of safety benefits is scaled; other severity classes are unchanged. "
                "Source: TfNSW EPV 2026.1 Table 5.1; ATAP T2 (2022) recommends ±30% VSL sensitivity."
            )
        else:
            st.info("No VSL sensitivity data available.")

    # --- First-Year Benefit Breakdown ---
    fy = _r_sens["first_year"]
    with st.expander("First-year benefits — each benefit line in the first year of operation", expanded=False):
        _fy_rows = [{"Benefit": label, "First year ($M)": round(fy.get(key, 0.0), 2)}
                    for key, label in TYPE_LABELS.items()]
        _fy_rows.append({"Benefit": "Total", "First year ($M)": round(fy.get("total", 0.0), 2)})
        st.dataframe(pd.DataFrame(_fy_rows), use_container_width=True, hide_index=True)

    # --- Monte Carlo Risk Analysis (advanced only) ---
    if show_advanced:
        with st.expander("Monte Carlo risk analysis — range of outcomes from uncertain inputs", expanded=False):
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
                            base_case_costs=st.session_state.base_case_costs,
                            annualisation=st.session_state.annualisation,
                            safety_vkt_data=_calc_safety_vkt,
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
                    st.subheader("NPV distribution ($M)")
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
                    st.subheader("BCR distribution")
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
                    st.subheader("Tornado chart — NPV sensitivity (P10/P90 of each input)")
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
