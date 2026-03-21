# CLAUDE.md — Cost-Benefit Analysis Repository Guide

## Project Overview

A Transport Cost-Benefit Analysis (CBA) dashboard implementing the TfNSW (Transport for New South Wales) Economic Parameter Values framework (January 2025, June 2024 prices in AUD). The tool supports multi-vehicle-type, multi-project-case analysis with discounting, sensitivity analysis, and flexible data import/export.

**Two versions exist:**
- **Streamlit app** (`app.py`) — primary production version, Python-based
- **Standalone web dashboard** (`index.html` + `cba-engine.js`) — HTML5/JavaScript version

---

## Repository Structure

```
Cost-Benefit-Analysis/
├── app.py                          # Primary Streamlit application (2,100+ lines)
├── requirements.txt                # Python dependencies
├── plan.md                         # Detailed implementation roadmap
├── index.html                      # Standalone HTML5 dashboard
├── cba-engine.js                   # CBA calculation engine (JavaScript, mirrors app.py)
├── app.js                          # Parameter reference table renderers (JavaScript)
├── charts.js                       # Chart.js chart rendering utilities
├── styles.css                      # CSS for standalone web version
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
| Charts | Plotly ≥ 5.18.0 (Streamlit), Chart.js 4.4.7 (standalone) |
| File I/O | openpyxl ≥ 3.1.0 (Excel templates) |
| Standalone web | Vanilla HTML5, CSS3, JavaScript |

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Streamlit app
streamlit run app.py
```

There is no build step. JavaScript files in the root are for the standalone HTML5 version only and are loaded directly by `index.html`.

---

## Architecture: `app.py`

### Key Sections (by line range)

| Section | Lines | Description |
|---------|-------|-------------|
| `PARAMS` dict | ~43–95 | TfNSW economic parameter defaults (VTTS, VOC, crash costs, emissions, etc.) |
| Data schema factories | ~162–218 | `make_traffic_case()`, `make_traffic_data()`, `make_cost_data()` |
| Helper functions | ~225–282 | Discount factors, VOC interpolation, CAGR year interpolation |
| Matrix UI helpers | ~289+ | Traffic table renderers, crash data, cost entry |
| File upload handlers | ~465–610 | Template mode, smart parse, user mapping |
| `calculate_matrix()` | ~700+ | Core benefit/cost calculation engine |
| `calculate_all_cases()` | ~941–964 | Runs calculation loop across all project cases |
| UI tabs/sidebar | ~1310+ | Streamlit layout: sidebar config, tabs |

### Session State Convention

Session state keys follow these patterns:
- `st.session_state["traffic_data"]` — nested dict keyed by case → vehicle type → metric
- `st.session_state["cost_data"]` — nested dict keyed by case → cost category
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
```python
{
  "cap_planning": float,         # $M
  "cap_land": float,             # $M
  "cap_construction": float,     # $M
  "contingency_pct": float,      # %
  "opex_maint": float,           # $M/yr
  "opex_op": float,              # $M/yr
  "residual": float              # $M (end-of-period residual value)
}
```

### Calculation Output (per case)
```python
{
  "npv": float,
  "bcr": float,
  "pv_benefits": float,
  "pv_costs": float,
  "annual_costs": list,
  "annual_benefits": list,
  "annual_net": list,
  "pv_by_type": {"tts": float, "voc": float, "safety": float, "env": float, "active": float},
  "sensitivity_dr": {...},
  "switching": {...},
  "scenarios": {...}
}
```

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
`tts`, `reliability`, `voc`, `safety`, `env`, `active`

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
```

---

## File Import/Export

Three upload modes:
1. **Template** — pre-formatted openpyxl Excel (one sheet per metric: VHT, VKT, Stops, Demand, Crashes)
2. **Smart Parse** — auto-detect headers; uses `_auto_match_vtypes()`, `_auto_match_years()`, `_auto_match_cases()`
3. **User Mapping** — drag-and-drop column mapper (Streamlit custom component in `column_mapper_component/`)

Export: CSV results download, Excel template generation.

---

## Parameters System

- `PARAMS` dict holds immutable defaults (TfNSW Jan 2025 values)
- User edits in Parameters tab are stored as overrides in `st.session_state`
- `build_effective_params()` merges overrides into a copy of `PARAMS` at calculation time
- Never mutate `PARAMS` directly

---

## Testing

No automated test suite exists. Verification is manual per the checklist in `plan.md`:
- Unit chain tests for TTS, VOC, CO₂ (with specific input/expected output values)
- Derived speed display
- Occupancy per vehicle type impact
- Paste/file upload round-trips
- Multi-case independence
- CAGR interpolation between modelling years
- Startup: `streamlit run app.py` must load without errors

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

1. **`app.py`** — entire application; read top-to-bottom for full picture
2. **`plan.md`** — implementation roadmap; consult before adding features to avoid conflicts
3. **`cba-engine.js`** — JavaScript mirror of `app.py` calculations; keep in sync when changing formulas

---

## Common Pitfalls

- **Do not mutate `PARAMS`** — always use `build_effective_params()` copy
- **Speed is always derived** (`VKT/VHT`), never accept speed as a direct input
- **CAGR interpolation, not linear** — use the geometric interpolation formula for year-by-year expansion
- **Discounting is start-of-year** — discount factor = `1/(1+r)^year`, not mid-year
- **Vehicle type mapping** — user sees `Car/LCV/HCV/Bus`; `PARAMS` uses `car/lgv/rigid/artic`
- **Benefits are incremental** — always project minus base; never absolute values
- **JavaScript standalone is separate** — changes to `app.py` calculation logic should be mirrored in `cba-engine.js` if the standalone version matters
