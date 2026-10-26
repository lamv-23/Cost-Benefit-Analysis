# TfNSW / Treasury Compliance Additions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add yearly P50/P90 capital, recurrent and base case cost cashflows, upfront carbon, and the full TfNSW required sensitivity table to the Streamlit CBA app.

**Architecture:** The pure calculation code moves out of `app.py` into a new Streamlit-free module, `cba_engine.py`, so it can be unit tested with pytest. Costs become yearly rows turned into a per-year *cost schedule* by one function. `calculate_matrix` gains a `scenario` argument, so every required sensitivity test is an exact re-run, not a scaled output. `app.py` keeps all UI and session state.

**Tech Stack:** Python 3.9 (local) / 3.12 (Streamlit Cloud), Streamlit 1.47.1, pandas, numpy, Plotly, pytest 8.4.2, `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-10-26-tfnsw-compliance-design.md`

## Global Constraints

- Code must run on Python 3.9.6 and 3.12. Put `from __future__ import annotations` at the top of `cba_engine.py`. No `match` statements.
- All costs are real June 2024 dollars. The two nominal outturn inputs are for reporting only and are never used in a calculation.
- Discounting stays start-of-year: `1 / (1 + r/100) ** t`.
- Never mutate `PARAMS`; take a deep copy, as `build_effective_params()` does.
- `requirements.txt` is unchanged. Add `requirements-dev.txt` containing exactly `pytest==8.4.2`.
- Run tests with `python3 -m pytest tests -q`.
- Do all work on branch `feat/tfnsw-compliance`, created from `claude/complete-cba-dashboard-hBs4G`. That branch deploys to Streamlit Cloud, so do not merge or push to it until the user approves.
- Commit messages use `type: description`, ending with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01EaE5nuaAmjgbnChHcZtGYJ
  ```
- Fixed copy:
  - Old-file error: `This project file was saved in an older format and can't be opened. Please re-enter the project.`
  - Table title: `TfNSW required sensitivity tests`
  - Blank outturn cell: `not entered`

## Review Focus

1. The construction period or appraisal period changes after costs were entered: the tables resize, entered years keep their values, and nothing raises. Tested in Task 2 (`fit_cost_rows`) and Task 3 (AppTest).
2. No capital entered yet (all zeros): no division by zero when spreading carbon, attributing contingency or calculating BCR. Tested in Tasks 2 and 3.
3. Pasted rows containing blanks, `None` or `NaN` are treated as 0.0, never propagated as NaN. Tested in Task 2 (`clean_row`).
4. A central discount rate of 3, 4 or 7%: the required table still shows all 17 rows, and the discount-rate chart has no duplicate points. Tested in Task 5.
5. Changing the number of options keeps the shared base case row, and every option has correctly sized rows. Tested in Task 3 (AppTest).

## File Structure

| File | Responsibility |
|---|---|
| `cba_engine.py` (new) | `PARAMS`, vehicle maps, `VTYPES`, `TYPE_LABELS`, the traffic and cost data factories, the cost schedule, `calculate_matrix`, `calculate_all_cases`, `run_required_sensitivities`, `run_monte_carlo`, `appraisal_summary`, `generate_csv`, `validate_project_file`. No `streamlit` import. |
| `app.py` | UI, session state, caching, charts. Imports the names above from `cba_engine`. |
| `tests/conftest.py` | Small fixture builders (`make_case_traffic`, `fixture_costs`). |
| `tests/test_engine.py` | Unit tests for `cba_engine`. |
| `tests/test_app_smoke.py` | AppTest headless runs of `app.py`. |
| `requirements-dev.txt` | `pytest==8.4.2` |
| `CLAUDE.md` | Updated architecture and testing sections (Task 6). |

---

### Task 1: Test harness and engine module (no behaviour change)

**Files:**
- Create: `cba_engine.py`, `tests/conftest.py`, `tests/test_engine.py`, `tests/test_app_smoke.py`, `requirements-dev.txt`
- Modify: `app.py`. Remove the moved definitions and add `from cba_engine import (...)`.

**Interfaces:**
- Produces, moved verbatim into `cba_engine.py`:
  - constants: `PARAMS`, `VTYPE_MAP`, `EMISSION_VTYPE_MAP`, `AIR_NOISE_VTYPE_MAP`, `VTYPES`, `DEFAULT_MODELLING_YEARS`, `TYPE_LABELS`
  - functions: `make_traffic_case`, `make_traffic_data`, `make_cost_data`, `discount_factor`, `interpolate_voc`, `_cagr_interpolate`, `interpolate_modelling_years`, `calculate_matrix`, `calculate_all_cases`, `run_monte_carlo`, `generate_csv`
- Stay in `app.py`: `build_effective_params`, `_stable_hash`, `_cached_calculate_all_cases`, `format_m`, the colour maps, and everything that touches `st`.
- `tests/conftest.py` produces `make_case_traffic(years: list[int], **by_vtype) -> dict`. It returns a traffic case dict with every vehicle type in `VTYPES`, all zeros unless given.

- [ ] **Step 1: Create the branch.** `git checkout -b feat/tfnsw-compliance`

- [ ] **Step 2: Write regression tests that pin current behaviour** in `tests/test_engine.py`. They use the rural context, `annualisation = {vt: {"factor": 1.0, "days": 1}}`, years `[2026, 2056]`, `construction_years=2`, `evaluation_period=30`, `discount_rate=7`, `construction_start_year=2026` and `discount_base_year=2026`. Each assertion uses `result["first_year"]` values × 1e6, to 2 decimal places:
  - `test_voc_uses_total_cost_difference`: Car VHT 1000→750, VKT 60000 both cases → `voc == 720.0`
  - `test_safety_uses_rate_difference`: same traffic, project Car rate 0.100 (base 0.153) → `safety == 3180.0`
  - `test_safety_shorter_route_same_rate`: Car VKT 60000→55000, VHT 1000→950 → `safety == 765.0`
  - `test_disbenefit_not_clamped`: HCV VHT 100→120, VKT 8000 → `tts == -987.6`
  - `test_interpolation_from_zero`: `interpolate_modelling_years([2026, 2056], [0.0, 100.0], 2056) == 100.0` and the same at 2041 `== 50.0`
  - `test_rule_of_half_user_benefits_only`: Car VHT 1000→800, VKT 60000→64000, with `generated_demand_pct_global=100` → tts, reliability and voc are each 0.5× the 0% run; safety and env are each 1.0×

  These tests call the current `calculate_matrix(inputs, base_traffic, proj_traffic, cost, annualisation, sv_base, sv_proj, params)` signature, using `cost = make_cost_data(1)["project_1"]`.

- [ ] **Step 3: Write `tests/test_app_smoke.py::test_sample_data_runs`.** AppTest on `app.py` with `default_timeout=300`:
  - check `confirm_load_sample`, then click "Load Sample Data";
  - assert no `at.exception`;
  - assert the metric "Benefit-Cost Ratio" == `"1.68"`, "PV Benefits" == `"$614.6M"` and "PV Costs" == `"$365.0M"`.

- [ ] **Step 4: Run the tests.** `python3 -m pytest tests -q`. Expected: FAIL with `ModuleNotFoundError: cba_engine`.

- [ ] **Step 5: Move the definitions** into `cba_engine.py`, with `from __future__ import annotations` and its own imports (`math`, `copy`, `io`, `csv`, `json`). Import them back into `app.py`.

- [ ] **Step 6: Run the tests.** `python3 -m pytest tests -q`. Expected: all PASS, and the sample metrics are unchanged.

- [ ] **Step 7: Commit.** `refactor: move calculation engine to cba_engine.py and add pytest suite`

---

### Task 2: Yearly cost data model and cost schedule

**Files:**
- Modify: `cba_engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces:
  - `COST_FORMAT_VERSION = 2`
  - `CAPEX_CATEGORIES = ("planning", "land", "construction")`
  - `clean_row(values: list) -> list[float]`. Turns `None`, `NaN` and `""` into `0.0`, and casts everything to float.
  - `make_cost_data(n_project_cases: int, const_years: int, eval_period: int) -> dict[str, dict]`. Replaces the old signature. Each case is:
    ```python
    {"capex_base": {"planning": [0.0]*C, "land": [0.0]*C, "construction": [0.0]*C},
     "contingency_p50": [0.0]*C, "contingency_p90": [0.0]*C,
     "recurrent": [0.0]*(C+E), "upfront_carbon_t": 0.0,
     "outturn_p50_nominal": None, "outturn_p90_nominal": None,
     "construction_disbenefit_annual": 0.0, "construction_asset_life": 40, "residual": 0.0,
     "walk_pkm_day": 0.0, "cycle_pkm_day": 0.0,
     "generated_demand_pct_global": 0.0,
     "generated_demand_pct_override": {vt: None for vt in VTYPES}}
    ```
    `C` = construction years, `E` = appraisal period. Each case is a deep copy, so no nested objects are shared between cases.
  - `make_base_case_costs(const_years: int, eval_period: int) -> dict`. Returns `{"recurrent": [0.0]*(C+E)}`.
  - `fit_cost_rows(costs: dict, const_years: int, eval_period: int) -> None`. Works in place: pads with `0.0` or trims each capex and contingency row to `C`, and `recurrent` to `C+E`. Works on both project and base dicts; ignores keys that are absent.
  - `build_cost_schedule(cost: dict, base_costs: dict, const_years: int, eval_period: int, capital: str = "p50", delay_years: int = 0) -> dict`, where `N = delay_years + C + E`. Returns:
    - `capital: list[float]` (length N): base rows plus the chosen contingency, placed at `t in [D, D+C)`, else `0.0`.
    - `project_recurrent: list[float]` (N): for `t < D`, `base_recurrent[t]`; otherwise `recurrent[t-D]`, repeating the last value past the end.
    - `base_recurrent: list[float]` (N): the base row, repeating its last value past the end.
    - `upfront_carbon_t: list[float]` (N): carbon spread pro rata to **P50** capital by year, shifted by D. If total P50 capital is 0, all of it goes in year `D`.
    - `construction_years: list[bool]` (N): True for `t in [D, D+C)`.
    - `capital_by_category: dict[str, float]`: each category's base total, plus the chosen contingency attributed pro rata to base category totals. If the base total is 0, all contingency goes to `"construction"`.
    - `capital_total: float`

- [ ] **Step 1: Write the failing tests.** Fixture `fixture_costs()` in `conftest.py`, with C=2 and E=3:
  - `capex_base`: planning `[1,0]`, land `[2,0]`, construction `[4,4]`
  - `contingency_p50` `[1,1]`, `contingency_p90` `[2,2]`
  - `recurrent` `[0.5,0.5,1,1,1]`; base recurrent `[0.5,0.5,0.8,0.8,0.8]`
  - `upfront_carbon_t` 1000

  Tests:
  ```python
  def test_schedule_p50():
      s = build_cost_schedule(cost, base, 2, 3)
      assert s["capital"] == [8.0, 5.0, 0, 0, 0] and s["capital_total"] == 13.0
      assert s["capital_by_category"]["land"] == pytest.approx(2.363636, abs=1e-6)
      assert s["capital_by_category"]["construction"] == pytest.approx(9.454545, abs=1e-6)
      assert s["upfront_carbon_t"][:2] == pytest.approx([615.384615, 384.615385])
  def test_schedule_p90():           # capital_total == 15.0; carbon split unchanged (P50 shares)
  def test_schedule_delay_1():       # capital == [0, 8, 5, 0, 0, 0];
                                     # project_recurrent == [0.5, 0.5, 0.5, 1, 1, 1];
                                     # base_recurrent == [0.5, 0.5, 0.8, 0.8, 0.8, 0.8];
                                     # upfront_carbon_t[0] == 0
  def test_schedule_zero_capital():  # all capex 0 -> no exception;
                                     # carbon all in year 0; capital_total == 0
  def test_fit_cost_rows_pads_and_trims():  # C 2->3 keeps [1,0] -> [1,0,0];
                                            # E 3->2 trims recurrent to 4 values
  def test_clean_row():              # clean_row([1, None, float("nan"), "", "2.5"]) == [1.0, 0.0, 0.0, 0.0, 2.5]
  def test_make_cost_data_no_shared_rows():
      # mutating project_1 recurrent / override dict leaves project_2 unchanged
  ```

- [ ] **Step 2: Run the tests.** `python3 -m pytest tests/test_engine.py -q`. Expected: the new tests FAIL with `ImportError`.

- [ ] **Step 3: Implement the functions above** in `cba_engine.py`. `make_cost_data` changes signature in this task, so update its callers in `app.py` to pass the sidebar's `const_years` and `eval_period`. The UI still uses the old fields until Task 3, so keep the old keys in the returned dicts for now, alongside the new ones. Task 3 removes them.

- [ ] **Step 4: Run the tests.** `python3 -m pytest tests -q`. Expected: all PASS, and the smoke test is unchanged.

- [ ] **Step 5: Commit.** `feat: yearly cost data model and cost schedule`

---

### Task 3: Switch the app to yearly costs

This is one task because the engine, the cost UI, the sample data and save/load must change together for the app to keep running.

**Files:**
- Modify: `cba_engine.py` (`calculate_matrix`, `calculate_all_cases`, `run_monte_carlo`, `TYPE_LABELS`, new `validate_project_file`)
- Modify: `app.py` (`render_cost_entry`, `_load_sample_data`, `_init_session_state`, `_serialise_project`, `_deserialise_project`, the calculation call sites, sidebar help text, `COLORS`)
- Test: `tests/test_engine.py`, `tests/test_app_smoke.py`

**Interfaces:**
- Consumes: Task 2's schedule functions.
- Produces:
  - `calculate_matrix(inputs, base_traffic, proj_traffic, cost, base_costs, annualisation, safety_vkt_base=None, safety_vkt_proj=None, params=None) -> dict`. `base_costs` is new and comes after `cost`. Changes to the result:
    - new keys `annual_capital`, `annual_recurrent`, `pv_capital`, `pv_recurrent`, `capital_p50_total`, `capital_p90_total`, `residual`;
    - `benefits_by_type` keys become `tts`, `tts_<vt>`, `reliability`, `voc`, `safety`, `env`, `active`, `avoided_costs`, `upfront_carbon`, `construction_disruption`, `residual`;
    - `"pavement"` is removed.
  - `calculate_all_cases(inputs, traffic_data, cost_data, base_case_costs, annualisation, safety_vkt_data=None, params=None) -> dict`
  - `TYPE_LABELS` adds:
    - `avoided_costs: "Avoided Base Case Costs"`
    - `upfront_carbon: "Upfront Carbon Emissions"`
    - `construction_disruption: "Construction Disruption"`
    - `residual: "Residual Value"`

    It drops `pavement`.
  - `validate_project_file(data: dict) -> str | None`. Returns the fixed old-file error text unless `data.get("type") == "cba_project"` and `data.get("cost_format") == COST_FORMAT_VERSION`; otherwise returns `None`.
  - Session key `base_case_costs` holds `make_base_case_costs(...)`. Saved files include `"cost_format": COST_FORMAT_VERSION` and `base_case_costs`.

**Rules, from the spec:**

Per year `t`:
- Cost = `capital[t] + project_recurrent[t]`.
- Benefit = transport benefits + `avoided_costs`, where:
  - `avoided_costs = base_recurrent[t]`
  - `upfront_carbon = −carbon_t[t] × params["carbon_per_tonne"] / 1e6`
  - `construction_disruption = −construction_disbenefit_annual` in construction years
  - `residual` goes in the last year only

Residual value:
- Auto residual = `land + construction × max(0, (life − E)/life)`, using `capital_by_category`.
- The manual override (`residual > 0`) wins.

Other results:
- FYRR uses `capital_p50_total`.
- The carbon sensitivity multiplies `annual_env_emit + upfront_carbon` by `(factor − 1)`.

Monte Carlo:
- The cost factor multiplies `capex_base["construction"]` and `contingency_p50` element-wise.
- The tornado does the same.

- [ ] **Step 1: Write the failing engine tests.** Use `fixture_costs()`, zero traffic (`make_case_traffic` with no args), `discount_rate=0`, `construction_years=2`, `evaluation_period=3` and `construction_asset_life=40`:
  ```python
  def test_central_costs_and_lines():
      r = calculate_matrix(inp, bt, pt, cost, base, ann, params=PARAMS)
      assert r["pv_capital"] == pytest.approx(13.0)
      assert r["pv_recurrent"] == pytest.approx(4.0)
      assert r["pv_costs"] == pytest.approx(17.0)
      assert r["pv_by_type"]["avoided_costs"] == pytest.approx(3.4)
      assert r["pv_by_type"]["upfront_carbon"] == pytest.approx(-0.123)
      assert r["pv_by_type"]["residual"] == pytest.approx(11.109091, abs=1e-6)
      assert r["pv_benefits"] == pytest.approx(14.386091, abs=1e-6)
      assert r["bcr"] == pytest.approx(0.846241, abs=1e-6)
  def test_construction_disruption_is_disbenefit():
      # construction_disbenefit_annual=0.2 -> pv_by_type["construction_disruption"] == -0.4,
      # pv_costs unchanged at 17.0
  def test_manual_residual_override():   # residual=5.0 -> pv_by_type["residual"] == 5.0
  def test_validate_project_file():
      # {} and {"type": "cba_project"} -> exact error text;
      # {"type": "cba_project", "cost_format": 2} -> None
  ```
  Update Task 1's regression tests to the new signature, passing `make_base_case_costs(2, 30)` as `base_costs` and the new `make_cost_data(1, 2, 30)`. Their expected values do not change.

- [ ] **Step 2: Run the tests.** `python3 -m pytest tests/test_engine.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement the engine changes** listed above. Remove the old cost keys from `make_cost_data`.

- [ ] **Step 4: Rewrite `render_cost_entry`.**
  1. A **"Base case — recurrent costs ($M, real)"** expander, rendered first. It is one `st.data_editor` row over every timeline year (columns are calendar years from `construction_start_year`).
  2. Per option:
     - a capital `st.data_editor` with 5 rows (Planning & design, Land, Construction, Contingency to P50, Contingency to P90) by construction year, with P50 and P90 totals shown below it;
     - a recurrent row `st.data_editor`, whose help text says construction-year values should be the cost of maintaining the existing road;
     - `Upfront carbon (tCO₂e)`;
     - `P50 outturn capital (nominal $M)` and `P90 outturn capital (nominal $M)` as `st.number_input(value=None)`;
     - the existing asset life, residual override, disruption, active transport and Rule-of-Half inputs.

  Write values back through `clean_row`. Call `fit_cost_rows` on every case, and on the base dict, before rendering. Remove the contingency % input, the pavement input and the `generated_demand_pct_override` `setdefault` shim.

- [ ] **Step 5: Rewrite `_load_sample_data` costs** (3 construction years, 30-year appraisal period):
  - `capex_base`: planning `[10,3,2]`, land `[25,5,0]`, construction `[60,120,80]`
  - `contingency_p50` `[8,20,17]`, `contingency_p90` `[14,35,29]`
  - `recurrent`: `1.2` in construction years, then `2.2`/yr, plus `6.0` in operating years 10, 20 and 30
  - base `recurrent`: `1.2`/yr, plus `5.0` in timeline years 8, 18 and 28
  - `upfront_carbon_t` 45000; outturn P50 `395.0`, P90 `432.0`

  Keep the existing traffic, walk/cycle and other sample values.

- [ ] **Step 6: Update save/load and sidebar help.**
  - `_serialise_project` adds `"cost_format": COST_FORMAT_VERSION` and `base_case_costs`.
  - `_deserialise_project` calls `validate_project_file` first. If it returns an error, show it with `st.error` and load nothing.
  - The Evaluation Period help text becomes: `Appraisal period in years, counted from opening (TfNSW default: 30 years; maximum 50). Construction years are added before it.`

- [ ] **Step 7: Write the smoke tests** in `tests/test_app_smoke.py`. Replace the pinned numbers in `test_sample_data_runs` with: no exception, and the "PV Costs" metric is present. Add:
  - `test_change_construction_years_keeps_costs`: after loading the sample, set the sidebar "Construction Period (years)" to 4. There is no exception, and `cost_data["project_1"]["capex_base"]["construction"] == [60.0, 120.0, 80.0, 0.0]`.
  - `test_two_options_share_base_costs`: set "Number of Project Cases" to 2. There is no exception, `base_case_costs["recurrent"]` is unchanged in length (33), and `cost_data["project_2"]["recurrent"]` has length 33.
  - `test_empty_project_no_errors`: a fresh app with no sample data has no exception (zero capital).

- [ ] **Step 8: Run the tests.** `python3 -m pytest tests -q`. Expected: all PASS.

- [ ] **Step 9: Check the sample's P50 capital** at 350.0 and P90 at 383.0 in the cost entry metrics, then pin the sample's new "Benefit-Cost Ratio" metric value in `test_sample_data_runs`.

- [ ] **Step 10: Commit.** `feat: yearly P50/P90 capital, recurrent and base case costs, upfront carbon`

---

### Task 4: Scenario options in `calculate_matrix`

**Files:**
- Modify: `cba_engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces: `calculate_matrix(..., params=None, scenario: dict | None = None)`. Keys of `scenario`, with defaults:
  - `capital: "p50"`
  - `delay_years: 0`
  - `growth: "forecast"` (or `"none"` / `"half"`)
  - `cost_factor: 1.0`
  - `benefit_factor: 1.0`
  - `discount_rate: None`

  A `discount_rate` of `None` means `inputs["discount_rate"]`.

**Rules:**
- `cost_factor` scales capital, project recurrent costs and the *auto* residual.
- `benefit_factor` scales tts, reliability, voc, safety, env and active only.
- The manual residual override is never scaled.
- `delay_years` goes to `build_cost_schedule`. The construction start moves D years later, and benefits are calculated for the delayed calendar years.
- Opening year `Y0 = construction_start_year + D + C`.
- Traffic value for year `y ≥ Y0`:
  - `"none"` uses `v(Y0)`;
  - `"half"` uses `v0 × (1 + g/2)^(y−Y0)`, where `g = (v(y)/v0)^(1/(y−Y0)) − 1`, and returns `v0` when `v0 == 0` or `y == Y0`.
- The growth adjustment applies after the existing `zero_growth_after_last_year` clamp.

- [ ] **Step 1: Write the failing tests.** Same fixture as Task 3, at `discount_rate=0`:
  ```python
  def test_scenario_p90():          # pv_costs == 19.0; pv_by_type["residual"] == approx(12.818182)
  def test_scenario_cost_factor():  # cost_factor=1.2 -> pv_costs == 20.4;
                                    # residual == approx(13.330909); avoided_costs still 3.4
  def test_scenario_cost_factor_keeps_manual_residual():  # residual=5.0, cost_factor=1.4 -> residual 5.0
  def test_scenario_benefit_factor():
      # traffic with tts > 0: benefit_factor=1.4 -> pv_by_type["tts"] == 1.4 * central;
      # avoided_costs / upfront_carbon / residual unchanged
  def test_scenario_delay_1():      # pv_costs == 17.5; pv_by_type["avoided_costs"] == 4.2;
                                    # pv_benefits == approx(15.186091); total_years == 6
  def test_scenario_delay_uses_later_traffic():
      # growing traffic: first operating year's tts with delay 1 == central tts for the following calendar year
  def test_scenario_no_growth():    # growing Car VHT saving: every operating year's tts == first operating year's
  def test_scenario_half_growth():  # year Y0+10 value == v0 * (1 + g/2)**10 within 1e-9 relative
  def test_scenario_discount_rate():
      # scenario discount_rate=7 equals central run with inputs["discount_rate"]=7
      # (npv, bcr within 1e-9)
  ```

- [ ] **Step 2: Run the tests.** `python3 -m pytest tests/test_engine.py -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement the `scenario` handling.**

- [ ] **Step 4: Run the tests.** `python3 -m pytest tests -q`. Expected: all PASS.

- [ ] **Step 5: Commit.** `feat: scenario options for P90, delay, growth and cost/benefit factors`

---

### Task 5: Required sensitivity table

**Files:**
- Modify: `cba_engine.py`, `app.py` (Sensitivity tab: the discount-rate chart and the Scenario Analysis table)
- Test: `tests/test_engine.py`, `tests/test_app_smoke.py`

**Interfaces:**
- Produces: `run_required_sensitivities(inputs, base_traffic, proj_traffic, cost, base_costs, annualisation, safety_vkt_base=None, safety_vkt_proj=None, params=None) -> list[dict]`. Each row is `{"test": str, "pvb": float, "pvc": float, "npv": float, "bcr": float, "central": bool}`. There are exactly 17 rows, in this order, with these `test` labels:
  1. `Central`
  2. `Discount rate 3%`
  3. `Discount rate 4%`
  4. `Discount rate 7%`
  5. `Costs +20%`
  6. `Costs −20%`
  7. `Costs +40%`
  8. `Costs −40%`
  9. `Benefits +20%`
  10. `Benefits −20%`
  11. `Benefits +40%`
  12. `Benefits −40%`
  13. `P90 capital cost`
  14. `Opening delayed 1 year`
  15. `Opening delayed 3 years`
  16. `No traffic growth`
  17. `Half traffic growth`

  `calculate_matrix` no longer returns `sensitivity_dr` or `scenarios`.

- [ ] **Step 1: Write the failing tests.**
  ```python
  def test_required_rows_order_and_central():  # 17 labels exactly as above; only row 0 central;
                                               # row 0 npv == calculate_matrix central npv
  def test_required_rows_match_scenarios():    # "Costs +20%" pvc == scenario cost_factor=1.2 pvc;
                                               # "P90 capital cost" == scenario capital="p90"
  def test_required_rows_when_central_is_7():  # inputs discount_rate=7 -> still 17 rows;
                                               # "Discount rate 7%" npv == Central npv
  ```
  Smoke test `test_sensitivity_table_present`: after loading the sample, a dataframe whose index or "Test" column holds all 17 labels is rendered with no exception.

- [ ] **Step 2: Run the tests.** `python3 -m pytest tests -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement `run_required_sensitivities`.** In `app.py`:
  - cache it per option with `st.cache_data`, keyed like `_cached_calculate_all_cases`;
  - render `TfNSW required sensitivity tests` at the top of the Sensitivity tab as a dataframe with the central row highlighted;
  - build the discount-rate chart from the Central row and the 3%, 4% and 7% rows, plotting the central rate's point once only;
  - remove the old Scenario Analysis rows (3.5% and 10%, Demand ±20%) and every use of `sensitivity_dr` and `scenarios`.

- [ ] **Step 4: Run the tests.** `python3 -m pytest tests -q`. Expected: all PASS.

- [ ] **Step 5: Commit.** `feat: TfNSW required sensitivity tests table`

---

### Task 6: Reporting, CSV and docs

**Files:**
- Modify: `cba_engine.py` (`appraisal_summary`, `generate_csv`), `app.py` (Dashboard summary table, benefit chart types, Cashflow tab, CSV download call, About tab text), `CLAUDE.md`
- Test: `tests/test_engine.py`, `tests/test_app_smoke.py`

**Interfaces:**
- Produces:
  - `appraisal_summary(result: dict, cost: dict) -> dict`, with keys in this order:
    - `P50 outturn capital (nominal $M)`
    - `P90 outturn capital (nominal $M)`
    - `PV capital ($M)`
    - `PV recurrent costs ($M)`
    - `PV costs ($M)`
    - `PV benefits ($M)`
    - `NPV ($M)`
    - `BCR`

    The outturn values are copied from `cost` exactly, or are `"not entered"` when `None`.
  - `generate_csv(results: dict, project_name: str, summary: dict, sensitivity_rows: list[dict]) -> str`. Sections in order: the summary, the itemised PV (every `TYPE_LABELS` line, plus PV capital and PV recurrent), the required sensitivity tests, then the yearly cashflow with the columns Capital, Recurrent, Benefits, Net, Discounted net and Cumulative.

- [ ] **Step 1: Write the failing tests.**
  ```python
  def test_summary_outturn_not_entered():  # outturn None -> both "not entered";
                                           # PV capital == result["pv_capital"]
  def test_summary_outturn_copied():       # outturn_p50_nominal=395.0 -> 395.0 unchanged
  def test_csv_sections():                 # CSV contains "TfNSW required sensitivity tests",
                                           # "Avoided Base Case Costs", "P90 capital cost",
                                           # "P50 outturn capital (nominal $M)"
  ```
  Smoke test `test_dashboard_summary`: after loading the sample, a dataframe containing `P50 outturn capital (nominal $M)` with value 395.0 renders, with no exception.

- [ ] **Step 2: Run the tests.** `python3 -m pytest tests -q`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement.**
  - **Dashboard:** an "Appraisal summary" table with one column per option, above the charts.
  - **Benefit composition:** the chart's `_bar_types` and `COLORS` use the new keys:
    - `avoided_costs "#20c997"`
    - `upfront_carbon "#6c757d"`
    - `construction_disruption "#adb5bd"`
    - `residual "#795548"`
  - **Cashflow tab:** columns for Capital, Recurrent, Avoided base case costs, Upfront carbon, Construction disruption and Residual.
  - **CSV download:** passes the summary and the sensitivity rows.
  - **About tab:** replace text that mentions removed inputs. Use `grep -n -i 'pavement\|contingency\|scenario' app.py` to find it.
  - **`CLAUDE.md`:** in the Architecture and Testing sections, describe `cba_engine.py`, the yearly cost schema and `python3 -m pytest tests -q`. Remove the stale `cba-engine.js`/`index.html` references.

- [ ] **Step 4: Run the tests.** `python3 -m pytest tests -q`. Expected: all PASS. `grep -n 'pavement' app.py cba_engine.py` returns nothing.

- [ ] **Step 5: Commit.** `feat: appraisal summary, itemised PV and CSV for TfNSW reporting`
