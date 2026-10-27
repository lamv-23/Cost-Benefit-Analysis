# CLAUDE.md — Cost-Benefit Analysis Repository Guide

## Project Overview

A Transport Cost-Benefit Analysis (CBA) dashboard implementing the TfNSW (Transport for New South Wales) Economic Parameter Values 2026.1 (July 2026, June 2026 prices in AUD). The tool supports multi-vehicle-type, multi-project-case analysis with discounting, sensitivity analysis, and flexible data import/export.

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
| Parameters | `PARAMS`, `CARBON_VALUES`, `carbon_value()`, `crash_cost_per_vkt()`, `PRICE_YEAR`/`PRICE_LABEL`, `VTYPES`, `TYPE_LABELS` (benefit and cost line labels) |
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

All costs are real June 2026 dollars (`PRICE_LABEL`), entered as yearly cashflows (never spread automatically). `C` = construction years, `E` = appraisal period (counted from opening).

```python
{
  "capex_base": {"planning": [...C], "land": [...C], "construction": [...C]},  # $M, no contingency
  "contingency_p50": [...C],         # $M by year, takes base to P50 (core result)
  "contingency_p90": [...C],         # $M by year, takes base to P90 (sensitivity only)
  "recurrent": [...C + E],           # $M by year: operations, maintenance, renewals
  "upfront_carbon_t": float,         # tCO2e, spread by P50 capital, valued at the NSW carbon value for each year
  "outturn_p50_nominal": float | None,  # nominal $M, reporting only, never used in a calculation
  "outturn_p90_nominal": float | None,  # blank shows "not entered"
  "construction_disbenefit_annual": float, "construction_asset_life": int, "residual": float,
  "walk_pkm_day": float, "cycle_pkm_day": float,
  "generated_demand_pct_global": float, "generated_demand_pct_override": {vtype: None},
}
```

Base case: `base_case_costs = {"recurrent": [...C + E]}`, shared by all options. Recurrent costs are net (option − base, scaled in the cost tests): a net increase in PV terms is a cost (`pv_recurrent`), a net saving is the `recurrent_savings` benefit (TfNSW CBA Guide §6.8). Capital is the other cost. Saved projects carry `cost_format` (`COST_FORMAT_VERSION`); older files are refused, not migrated.

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
`PARAMS` is keyed by the user-facing types `Car`, `LCV`, `HCV`, `Bus` (no mapping). Each is an
EPV 2026.1 vehicle class or a vehicle-mix-weighted group: Car = medium car (VOC) / car; LCV =
courier van utility + 4WD; HCV = all rigid, articulated and combination trucks (HV); Bus = heavy
bus. Weights are EPV Table 3.19.

### Case Keys
- `"base_case"` — always present
- `"project_1"` through `"project_5"` — up to 5 options; shown as "Option 1"… via `case_label()` / `case_labels()` (keys and saved files keep `project_N`; template import accepts "Option N" and older "Project N")

### Benefit Types
`tts`, `reliability` (proxy, switchable), `voc`, `safety`, `env`, `road_damage` (switchable), `active`, plus the lines `recurrent_savings`, `upfront_carbon` and `construction_disruption` (disbenefits) and `residual`. Labels are in `TYPE_LABELS`.

### Context
`"urban"` or `"rural"` — affects VTTS and some cost rates

---

## Calculation Conventions

| Concept | Convention |
|---------|-----------|
| **Speed** | Derived: `speed = VKT / VHT` (never directly input) |
| **Annualisation** | Peak-period × expansion_factor × days_per_year (per vehicle type) |
| **Year interpolation** | CAGR: `v1 × (v2/v1)^((eval_year − y1) / (y2 − y1))`; linear (clamped ≥ 0) when either endpoint is 0 |
| **Disbenefits** | Never clamp per-vehicle-type benefits at 0 — a slower/costlier project is a negative benefit |
| **Rule-of-Half** | Halves only the generated-demand share of TTS, reliability and VOC; safety and environment use the full VKT change |
| **Discount rates** | 5% central; required sensitivity at 3%, 4% (federal PPR) and 7% (TfNSW CBA Guide Aug 2024 / TPG23-08) |
| **Discounting** | Start-of-year convention: `1 / (1 + rate/100)^year` |
| **TTS** | VHT delta × EPV value per vehicle-hour (`vtt_vehicle_hr`, Tables 2.2/2.3; includes occupancy, business share, freight) |
| **VOC** | Speed-dependent $/km from `voc[model][vtype]`: urban `stop_start` or `freeway` (Setup), rural uses `rural` (freeway model, regional mix) |
| **Safety** | Per-VKT crash cost rates ($/VKT per vehicle type, per case) |
| **Environment** | Operating carbon (`carbon_t_per_vkt` × carbon value for the year) + other externalities (`externality_cents_vkt`) per VKT delta |
| **Benefits** | All incremental: project case minus base case |

---

## UI Patterns

- **Sidebar**: project name, save/open project file, load sample — nothing else. Periods, discount rate, context, annualisation and benefit methods live in **Inputs → Setup**
- **Run order**: sidebar → Inputs tab (Setup, Traffic, Costs) → title (into `_title_slot`) → calculation → Save button (into `_save_slot`) → Parameters → About → empty-state check → Results → Cashflow → Sensitivity. Anything reading cost/traffic edits must come after Inputs. The empty-state check calls `st.stop()` when nothing is entered (`_has_inputs()`) or the calculation failed, so Parameters and About are drawn before it
- **Widget keys set by code** (`_load_sample_data`, project load, `_init_session_state` write-back) must be set before those widgets render: the project name box is filled after the uploader via `_name_slot`; both sample buttons (sidebar and Results empty state) use the `_request_sample` callback, which sets `_sample_requested`, handled at the top of the script (it also sets the name to "Sample Road Upgrade" and un-ticks `confirm_load_sample`; a new session is "Untitled project"); never call `_init_session_state()` mid-run
- **Restorable widgets**: use `key=` with no `value=`/`index=`, and set the default in `_init_session_state` (written back every run so an early `st.rerun()` can't reset it); never assign a widget's key after it renders
- **File uploader** returns the file on every run — apply each upload once (guarded by `_loaded_project_id` / `file_id`)
- **Tabs**: Inputs (sub-tabs 1 · Setup / 2 · Traffic / 3 · Costs) → Results → Cashflow → Sensitivity → Parameters → About. Main tabs are pill-styled via CSS on `div[data-baseweb="tab-list"]`; sub-tabs inside a `tab-panel` are plain underlined; a third level (Traffic: VHT / VKT / Demand / Crashes / Safety rates / Benefit assumptions; Costs: Capital and other / Recurrent by year) is styled as small segmented buttons. Tabs keep long inputs to one screen; every tab's content still runs each rerun, so edits persist
- **Explanations**: one plain sentence (`st.caption`) per tab and section; longer detail goes in `help=` tooltips or collapsed expanders
- Data entry via `st.data_editor` (supports paste-from-Excel)
- Parameters tab: one editable table per group via `param_table()`; its `on_change` callback writes `param_*` keys (the tab renders after the calculation), and table keys carry `_ptbl_ver`, bumped on edit, reset and project load so tables redraw from session values. Saves keep only changed `param_*` values (`_is_param_value_key`), not old `_num`/`_sl` widget keys, so opening a project clears all overrides before applying the file's
- Generated demand and active transport inputs are stored in `cost_data` but shown on Inputs → Traffic → Benefit assumptions (`render_benefit_assumptions()`)
- Recurrent costs: one `st.data_editor` with a row per year and a column per case (base case + options), tall enough to show every year; paste a column from Excel
- Traffic change tables (Option − Base) end with a Total row; for VHT and VKT a reduction is green (improvement); demand is uncoloured. There is no traffic summary on Results
- Pinned Streamlit 1.47.1 does not accept `width="stretch"` on `st.dataframe`/`st.data_editor`; keep `use_container_width=True` until the pin is raised (the deprecation warnings only appear on newer local installs)
- Result cards: NPV and BCR only (`st.metric()`), at the top of the Results tab; two options per row when comparing. IRR/FYRR/payback are still computed by the engine but not shown as cards
- Results charts: one horizontal NPV waterfall (green adds, red subtracts, blue totals; lines that are exactly zero are named in a caption; bar labels use `signed_m`, which switches to $B like `format_m`), then annual net cashflow and cumulative discounted net benefits. Benefit-type colours are not used on Results
- Labels are sentence case everywhere (widgets, headings, chart titles, table columns, `TYPE_LABELS`); case names stay "Base Case" / "Option N"
- Cashflow table: Net follows Benefits and Year is pinned, so both stay in view; Save project is disabled until `_has_inputs()`
- Sensitivity: the TfNSW required test table is shown; every other analysis is a collapsed expander
- Charts: Plotly with transparent background for Streamlit theme compatibility

### Color Palette (benefit types)
```
tts      #0d6efd  (blue)
voc      #fd7e14  (orange)
safety   #dc3545  (red)
env      #198754  (green)
active   #6f42c1  (purple)
recurrent_savings       #20c997
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

- `PARAMS` dict holds immutable defaults (TfNSW EPV 2026.1, June 2026 prices; each entry cites its table). Values were extracted from the EPV Excel tool, which is not in the repo
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
- `tests/test_app_smoke.py` — headless `AppTest` runs of `app.py`: load sample (`confirm_load_sample` checkbox, then `at.button(key="sidebar_load_sample")`; both sample buttons are labelled "Load sample project", so find them by key), change periods, two options, save/load, sensitivity table, results summary, empty-state sample button. Use `AppTest.from_file("app.py", default_timeout=300)`.
- AppTest can't drive uploads/downloads: use `_capture_saves()` / `_open_in_fresh_app()` in `tests/test_app_smoke.py` (they monkeypatch `streamlit.download_button` / `file_uploader`)
- Startup check: `streamlit run app.py` must load without errors.
- Manual checks in `plan.md` still apply for new calculation features (unit chains for TTS, VOC, CO₂; CAGR interpolation).

---

## Deployment, Branches & Environment

- `claude/complete-cba-dashboard-hBs4G` is the default branch and **deploys to Streamlit Cloud on push** — do feature work on a separate branch; merge/push only when the user says to
- Push as GitHub account `lamv-23` (repo owner); a 403 on push means the wrong account is active — run `gh auth switch --user lamv-23`
- `runtime.txt` pins Python 3.12 on Cloud; local is 3.9 — keep `from __future__ import annotations` in `cba_engine.py`
- Shell is zsh: write `"${REV}:app.py"` not `$REV:app.py` (`:a` is a zsh modifier), and quote `'==='` in `echo`

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
- **Price year** — everything is June 2026; saved projects carry `price_year` (missing = 2024). Opening another price year sets `_price_year_pending`; the Costs tab offers `index_costs()` by CPI Sydney (`CPI_JUNE_2024_TO_2026`) and parameter overrides from that file are dropped
- **Benefits are incremental** — always project minus base; never absolute values
- **Costs are real** — the nominal outturn fields are for reporting only; never feed them into a calculation
- **Contingency once** — P50 capital is base rows plus the P50 contingency row; do not add a contingency percentage on top
- **Recurrent costs are net** — option minus base case; never put the base case row in benefits as well
- **Carbon** — operating and upfront carbon use `carbon_value("nsw", "central", year)` (`CARBON_VALUES`: EPV Table 6.1 FY2026 value × Table 6.4 factors, June 2026 $; NSW central/high, National central/low); `bcr_national_carbon` and the carbon sensitivity rows revalue the net tonnes (`annual_carbon_t`)
- **BCR is `None`** when PV costs ≤ 0 (`benefit_cost_ratio`); display with `fmt_bcr` ("–"), never format it as a float directly
- **Residual value** is discounted from the end of the final year (exponent + 1); any PV of the benefit rows must treat the residual row that way
- **Defaults** — `zero_growth_after_last_year` True; `include_reliability` and `include_road_damage` True; safety rates are always per case (`safety_vkt_data`), set from each case's road type (`sv_road_<case>`: urban/rural × divided/single → `crash_cost_per_vkt`, or `custom`) and the Setup `funding` basis (`nsw`/`joint`, also picks the VSL); old files keep their rates as `custom`
- **Road damage** — `road_damage_cents_vkt` is EPV 2026.1 Table 8.1 × `road_damage_maintenance_share` (0.46)
- **Stop VOC** — `include_stop_voc` (default False) adds change in stops × `voc_per_stop` (Table 3.14) to the VOC line; off by default because the speed-based VOC models already reflect typical stopping
- **Active transport** — health rate on all new km, plus `active_car_savings` (Table 7.1, former car users) on each option's `active_car_share_pct`; no travel time value (TfNSW)
- **Asset lives** — `ASSET_LIVES` (Table 12.1); the Costs picker sets `construction_asset_life` to the midpoint via a callback that drops the `cost_asset_life_<i>` widget key
- **Tests** — run `python3 -m pytest tests -q` before committing; keep `cba_engine.py` free of `streamlit` imports
