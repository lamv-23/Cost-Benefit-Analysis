"""
Transport Cost-Benefit Analysis Dashboard
Parameters based on TfNSW Economic Parameter Values (January 2025)
All monetary values in June 2024 prices (AUD)
"""

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
    page_title="Transport CBA Dashboard — TfNSW",
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
}

# Phase 0b: Vehicle type mapping — UI labels to PARAMS internal keys
# Note: Bus approximated as artic for VOC/air/noise externality rates
VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "artic"}

# Separate mapping for emission_cost (uses "bus" key, not "artic")
EMISSION_VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "bus"}

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


def _cagr_interpolate(v1: float, v2: float, y1: int, y2: int, eval_year: int) -> float:
    """CAGR-based interpolation/extrapolation between two modelling years.

    Mirrors the Excel formula: ((v2/v1)^(1/(y2-y1)))-1 applied as
    v1 * (v2/v1)^((eval_year-y1)/(y2-y1)).  Returns 0 if either value is 0.
    """
    if v1 == 0 or v2 == 0 or y2 == y1:
        return 0.0
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

            def _style_incr(val):
                if isinstance(val, (int, float)):
                    if val < 0:
                        return "background-color:rgba(220,53,69,0.12);color:#dc3545"
                    if val > 0:
                        return "background-color:rgba(25,135,84,0.12);color:#198754"
                return ""

            st.dataframe(
                incr_df.style.applymap(_style_incr).format("{:+.0f}"),
                use_container_width=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# CRASH MATRIX UI HELPER — Step 4
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# COST ENTRY UI HELPER — Step 5
# ─────────────────────────────────────────────────────────────────────────────

def render_cost_entry() -> None:
    """Render cost input forms per project case (Step 5).

    One expandable section per project case with capital costs (planning, land,
    construction, contingency %), recurrent costs (maintenance, operating), and
    residual value.  Updates ``st.session_state.cost_data`` in-place.
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

            cd["residual"] = st.number_input(
                "Residual Value ($M, at end of evaluation period)", min_value=0.0,
                value=float(cd["residual"]), step=0.1, key=f"cost_residual_{i}",
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
            if template_sheets & set(xl.sheet_names):
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

            # Detect year columns: 4-digit integers 2020-2100
            year_cols = [c for c in df.columns if c.isdigit() and 2020 <= int(c) <= 2100]
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

    # Capital and recurrent costs
    raw_cap = cost["cap_planning"] + cost["cap_land"] + cost["cap_construction"]
    total_capital = raw_cap * (1 + cost["contingency_pct"] / 100)
    annual_capital = total_capital / const_years if const_years > 0 else 0.0
    opex = cost["opex_maint"] + cost["opex_op"]
    residual = cost["residual"]

    modelling_years = base_traffic["years"]
    total_years = const_years + eval_period

    annual_costs: list = []
    annual_benefits: list = []
    benefits_by_type: dict = {k: [] for k in ("tts", "tts_Car", "tts_LCV", "tts_HCV", "tts_Bus", "reliability", "voc", "safety", "env", "active")}
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
        b_tts = b_rel = b_voc = b_safety = b_env = b_active = 0.0
        b_tts_by_vt: dict = {vt: 0.0 for vt in VTYPES}

        if y < const_years:
            cost_y = annual_capital
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
                vt_tts = annual_vht_saving * vtts_by_vtype[vt] / 1e6
                b_tts_by_vt[vt] = vt_tts
                b_tts += vt_tts

            b_rel = b_tts * _p["reliability_ratio"] * 0.3

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

            # ── Environmental: emission + air + noise per vtype × VKT Δ ────
            for vt in VTYPES:
                param_vt = VTYPE_MAP[vt]
                emit_vt = EMISSION_VTYPE_MAP[vt]
                emit_rate = _p["emission_cost"][ctx].get(emit_vt, 0.0)
                air_rate = _p["air_pollution"][ctx].get(param_vt, 0.0)
                noise_rate = _p["noise"][ctx].get(param_vt, 0.0)

                vkt_b = interpolate_modelling_years(modelling_years, base_traffic[vt]["vkt"], ey)
                vkt_p = interpolate_modelling_years(modelling_years, proj_traffic[vt]["vkt"], ey)
                vkt_delta = (vkt_b - vkt_p) * ann_factors[vt]
                b_env += vkt_delta * (emit_rate + air_rate + noise_rate) / 1e6

        benefit_y = b_tts + b_rel + b_voc + b_safety + b_env + b_active
        if y == total_years - 1:
            benefit_y += residual

        net = benefit_y - cost_y
        annual_costs.append(cost_y)
        annual_benefits.append(benefit_y)
        for k, v in zip(("tts", "reliability", "voc", "safety", "env", "active"),
                        (b_tts, b_rel, b_voc, b_safety, b_env, b_active)):
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
    fyrr = (annual_benefits[first_op] / total_capital * 100) if total_capital > 0 else 0.0

    pv_by_type = {
        t: sum(benefits_by_type[t][y] * discount_factor(dr, base_offset + y) for y in range(total_years))
        for t in benefits_by_type
    }

    sensitivity_dr = {}
    for r in [3, 4, 5, 7, 10, 12]:
        s_pvb = sum(annual_benefits[y] * discount_factor(r, base_offset + y) for y in range(total_years))
        s_pvc = sum(annual_costs[y] * discount_factor(r, base_offset + y) for y in range(total_years))
        sensitivity_dr[r] = {
            "pvb": s_pvb, "pvc": s_pvc,
            "npv": s_pvb - s_pvc,
            "bcr": s_pvb / s_pvc if s_pvc > 0 else 0.0,
        }

    switching = {}
    if pv_benefits > 0 and pv_costs > 0:
        switching["Total Benefits"] = -((pv_benefits - pv_costs) / pv_benefits) * 100
        switching["Total Costs"] = ((pv_benefits - pv_costs) / pv_costs) * 100
        for t, label in TYPE_LABELS.items():
            if pv_by_type.get(t, 0) > 0:
                switching[label] = -((pv_benefits - pv_costs) / pv_by_type[t]) * 100

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
        "fyrr": fyrr, "payback_year": payback_year, "total_capital": total_capital,
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
            t: benefits_by_type[t][first_op] for t in benefits_by_type
        } | {"total": annual_benefits[first_op]},
    }


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-CASE LOOP — Step 8
# ─────────────────────────────────────────────────────────────────────────────

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
            "", key=f"{key}_num",
            min_value=float(min_val), max_value=float(max_val), step=float(step),
            label_visibility="collapsed",
            on_change=_param_sync_num, args=(key,),
        )
    with col_sl:
        st.slider(
            "", key=f"{key}_sl",
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
    if "param_reliability_ratio" in ss:
        p["reliability_ratio"] = float(ss["param_reliability_ratio"])
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
        styled = styled.applymap(_colour_delta, subset=[col])

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


_init_session_state()


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — ALL INPUTS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Transport CBA")
    st.caption("TfNSW Economic Parameter Values (Jan 2025) · June 2024 prices")

    # ── Matrix Input Configuration (Step 2) ──────────────────────────────────
    st.markdown("### Modelling Configuration")

    # Number of project cases
    _n_input = st.number_input(
        "Number of Project Cases", min_value=1, max_value=5,
        value=st.session_state["n_project_cases"], step=1,
        key="n_project_cases_widget",
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
        if len(_parsed_years) >= 1 and _parsed_years != st.session_state["modelling_years"]:
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
    project_name = st.text_input("Project Name", value="Sample Road Upgrade")
    col1, col2 = st.columns(2)
    with col1:
        eval_period = st.number_input("Evaluation Period (years)", 1, 50, 30)
        discount_base_year = st.number_input("Discount Base Year", 2020, 2060, 2026,
            help="Calendar year used as Year 0 for discounting (PV anchor).")
        construction_start_year = st.number_input("Construction Start Year", 2020, 2060, 2026,
            help="Calendar year construction begins. Benefits start after the construction period.")
    with col2:
        const_years = st.number_input("Construction Period (years)", 1, 10, 3)
        discount_rate = st.number_input("Discount Rate (%)", 0.0, 20.0, 7.0, step=0.5)
    context = st.selectbox("Context", ["urban", "rural"], format_func=str.title)
    zero_growth_after_last_year = st.checkbox(
        "Zero growth after last modelling year",
        value=False,
        help="When checked, traffic volumes (and all benefits) are held flat at the last "
             "modelling year's values rather than extrapolating the trend.",
    )

    st.divider()

    # --- Capital Costs ---
    st.markdown("### Capital Costs ($M, undiscounted)")
    col1, col2 = st.columns(2)
    with col1:
        cap_planning = st.number_input("Planning & Design ($M)", 0.0, value=5.0, step=0.1)
        cap_construction = st.number_input("Construction ($M)", 0.0, value=120.0, step=1.0)
    with col2:
        cap_land = st.number_input("Land Acquisition ($M)", 0.0, value=10.0, step=0.1)
        contingency = st.number_input("Contingency (%)", 0.0, 100.0, 20.0, step=1.0)

    # --- Recurrent Costs ---
    st.markdown("### Recurrent Costs ($M/year)")
    col1, col2 = st.columns(2)
    with col1:
        opex_maint = st.number_input("Maintenance ($M/yr)", 0.0, value=1.5, step=0.1)
    with col2:
        opex_op = st.number_input("Operating ($M/yr)", 0.0, value=0.8, step=0.1)
    residual = st.number_input("Residual Value ($M)", 0.0, value=15.0, step=0.1)


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
    matrix_results = calculate_all_cases(
        inputs=_matrix_inputs,
        traffic_data=st.session_state.traffic_data,
        cost_data=st.session_state.cost_data,
        annualisation=st.session_state.annualisation,
        safety_vkt_data=st.session_state.safety_vkt_data,
        params=build_effective_params(),
    )
except Exception as _calc_err:
    matrix_results = {}
    if st.session_state.get("debug_mode"):
        st.error(f"Matrix calculation error: {_calc_err}")


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
# KPI METRICS — Step 10: multi-case aware
# ─────────────────────────────────────────────────────────────────────────────
_n_cases = st.session_state.n_project_cases

if matrix_results and _n_cases > 1:
    # Multi-case: one KPI column per project case
    _case_cols = st.columns(min(_n_cases, 4))
    for _i, _col in enumerate(_case_cols, 1):
        _mr = matrix_results.get(f"project_{_i}", {})
        _pb = f"{_mr['payback_year']} yrs" if _mr.get("payback_year") else "N/A"
        with _col:
            st.markdown(f"**Project {_i}**")
            st.metric("NPV", format_m(_mr.get("npv", 0)),
                      delta="Positive" if _mr.get("npv", 0) >= 0 else "Negative",
                      delta_color="normal" if _mr.get("npv", 0) >= 0 else "inverse")
            st.metric("BCR", f"{_mr.get('bcr', 0):.2f}",
                      delta="≥ 1.0" if _mr.get("bcr", 0) >= 1 else "< 1.0",
                      delta_color="normal" if _mr.get("bcr", 0) >= 1 else "inverse")
            st.metric("PV Benefits", format_m(_mr.get("pv_benefits", 0)))
            st.metric("PV Costs", format_m(_mr.get("pv_costs", 0)))
            st.metric("FYRR", f"{_mr.get('fyrr', 0):.1f}%")
            st.metric("Payback", _pb)
elif matrix_results:
    # Single project case
    _r_kpi = matrix_results["project_1"]
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.metric("Net Present Value", format_m(_r_kpi["npv"]),
                  delta="Positive" if _r_kpi["npv"] >= 0 else "Negative",
                  delta_color="normal" if _r_kpi["npv"] >= 0 else "inverse")
    with k2:
        st.metric("Benefit-Cost Ratio", f"{_r_kpi['bcr']:.2f}",
                  delta="Above 1.0" if _r_kpi["bcr"] >= 1 else "Below 1.0",
                  delta_color="normal" if _r_kpi["bcr"] >= 1 else "inverse")
    with k3:
        st.metric("PV Benefits", format_m(_r_kpi["pv_benefits"]))
    with k4:
        st.metric("PV Costs", format_m(_r_kpi["pv_costs"]))
    with k5:
        st.metric("First Year Rate of Return", f"{_r_kpi['fyrr']:.1f}%")
    with k6:
        pb = f"{_r_kpi['payback_year']} years" if _r_kpi["payback_year"] else "N/A"
        st.metric("Payback Period", pb)
else:
    st.info("Enter traffic data in the **Data Input** tab to see results.")

# ─────────────────────────────────────────────────────────────────────────────
# EXPORT BUTTON
# ─────────────────────────────────────────────────────────────────────────────
_export_r = matrix_results.get("project_1", {})
if _export_r:
    csv_data = generate_csv(_export_r, project_name)
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
tab_datainput, tab_dash, tab_cashflow, tab_sensitivity, tab_params = st.tabs(
    ["Data Input", "Dashboard", "Detailed Cashflow", "Sensitivity", "Parameters"]
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
            uploaded_file = st.file_uploader(
                "Drop file here",
                type=["csv", "xlsx"],
                label_visibility="collapsed",
            )
            if uploaded_file is not None:
                if parse_mode == "Template":
                    _handle_template_upload(uploaded_file)
                elif parse_mode == "Smart parse":
                    _smart_parse_upload(uploaded_file)
                else:
                    _render_user_mapping_upload(uploaded_file)

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

    # ── Sub-tabs: one per traffic metric + Crashes + Costs ────────────────
    sub_vht, sub_vkt, sub_stops, sub_demand, sub_safety, sub_costs = st.tabs(
        ["VHT", "VKT", "Stops", "Demand", "Safety $/VKT", "Costs"]
    )

    # ── VHT sub-tab ───────────────────────────────────────────────────────
    with sub_vht:
        st.caption(
            "Vehicle Hours Travelled per peak period (veh-hrs/peak period). "
            "Used directly for Travel Time Savings calculation. "
            "Speed = VKT / VHT (derived, not entered)."
        )
        render_traffic_matrix("vht", "veh-hrs / peak period")

    # ── VKT sub-tab ───────────────────────────────────────────────────────
    with sub_vkt:
        st.caption(
            "Vehicle Kilometres Travelled per peak period (veh-km/peak period). "
            "Used for VOC, emissions, air pollution, and noise calculations. "
            "Speed (km/h) = VKT ÷ VHT — shown as read-only in the VHT tab."
        )
        render_traffic_matrix("vkt", "veh-km / peak period")

    # ── Stops sub-tab ─────────────────────────────────────────────────────
    with sub_stops:
        st.caption("Vehicle stops per peak period (stops/peak period). Captured for reference.")
        render_traffic_matrix("stops", "stops / peak period")

    # ── Demand sub-tab ────────────────────────────────────────────────────
    with sub_demand:
        st.caption(
            "Person-trips per peak period (person-trips/peak period). "
            "Captured for reference; TTS is driven by VHT, not demand."
        )
        render_traffic_matrix("demand", "person-trips / peak period")

    # ── Safety $/VKT sub-tab ──────────────────────────────────────────────
    with sub_safety:
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

    # ── Costs sub-tab ─────────────────────────────────────────────────────
    with sub_costs:
        st.caption(
            "Capital and recurrent costs per project case ($M, undiscounted). "
            "Base Case has no project costs. Construction cost is spread evenly over "
            "the construction period defined in Project Details (sidebar)."
        )
        render_cost_entry()


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

    with chart1:
        st.subheader("Benefit Composition (PV $M)")
        pv = _r["pv_by_type"]
        labels_list, values_list, colors_list = [], [], []
        for t in ["tts", "reliability", "voc", "safety", "env", "active"]:
            if pv.get(t, 0) > 0:
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
        wf_values = [pv.get(t, 0) for t in TYPE_LABELS] + [
            _r["pv_benefits"], -_r["pv_costs"], _r["npv"]
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

    if view_mode == "Undiscounted":
        _bbt = _r_cf["benefits_by_type"]
        _tts_cols: dict = {}
        if tts_breakdown:
            _tts_cols = {
                "TTS — Car ($M)": [round(v, 3) for v in _bbt.get("tts_Car", [0.0] * _r_cf["total_years"])],
                "TTS — LCV ($M)": [round(v, 3) for v in _bbt.get("tts_LCV", [0.0] * _r_cf["total_years"])],
                "TTS — HCV ($M)": [round(v, 3) for v in _bbt.get("tts_HCV", [0.0] * _r_cf["total_years"])],
                "TTS — Bus ($M)": [round(v, 3) for v in _bbt.get("tts_Bus", [0.0] * _r_cf["total_years"])],
            }
        df_cf = pd.DataFrame({
            "Year": years_list,
            "Costs ($M)": [round(c, 3) for c in _r_cf["annual_costs"]],
            "Benefits ($M)": [round(b, 3) for b in _r_cf["annual_benefits"]],
            "TTS ($M)": [round(v, 3) for v in _bbt["tts"]],
            **_tts_cols,
            "Reliability ($M)": [round(v, 3) for v in _bbt["reliability"]],
            "VOC ($M)": [round(v, 3) for v in _bbt["voc"]],
            "Safety ($M)": [round(v, 3) for v in _bbt["safety"]],
            "Environmental ($M)": [round(v, 3) for v in _bbt["env"]],
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
    st.download_button(
        f"Download {view_mode} Cashflow CSV",
        cf_csv,
        file_name=f"cashflow-{view_mode.lower()}{_cf_filename_suffix}.csv",
        mime="text/csv",
        key="dl_cashflow",
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
    for r_val in sorted(_r_sens["sensitivity_dr"].keys()):
        v = _r_sens["sensitivity_dr"][r_val]
        rows.append({
            "Scenario": f"Discount Rate {r_val}%",
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
    fy = _r_sens["first_year"]
    fy_cols = st.columns(7)
    for i, (key, label) in enumerate(TYPE_LABELS.items()):
        with fy_cols[i]:
            st.metric(label, f"${fy[key]:.2f}M")
    with fy_cols[6]:
        st.metric("Total", f"${fy['total']:.2f}M")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: PARAMETERS (EDITABLE)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_params:
    st.markdown('<div class="section-header">Economic Parameters</div>', unsafe_allow_html=True)
    st.caption("Edit values below. Changes take effect immediately in all calculations. "
               "Source: TfNSW Economic Parameter Values (January 2025), June 2024 prices.")

    if st.button("Reset All to Defaults", key="reset_params"):
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

    # ── Reliability Ratio ────────────────────────────────────────────────────
    with st.expander("Reliability Ratio"):
        param_editor(
            label="Reliability Ratio (of VTTS)",
            key="param_reliability_ratio",
            default=PARAMS["reliability_ratio"],
            min_val=0.0, max_val=2.0, step=0.05,
            unit="ratio", source="TfNSW EPV Jan 2025, §4.3",
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

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Transport CBA Dashboard · Parameters based on TfNSW Economic Parameter Values (Jan 2025) · For practitioner use · Not for public distribution")
