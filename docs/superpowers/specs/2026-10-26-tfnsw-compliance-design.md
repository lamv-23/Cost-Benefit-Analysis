# TfNSW / NSW Treasury compliance additions — design

Date: 2026-10-26
Scope: `app.py` (Streamlit CBA app). No other app version exists any more.

## Why

Project teams use this app to appraise **road upgrade projects**. Their results then
go to **assurance reviews**, which check them against the TfNSW CBA Guide (August 2024)
and NSW Treasury TPG23-08. A review comparing the app against those guides found
five gaps. This design closes them.

The point is that a project team can produce every number the guides require from
the app, and a reviewer can confirm each required test was run without re-running
anything.

## Goals

1. Discount rate sensitivity at **3%, 4% and 7%**, alongside the central rate (default 5%).
2. The full TfNSW sensitivity set (Guide §4.2.12), shown in one table.
3. **P50 / P90** capital costs, entered as yearly cashflows, with P50 in the core result
   and P90 as a sensitivity.
4. **Upfront (embodied) carbon** from construction, valued and included in the CBA.
5. **Base case costs**, and project recurrent costs including periodic maintenance and
   renewals, entered as yearly cashflows.

## Non-goals

- Importing estimate Excel files directly. The user will share a sample later;
  pasting a row from Excel into the yearly tables is enough for now.
- Distributional analysis, qualitative impacts and other report-only content.
- Public transport benefits (crowding, fare revenue, transfer time).
- Changes to how benefits are calculated, except where a sensitivity test needs it.

## Anti-goals (would be a failure even if it works)

- A reviewer can't tell from the Sensitivity tab whether a required test was run.
- Contingency gets counted twice (for example, a P50 total plus a contingency % on top).
- Avoided base case maintenance is counted twice (the old pavement savings input
  alongside the new base case costs).
- Totals get silently spread evenly over years. The user explicitly does not want an
  automatic "spread evenly" feature.

## Constraints

- All costs are in **real terms** (June 2024 prices), as the rest of the app.
- Streamlit app; data entry follows the existing pattern (`st.data_editor`, which
  supports pasting from Excel).
- `PARAMS` is never mutated; use `build_effective_params()`.
- Discounting stays start-of-year: `1/(1+r)^t`.
- No automated test suite exists. Verification uses Streamlit `AppTest` headless runs
  and hand-checked numbers, as done for recent fixes.

## Decisions

Marked **(user)** where the user decided, **(builder call)** where I decided and the
user did not object or has not yet been asked.

### Timeline

- Year columns run from `construction_start_year` through the end of the appraisal
  period: `const_years + eval_period` years. This matches `calculate_matrix` today.
- The appraisal period counts from opening (TfNSW default 30 years). The sidebar help
  text currently says it includes construction; fix the text, not the maths.
- When the construction period, start year or appraisal period changes, the cost tables
  are padded with zeros or trimmed to the new years, without losing entered values
  (same approach as the crash data fix in commit `1ff963f`).

### Item 3 — Capital costs, P50 / P90 (user)

Per project option, yearly tables over the **construction years**:

| Row | Meaning |
|---|---|
| Planning & design (base) | Base estimate, no contingency |
| Land (base) | Base estimate |
| Construction (base) | Base estimate |
| Contingency to P50 | Amount by year that takes the base to P50 |
| Contingency to P90 | Amount by year that takes the base to P90 |

- P50 capital by year = sum of the base rows + P50 contingency. P90 = base + P90 contingency. **(user)**
- The core result uses P50. P90 is a sensitivity. **(user, per TfNSW Guide)**
- No contingency % field and no "spread evenly" button. **(user)**
- **Residual value** keeps today's rule: land keeps full value, construction depreciates
  straight-line over asset life, planning has none. Contingency is attributed to the
  three categories pro rata to their base totals. **(builder call)**
- The manual residual override stays.

### Item 5 — Recurrent costs and base case costs (user)

- Per project option: one **recurrent cost** row by year over the whole timeline
  (operations, maintenance and periodic renewals together). **(user: yearly cashflows)**
- Base case: one **recurrent cost** row by year over the whole timeline, shared by all
  options. **(user)**
- P90 applies to capital only; recurrent costs are a single estimate. **(builder call)**
- **Avoided base case costs are a benefit**, shown as their own line ("Avoided base case
  costs"). Project capital and recurrent costs are the costs. This follows TfNSW Guide
  Table 6, which lists avoided capital and recurrent costs as Government benefits. NPV
  is unchanged by this choice; BCR differs. **(builder call)**
- The **pavement maintenance savings** input is removed, because base case recurrent
  costs replace it. **(builder call)**
- **Construction years:** the project recurrent row covers construction years too, and
  users enter the cost of maintaining the existing road during construction there. The
  table's help text says so. The "Avoided base case costs" benefit is the base row in
  every year and the project row is a cost in every year, so in construction years where
  the two rows are equal the net effect is zero: a project that keeps maintaining the
  existing road during construction gets no credit for those years. The sample data
  follows this.
  **(builder call)**
- **Construction-phase traffic disruption** moves from costs to a **disbenefit** line,
  "Construction disruption", per TfNSW Guide Table 6. The input itself is unchanged.
  **(builder call, consistent with upfront carbon and avoided costs)**

### Item 4 — Upfront carbon (user)

- Per project option: one input, **upfront carbon (tCO₂e)**. **(user: teams arrive with
  tonnes of CO₂e)**
- Spread across the construction years in proportion to the P50 capital cashflow.
  **(builder call)**
- Valued at the app's carbon price (`PARAMS["carbon_per_tonne"]`, $123/t) and included in
  the existing carbon price sensitivity, so Treasury's $135.74/t test also covers it.
  **(builder call)**
- Reported as a **disbenefit** line, "Upfront carbon emissions" (negative benefit), per
  TfNSW Guide Table 6 ("cost of carbon emissions" under disbenefits). **(builder call —
  earlier in conversation this was described as a cost line; corrected to match the
  guide)**

### Items 1 and 2 — Required sensitivity table

A single table, **"TfNSW required sensitivity tests"**, at the top of the Sensitivity tab,
per option. Each row shows PV benefits, PV costs, NPV and BCR, and the central row is
highlighted.

| Test | Definition |
|---|---|
| Central | As entered (P50, central discount rate) |
| Discount rate 3% / 4% / 7% | Same cashflows, different rate. Always shown regardless of the central rate. 4% is for federal (PPR) submissions. |
| Costs +20% / −20% / +40% / −40% | Scale all project costs (capital at P50 and recurrent). The auto-calculated residual value scales with capital, since it is a share of capital. **(builder call)** |
| Benefits +20% / −20% / +40% / −40% | Scale transport benefits. Residual value, avoided base case costs, upfront carbon and construction disruption are not scaled. **(builder call)** |
| P90 capital cost | Capital = base + P90 contingency in every year; auto-calculated residual value recalculated. |
| Opening delayed 1 year / 3 years | See below. |
| No traffic growth | Base and project traffic held at opening-year values for every year. |
| Half traffic growth | Base and project traffic grow from opening at half the forecast annual growth rate, per vehicle type, for VHT and VKT. |

A **manual residual override**, if set, is kept unchanged in every test: it is the
user's explicit value. **(builder call)**

**Opening delay (user):** the construction period stays the same length; the project is
delayed by N years before construction (development delay). The whole capital cashflow
(base and contingency rows) and the upfront carbon move N years later, with the same
shape and total. Opening, benefits and the project recurrent row (including its
construction-year values) also move N years later. During the N delay years the existing
road is still maintained, so the project option carries the base case recurrent cost
for those years (no avoided-cost credit). The appraisal period stays 30 years from the
new opening date. Where a cost row needs values beyond the entered
years, the last entered year's value repeats. Benefits are **recalculated for the actual
delayed calendar years** (traffic is entered by calendar year), not the central benefit
profile shifted, because that is what re-running the appraisal with a later opening
would give. **(builder call)**

- The old discount-rate rows (3.5% and 10%) and the old "Demand ±20%" rows are removed
  from the Scenario Analysis table. They are replaced by the new table.
- The existing discount-rate chart switches to 3 / 4 / 5 / 7.
- The carbon price, VSL, WEBs and Monte Carlo sections stay as they are.

### Reporting

- A **summary table** per option in the shape the TfNSW Guide asks for: P50 and P90
  outturn capital, PV capital, PV recurrent costs, PV benefits, BCR and NPV.
- **Outturn costs are nominal (user).** Per option, two reporting-only inputs: **P50
  outturn capital (nominal $M)** and **P90 outturn capital (nominal $M)**, copied from the
  estimate file. They appear in the summary table (and CSV) exactly as entered, labelled
  nominal, and are **never used in any calculation**. Every other figure stays real.
  If left blank, the table shows "not entered" so a reviewer can see the gap.
- The itemised PV of each benefit and cost line, including the new lines (avoided base
  case costs, upfront carbon).
- The Cashflow tab shows the new cost lines by year.
- CSV export includes the summary table and the required sensitivity table.

### Data, save and load

- `cost_data` gets the new yearly fields. The old fields (`cap_planning`, `cap_land`,
  `cap_construction`, `contingency_pct`, `opex_maint`, `opex_op`,
  `pavement_saving_annual`) are removed.
- A new `base_case_costs` key (recurrent row) is added and saved with the project.
- The sample data is rewritten as yearly cashflows: a construction S-curve for capital,
  P50 and P90 contingency rows, recurrent rows with a periodic resurfacing spike in both
  cases, and a sample upfront carbon figure. Total P50 capital stays around $350M
  (commit `78405b5`).
- The Monte Carlo cost factor applies to P50 construction capital (base + P50
  contingency), as it applies to `cap_construction` today.
- **Old saved projects are not supported (user).** Saved files get a cost-format
  version number. Opening a file without the new format shows a clear error ("saved in
  an older format and can't be opened; please re-enter it") and loads nothing. No
  conversion or migration code. The earlier compatibility shim for files saved before
  Rule-of-Half (`cd.setdefault("generated_demand_pct_override", ...)`) is removed too.

## Left to the builder

- Table layout, labels and widget keys, following existing patterns.
- The exact half-growth formula, provided it halves the annual growth rate from the
  opening year.
- Refactoring `calculate_matrix` so the sensitivity tests can re-run it with modified
  inputs, rather than scaling outputs, where scaling outputs is not exact (delay,
  growth, P90).
- Performance: the required table needs about 16 extra runs per option. Cache as the main
  calculation is cached.
