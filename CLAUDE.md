# CLAUDE.md — Cost-Benefit Analysis Repository Guide

## Project Overview

A Transport Cost-Benefit Analysis (CBA) dashboard implementing the TfNSW (Transport for New South Wales) Economic Parameter Values framework (January 2025, June 2024 prices in AUD). The tool supports multi-vehicle-type, multi-project-case analysis with discounting, sensitivity analysis, and flexible data import/export.

Teams use it to appraise road upgrade projects whose results go to assurance reviews, so it follows the TfNSW CBA Guide (August 2024) and NSW Treasury TPG23-08: P50/P90 capital, base case and recurrent costs, upfront carbon, and the TfNSW required sensitivity tests.

The app is a Streamlit app (`app.py`) over a Streamlit-free calculation engine (`cba_engine.py`). The earlier standalone HTML/JavaScript version has been removed.

---

## Repository Structure

```
Cost-Benefit-Analysis/
├── app.py                          # Streamlit UI, session state, caching, charts
├── cba_engine.py                   # Calculation engine (no streamlit import)
├── requirements.txt                # Python dependencies
├── requirements-dev.txt            # pytest (test runner only)
├── plan.md                         # Detailed implementation roadmap
├── tests/
│   ├── conftest.py                 # Fixture builders (make_case_traffic, fixture_costs)
│   ├── test_engine.py              # Unit tests for cba_engine
│   └── test_app_smoke.py           # Headless AppTest runs of app.py
├── docs/superpowers/               # Design specs and plans
├── column_mapper_component/
│   └── index.html                  # Drag-and-drop column mapper (Streamlit custom component)
└── .gitignore
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend/UI | Python 3, Streamlit ≥ 1.30.0 |
| Data | Pandas ≥ 2.0.0 |
| Charts | Plotly ≥ 5.18.0 |
| File I/O | openpyxl ≥ 3.1.0 (Excel templates) |
| Tests | pytest 8.4.2 (`requirements-dev.txt`), Streamlit `AppTest` |

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Streamlit app
streamlit run app.py
```

There is no build step. Code must run on Python 3.9 and 3.12.

---

## Architecture

### `cba_engine.py` (no `streamlit` import)

| Area | Names |
|------|-------|
| Parameters and maps | `PARAMS`, `VTYPE_MAP`, `VTYPES`, `TYPE_LABELS` (benefit and cost line labels) |
| Data factories | `make_traffic_case()`, `make_traffic_data()`, `make_cost_data()`, `make_base_case_costs()` |
| Cost schedule | `clean_row()`, `fit_cost_rows()`, `build_cost_schedule()` |
| Calculation | `calculate_matrix()` (one option vs base), `calculate_all_cases()` |
| Sensitivity | `run_required_sensitivities()` (the 17 TfNSW rows), `run_monte_carlo()` |
| Reporting | `appraisal_summary()`, `generate_csv()` |
| Project files | `validate_project_file()` (rejects files without the current `cost_format`) |

### `app.py`

Streamlit UI: sidebar, tabs, session state, `st.cache_data` wrappers (including `_cached_required_sensitivities`) and Plotly charts. Imports everything above from `cba_engine`. Put calculation logic in `cba_engine.py`, not here.

### Session State Convention

Session state keys follow these patterns:
- `st.session_state["traffic_data"]` — nested dict keyed by case → vehicle type → metric
- `st.session_state["cost_data"]` — dict keyed by project case → yearly cost schedule (see Cost Data)
- `st.session_state["base_case_costs"]` — shared base case recurrent cost row (all options)
- `st.session_state["params_override"]` — user-edited parameter overrides merged via `build_effective_params()`
- `st.session_state["results"]` — calculation outputs keyed by case

---

## Data Structures

### Traffic Case
```python
{
  "years": [2026, 2031, 2041, 2056],   # modelling years
  "Car": {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
  "LCV": {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
  "HCV": {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
  "Bus": {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]}
}
```

### Cost Data (per project case)

All costs are real June 2024 dollars, entered as yearly cashflows (never spread automatically). `C` = construction years, `E` = appraisal period (counted from opening).

```python
{
  "capex_base": {"planning": [...C], "land": [...C], "construction": [...C]},  # $M, no contingency
  "contingency_p50": [...C],         # $M by year, takes base to P50 (core result)
  "contingency_p90": [...C],         # $M by year, takes base to P90 (sensitivity only)
  "recurrent": [...C + E],           # $M by year: operations, maintenance, renewals
  "upfront_carbon_t": float,         # tCO2e, spread by P50 capital, valued at the carbon price
  "outturn_p50_nominal": float | None,  # nominal $M, reporting only, never used in a calculation
  "outturn_p90_nominal": float | None,  # blank shows "not entered"
  "construction_disbenefit_annual": float, "construction_asset_life": int, "residual": float,
  "walk_pkm_day": float, "cycle_pkm_day": float,
  "generated_demand_pct_global": float, "generated_demand_pct_override": {vtype: None},
}
```

Base case: `base_case_costs = {"recurrent": [...C + E]}`, shared by all options. Avoided base case costs are a benefit; project capital and recurrent costs are the costs. Saved projects carry `cost_format` (`COST_FORMAT_VERSION`); older files are refused, not migrated.

### Calculation Output (per case)
```python
{
  "npv": float, "bcr": float,
  "pv_benefits": float, "pv_costs": float,
  "pv_capital": float, "pv_recurrent": float,
  "annual_capital": list, "annual_recurrent": list, "annual_costs": list,
  "annual_benefits": list, "annual_net": list,
  "disc_net": list, "cum_disc_net": list, "total_years": int,
  "pv_by_type": {key: float for key in TYPE_LABELS},
  "benefits_by_type": {key: [yearly]},   # also tts_<vtype>
  "sensitivity_carbon": {...}, "sensitivity_vsl": {...},
  "switching": {...}
}
```
The TfNSW required sensitivity table is separate: `run_required_sensitivities()` returns 17 rows `{"test", "pvb", "pvc", "npv", "bcr", "central"}`.

---

## Naming Conventions

### Vehicle Types
| User-facing (VTYPES) | Internal PARAMS key |
|----------------------|---------------------|
| `Car` | `car` |
| `LCV` | `lgv` |
| `HCV` | `rigid` / `artic` |
| `Bus` | `bus` |

Mapping is defined in `VTYPE_MAP` constant.

### Case Keys
- `"base_case"` — always present
- `"project_1"` through `"project_5"` — up to 5 project alternatives

### Benefit Types
`tts`, `reliability`, `voc`, `safety`, `env`, `active`, plus the lines `avoided_costs`, `upfront_carbon` and `construction_disruption` (disbenefit) and `residual`. Labels are in `TYPE_LABELS`.

### Context
`"urban"` or `"rural"` — affects VTTS and some cost rates

---

## Calculation Conventions

| Concept | Convention |
|---------|-----------|
| **Speed** | Derived: `speed = VKT / VHT` (never directly input) |
| **Annualisation** | Peak-period × expansion_factor × days_per_year (per vehicle type) |
| **Year interpolation** | CAGR: `v1 × (v2/v1)^((eval_year − y1) / (y2 − y1))` |
| **Discounting** | Start-of-year convention: `1 / (1 + rate/100)^year` |
| **TTS** | From VHT delta × occupancy × VTTS (VHT only, not VKT) |
| **VOC** | Speed-dependent rates, interpolated from lookup tables |
| **Safety** | Per-VKT crash cost rates ($/VKT per vehicle type, per case) |
| **Environment** | Combined emission_cost + air_pollution + noise per VKT delta |
| **Benefits** | All incremental: project case minus base case |

---

## UI Patterns

- **Sidebar**: project name, modelling years, costs, discount rate, annualisation
- **Tabs**: Data Input → Dashboard → Cashflow → Sensitivity → Parameters
- Data entry via `st.data_editor` (supports paste-from-Excel)
- Parameters tab: sliders synced with number inputs via session state callbacks
- KPI cards: `st.metric()` in multi-column layout for case comparison
- Charts: Plotly with transparent background for Streamlit theme compatibility

### Color Palette (benefit types)
```
tts      #0d6efd  (blue)
voc      #fd7e14  (orange)
safety   #dc3545  (red)
env      #198754  (green)
active   #6f42c1  (purple)
avoided_costs           #20c997
upfront_carbon          #6c757d
construction_disruption #adb5bd
residual                #795548
```

---

## File Import/Export

Three upload modes:
1. **Template** — pre-formatted openpyxl Excel (one sheet per metric: VHT, VKT, Stops, Demand, Crashes)
2. **Smart Parse** — auto-detect headers; uses `_auto_match_vtypes()`, `_auto_match_years()`, `_auto_match_cases()`
3. **User Mapping** — drag-and-drop column mapper (Streamlit custom component in `column_mapper_component/`)

Export: CSV results download (appraisal summary, itemised PV, required sensitivity tests, yearly cashflow), Excel template generation.

---

## Parameters System

- `PARAMS` dict holds immutable defaults (TfNSW Jan 2025 values)
- User edits in Parameters tab are stored as overrides in `st.session_state`
- `build_effective_params()` merges overrides into a copy of `PARAMS` at calculation time
- Never mutate `PARAMS` directly

---

## Testing

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests -q
```

- `tests/test_engine.py` — unit tests of `cba_engine` (cost schedule, PV lines, required sensitivity rows, summary, CSV, project-file validation).
- `tests/test_app_smoke.py` — headless `AppTest` runs of `app.py`: load sample (`confirm_load_sample` checkbox, then the "Load Sample Data" button), change periods, two options, save/load, sensitivity table, dashboard summary. Use `AppTest.from_file("app.py", default_timeout=300)`.
- Startup check: `streamlit run app.py` must load without errors.
- Manual checks in `plan.md` still apply for new calculation features (unit chains for TTS, VOC, CO₂; CAGR interpolation).

---

## Commit Conventions

Follow `type: description` format:
- `feat:` new feature
- `fix:` bug fix
- `refactor:` code restructure without behaviour change
- `docs:` documentation only

Examples from history:
```
feat: per-vehicle-type annualisation factor AND days per year
fix: switch discounting from mid-year to start-of-year convention
refactor: extract calculate_matrix into standalone function
```

---

## Key Files to Understand First

1. **`cba_engine.py`** — all calculation, sensitivity and CSV logic
2. **`app.py`** — UI and session state; read after the engine
3. **`docs/superpowers/specs/2026-10-26-tfnsw-compliance-design.md`** — design decisions behind the cost schedule and required sensitivity table
4. **`plan.md`** — implementation roadmap; consult before adding features to avoid conflicts

---

## Common Pitfalls

- **Do not mutate `PARAMS`** — always use `build_effective_params()` copy
- **Speed is always derived** (`VKT/VHT`), never accept speed as a direct input
- **CAGR interpolation, not linear** — use the geometric interpolation formula for year-by-year expansion
- **Discounting is start-of-year** — discount factor = `1/(1+r)^year`, not mid-year
- **Vehicle type mapping** — user sees `Car/LCV/HCV/Bus`; `PARAMS` uses `car/lgv/rigid/artic`
- **Benefits are incremental** — always project minus base; never absolute values
- **Costs are real** — the nominal outturn fields are for reporting only; never feed them into a calculation
- **Contingency once** — P50 capital is base rows plus the P50 contingency row; do not add a contingency percentage on top
- **Avoided base case costs once** — they come from the base case recurrent row only
- **Tests** — run `python3 -m pytest tests -q` before committing; keep `cba_engine.py` free of `streamlit` imports
