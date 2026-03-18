# Plan: Restructure CBA Dashboard — Matrix Input UI (Streamlit)

## TL;DR
Replace the current sidebar scalar inputs with a **main-section tabular data entry system** in `app.py`. Users enter VHT/VKT/Stops/Demand by vehicle type (Car, LCV, HCV, Bus) × custom modelling years, for a base case + up to 5 project cases. The UI shows absolute values per case and auto-computes incremental benefits (Project − Base). Crash data and costs also move to per-project-case matrix format. Three input methods: manual `st.data_editor`, clipboard paste, and file upload (with template/smart-parse/user-mapping).

## User Decisions
- **Scope**: Streamlit (`app.py`) only — JS web app unchanged
- **Data granularity**: Full matrix (VHT, VKT, Stops, Demand × 4 vehicle types × custom years)
- **Project cases**: Base case + up to 5 project options
- **Time periods**: Custom modelling years defined by user
- **Input methods**: Manual entry, paste from clipboard, CSV/Excel upload (all 3 parse modes)
- **Crash data**: Full base/project matrix by severity
- **Costs**: Per project case, in main section
- **Vehicle types**: Car, LCV, HCV, Bus

---

## Phase 0: Units Audit & Corrections

### Complete unit chain for every benefit type

| Benefit | Input units | PARAM units | Conversion | Output units |
|---|---|---|---|---|
| **TTS** | VHT_peak (veh-hrs/period) | VTTS $/person-hr (user-editable) | VHT_peak × expansion × days × occupancy[vtype] × VTTS_weighted / 1e6 | $M/year |
| **Reliability** | — derived | reliability_ratio 0–1 (user-editable) | annual_tts × reliability_ratio × 0.3 | $M/year |
| **VOC** | VKT_peak (veh-km/period) | VOC $/veh-km by speed (user-editable table) | (VKT_base × VOC_spd_base − VKT_proj × VOC_spd_proj) × expansion × days / 1e6 | $M/year |
| **CO₂/emissions** | VKT_peak (veh-km/period) | `emission_cost` $/veh-km per vtype (user-editable; combines emission factor × carbon price) | VKT_Δ_annual × emission_cost[vtype] / 1e6 | $M/year |
| **Air pollution** | VKT_peak (veh-km/period) | `air_pollution` $/veh-km per vtype (user-editable) | VKT_Δ_annual × air_pollution[vtype] / 1e6 | $M/year |
| **Noise** | VKT_peak (veh-km/period) | `noise` $/veh-km per vtype (user-editable) | VKT_Δ_annual × noise[vtype] / 1e6 | $M/year |
| **Safety** | crash counts/year per severity (base & project) | `crash_costs` $/crash per severity (user-editable) | (base − project) × cost / 1e6 | $M/year |
| **Active transport** | person-km/day (daily, not peak) | `health_benefits` $/person-km (user-editable) | person-km/day × days × rate / 1e6 | $M/year |
| **Costs** | $M (undiscounted) | — | capital / const_years per yr; opex unchanged | $M/year |

### Derived quantities (never input, always computed & displayed)
- **Speed** = VKT_peak / VHT_peak (km/h) — show as read-only per vehicle type per year
- **Annual VHT** = VHT_peak × expansion_factor × days_per_year (vehicle-hours/year)
- **Annual VKT** = VKT_peak × expansion_factor × days_per_year (vehicle-km/year)

### Issues found in current engine
1. **CO₂ emission factors missing** — PARAMS has `carbon_per_tonne` ($123/tCO₂e) but no emission factors (tCO₂e/veh-km per vehicle type). Currently uses a direct user-input "annual CO₂ reduction (tonnes)" which bypasses VKT. New VKT-based approach requires adding emission factors to PARAMS. Must source from TfNSW EPV Jan 2025 or NTC CO₂ emission factors.
2. **Bus not in PARAMS VOC/air/noise tables** — Current PARAMS has car, lgv, rigid, artic. New vehicle type "Bus" has no direct equivalent. Mapping needed: Car→car, LCV→lgv, HCV→rigid, Bus→artic (or bus-specific rates if available). Must document this mapping explicitly.
3. **Occupancy is global** — VTTS requires person-hours, which requires occupancy per vehicle type. Current single occupancy (1.4) is only valid for cars. New defaults needed: Car=1.4, LCV=1.0, HCV=1.0, Bus=45 (seated capacity, or a factor reflecting actual loading). Must make occupancy per vehicle type a user-editable parameter (shown in sidebar).
4. **VOC formula change** — Old: `AADT × trip_len × (VOC_base_speed − VOC_proj_speed)`. New: `VKT_base_annual × VOC(speed_base) − VKT_proj_annual × VOC(speed_proj)`. This is more correct because VKT can differ between base and project cases (e.g. diversion).
5. **Active transport annualisation** — Unclear if walk_km/cycle_km inputs are peak-period or daily. Should be daily (or labelled clearly). Keep as daily input with explicit "× days_per_year" shown.

### Step 0a: Add emission cost parameters to PARAMS
- Replace the raw CO₂ approach with a single **emission cost per vehicle-km** ($/vehicle-km) per vehicle type, combining emission factor × carbon price into one editable rate
- Add to PARAMS: `"emission_cost": {"urban": {"car": 0.023, "lgv": 0.027, "rigid": 0.071, "bus": 0.101}, "rural": {"car": 0.007, "lgv": 0.009, "rigid": 0.022, "bus": 0.032}}` — derived from NTC fleet-average emission factors × $123/tCO₂e (June 2024)
- Keep `air_pollution` and `noise` as separate existing PARAMS (retain breakdown visibility); add `emission_cost` as a new component
- Environmental benefit per vtype per year = VKT_Δ × (emission_cost + air_pollution + noise) / 1e6

### Step 0b: Add vehicle type mapping constant
- Add `VTYPE_MAP = {"Car": "car", "LCV": "lgv", "HCV": "rigid", "Bus": "artic"}` 
- Document the approximation (Bus ≈ artic for externality rates) prominently in UI and Parameters tab

### Step 0c: Define occupancy per vehicle type
- Add to PARAMS: `"occupancy": {"Car": 1.4, "LCV": 1.0, "HCV": 1.0, "Bus": 45.0}` 
- User-editable in sidebar (with slider: Car 1.0–2.5, LCV 1.0–1.5, HCV 1.0, Bus 10–80)

### Step 0d: Unit labels on every input and PARAMS display
- Every `st.number_input` label includes unit in brackets, e.g. `"VHT (veh-hrs/peak period)"`
- Every PARAMS reference table has a "Unit" column
- All chart y-axis labels and table headers show units
- `st.caption()` beside annualisation inputs showing the formula: `Annual VHT = Peak VHT × {expansion} × {days} days`

### Step 0e: Make ALL economic parameters user-editable (Parameters tab redesign)
The "Parameters" tab becomes a fully interactive editor, not just a read-only reference. Design:

**Widget pattern** for each parameter — use synchronized `number_input` + `st.slider` via `st.session_state`:
```python
# Render a param widget with linked number input + slider
def param_editor(label, key, default, min_val, max_val, step, unit, source):
    col_label, col_input, col_slider = st.columns([2, 1, 2])
    with col_label:
        st.write(f"**{label}** `{unit}`")
        st.caption(source)
    with col_input:
        val = st.number_input("", key=f"{key}_num", value=st.session_state.get(key, default), 
                              min_value=min_val, max_value=max_val, step=step, label_visibility="collapsed")
        st.session_state[key] = val
    with col_slider:
        val2 = st.slider("", key=f"{key}_sl", value=st.session_state.get(key, default),
                         min_value=min_val, max_value=max_val, step=step, label_visibility="collapsed")
        if val2 != val:
            st.session_state[key] = val2
            st.rerun()
    return st.session_state[key]
```

**Parameters to expose with slider ranges:**

| Parameter | Slider range | Step | Unit |
|---|---|---|---|
| VTTS urban commute | $5–$60 | $0.01 | $/person-hr |
| VTTS urban business | $20–$120 | $0.01 | $/person-hr |
| VTTS urban other | $3–$30 | $0.01 | $/person-hr |
| VTTS rural commute | $5–$60 | $0.01 | $/person-hr |
| VTTS rural business | $20–$120 | $0.01 | $/person-hr |
| VTTS rural other | $3–$30 | $0.01 | $/person-hr |
| Reliability ratio | 0–1 | 0.01 | dimensionless |
| Crash cost — fatal | $1M–$20M | $10K | $/crash |
| Crash cost — serious | $100K–$2M | $1K | $/crash |
| Crash cost — moderate | $5K–$200K | $100 | $/crash |
| Crash cost — minor | $1K–$50K | $100 | $/crash |
| Crash cost — PDO | $1K–$50K | $100 | $/crash |
| Emission cost per vtype | $0–$1.00 | $0.001 | $/veh-km |
| Air pollution per vtype | $0–$1.00 | $0.001 | $/veh-km |
| Noise per vtype | $0–$0.20 | $0.001 | $/veh-km |
| Health — walking | $0–$10 | $0.01 | $/person-km |
| Health — cycling | $0–$10 | $0.01 | $/person-km |
| Occupancy per vtype | 1–80 | 0.1 | persons/vehicle |

- VOC speed tables remain as editable `st.data_editor` DataFrames (too tabular for individual sliders)
- A **"Reset to TfNSW defaults"** button restores all PARAMS values to the hardcoded defaults
- All PARAMS values read from `st.session_state` at runtime so every calculation uses the user-overridden values
- Show delta badges (e.g. "↑ 12% from default") when a value has been changed from its default

## Phase 1: Data Model & Input Infrastructure

### Step 1: Define traffic data schema
- Create a canonical dict structure for traffic data:
  ```
  traffic_data = {
    "base_case": {
      "years": [2021, 2031, 2041, 2056],
      "car":  {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
      "lcv":  {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
      "hcv":  {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
      "bus":  {"vht": [...], "vkt": [...], "stops": [...], "demand": [...]},
    },
    "project_1": { ... same structure ... },
    ...
  }
  ```
- Create a crash data schema per case: `{"base_case": {"fatal": [...], "serious": [...], ...}, "project_1": {...}}`
- Create a cost schema per project case: `{"project_1": {"cap_planning": X, "cap_construction": X, ...}}`
- Place schema definitions and default data factory functions at top of `app.py`

### Step 2: Build modelling year configuration & annualisation parameters (sidebar — minimal)
- Sidebar retains only:
  - Project name
  - Context (urban/rural)
  - Discount rate
  - Number of project cases (1–5 selector)
  - Modelling years editor (user-defined list, e.g. 2021, 2031, 2041, 2056)
  - Evaluation period & construction years
  - **Annualisation parameters panel**:
    - Peak period hours (e.g. 2)
    - Peak-to-daily expansion factor (e.g. VHT in peak × factor = daily VHT)
    - Days per year (default 365)
    - These convert peak-period inputs → annual totals used in `calculate()`
- Everything else moves to main section

### Step 3: Build `st.data_editor` tables for traffic data entry (main section)
- New tab: **"Data Input"** — placed FIRST in the tab order
- Sub-tabs within Data Input: one per metric (VHT | VKT | Stops | Demand)
- Each sub-tab shows an editable DataFrame:
  - Rows: vehicle types (Car, LCV, HCV, Bus) + Total row (auto-summed)
  - Columns: one per modelling year
  - Separate table per case (Base Case, Project 1, ..., Project N)
- Use `st.data_editor(df, num_rows="fixed")` — paste-from-Excel supported natively
- Below each set of tables: auto-computed **Incremental** table (Project − Base) displayed as read-only `st.dataframe` with colour coding (green positive, red negative)

### Step 4: Build crash data entry tables (main section)
- Within Data Input tab, add a **Crashes** sub-tab
- Editable table per case:
  - Rows: Fatal, Serious, Moderate, Minor, PDO
  - Columns: per modelling year
- Auto-compute incremental crash reduction (Base − Project = reduction)

### Step 5: Build cost entry per project case (main section)
- Within Data Input tab, add a **Costs** sub-tab
- One cost form per project case (using `st.expander` or columns):
  - Capital: Planning, Land, Construction, Contingency %
  - Recurrent: Maintenance, Operating (per year)
  - Residual value
- Base case has no costs (it's the do-nothing reference)

### Step 6: File upload & template system
- At top of Data Input tab: file upload widget (`st.file_uploader`)
- Support CSV and Excel (.xlsx)
- Three parse modes (radio selector):
  1. **Template**: Download a pre-formatted template; upload filled version → direct column mapping
  2. **Smart parse**: Auto-detect headers (VHT/VKT/Car/LCV etc.) → best-effort mapping with preview
  3. **User mapping**: Show detected columns → user selects which column maps to which field via dropdowns
- After parsing: populate `st.session_state` traffic_data dict → tables auto-fill
- Template download button: generates an Excel file with correct sheet structure

---

## Phase 2: Calculation Engine Refactoring

### Step 7: Refactor `calculate()` to accept matrix data (*depends on Step 1*)
- New signature: `calculate(inputs: dict, traffic_data: dict, crash_data: dict, annualisation: dict) -> dict`
- **Annualisation**: multiply all peak-period VHT/VKT values by `expansion_factor × days_per_year` to get annual totals before calculating benefits
- **Linear interpolation** between modelling years to fill every evaluation year:
  - For evaluation year `t`, find the two nearest modelling years and linearly interpolate VHT/VKT
  - Extrapolate beyond last modelling year using last two years' slope (or hold flat — to be confirmed)
- **TTS calculation from VHT only**:
  - `annual_vht_saving = (VHT_base[y] − VHT_project[y]) × annualisation_factor`  (already in vehicle-hours)
  - `tts_benefit_per_vtype = annual_vht_saving[vtype] × occupancy[vtype] × VTTS_weighted ($M)`
  - Sum across vehicle types: Car, LCV, HCV, Bus
  - Occupancy per vehicle type: Car=1.4 (user-editable), LCV=1.0, HCV=1.0, Bus=45 (defaults)
- **VOC calculation from VKT**:
  - Speed derived: `avg_speed = VKT / VHT` per vehicle type per modelling year, then interpolated
  - `voc_saving[vtype][y] = (VKT_base − VKT_project)[y] × VOC_rate(avg_speed, vtype, context)` — use average of base/project speed for VOC rate
- **Safety**: annual crash reduction = base_crashes[y] − project_crashes[y] per severity, linearly interpolated
- Keep reliability = 30% × 0.9 × TTS benefit
- Return includes `absolute_base`, `absolute_project`, and `incremental` sub-dicts for display

### Step 8: Multi-project-case calculation loop (*depends on Step 7*)
- Loop `calculate()` for each active project case vs. base case
- Return: `{"project_1": {npv, bcr, ...}, "project_2": {...}, ...}`
- Each result includes `pv_by_type`, `annual_cashflow`, sensitivity etc.

### Step 9: Update sensitivity analysis (*depends on Step 8*)
- Discount rate sensitivity: run for each project case
- Demand scenarios: scale all traffic_data values by ±20%
- Switching values: per project case
- Interactive tornado: adjust traffic growth, construction cost, discount rate, eval period, demand scaling factor

---

## Phase 3: Dashboard & Output Redesign

### Step 10: Redesign Dashboard tab (*depends on Step 8, parallel with Steps 11-12*)
- KPI cards: show for each active project case (columns)
- If 1 project case: 6 KPI cards (current layout)
- If 2+ cases: use columns — one set per case, with delta row
- Benefit composition pie: per project case (toggle selector or small multiples)
- Waterfall: per project case
- Cashflow: overlay all project cases on same chart

### Step 11: Incremental benefits summary (*parallel with Step 10*)
- New section on Dashboard: **Incremental Benefits Summary**
- Table showing base vs project absolute values and increments:
  - Rows: VHT, VKT, Demand, Stops, Crashes by severity
  - Columns: Base Case | Project 1 | Δ1 | Project 2 | Δ2 | ...
- Colour-coded deltas (green = improvement, red = disbenefit)
- This gives the "at a glance" view the user requested

### Step 12: Update Cashflow & Sensitivity tabs (*depends on Step 8*)
- Cashflow table: add project case selector if multiple cases
- Sensitivity: run per selected project case
- CSV export: include project case identifier

---

## Relevant Files
- `app.py` — **Primary target**. ~600 lines. Major restructure of sidebar inputs, calculate() function, and all 4 tabs
- `claude.md` — Update after implementation to reflect new architecture

## Verification
1. **Unit chain — TTS**: Enter VHT=1000 veh-hrs/period, expansion=5, days=365, occupancy Car=1.4, VTTS=$19.76/person-hr → verify TTS = 1000×5×365×1.4×19.76/1e6 ≈ $50.5M/year
2. **Unit chain — VOC**: VKT_base=10000, VKT_proj=9000 veh-km/period, expansion=5, speed_base=45, speed_proj=65 → verify VOC rates interpolated from PARAMS table, output units $M/year
3. **Unit chain — CO₂**: VKT_base=10000, VKT_proj=9000, emission_factor=0.000185 tCO₂e/veh-km, carbon=$123/t → verify CO₂ benefit = (10000−9000)×5×365×0.000185×123/1e6 ≈ $0.041M/year
4. **Derived speed display**: VKT=50000, VHT=1000 → displayed speed = 50 km/h
5. **Occupancy per type**: Enter Bus VHT saving = 10 veh-hrs/period, occupancy=45 → Bus TTS substantially larger than Car contribution
6. **Paste test**: Copy a block of numbers from Excel → paste into `st.data_editor` → verify all cells populate correctly  
7. **File upload — template mode**: Download template → fill values → upload → verify tables populate
8. **Incremental display**: Enter identical base case = project case → all increments show zero
9. **Multi-case**: Add 3 project cases → verify each produces independent NPV/BCR
10. **Linear interpolation**: Enter modelling years 2021 and 2031 with values 1000 and 2000 → verify year 2026 = 1500
11. **Unit labels visible**: Check every input widget, every table column, every chart y-axis shows unit
12. **`streamlit run app.py`** — no errors, all tabs render

## Decisions
- **JS version unchanged** — only Streamlit app updated
- **Speed is derived** from VKT/VHT (not a direct input) — avg_speed = VKT / VHT
- **Trip purpose split** remains global (not per vehicle type) — kept for simplicity
- **Environmental & active transport** inputs stay as simple annual values (not matrixed)
- **Backward compatibility**: Not required — this is a fundamental UI redesign
- **Sidebar stays minimal**: Only project config (name, context, discount rate, years, # cases)

## Resolved Decisions (from user)
- **Peak period inputs**: Users enter peak-period VHT/VKT/Stops/Demand. An annualisation panel in sidebar/input tab lets users specify expansion factors (e.g. peak-to-daily factor, days-per-year) to convert to annual values for discounting.
- **Interpolation**: Linear interpolation between modelling years (confirmed).
- **VHT for TTS**: VHT alone is used for TTS calculation. The "Demand" row in the matrix is captured for reference/display but TTS benefit = (VHT_base − VHT_project) × VTTS (no separate demand row needed in the engine).
