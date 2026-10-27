"""Regression tests pinning current behaviour of cba_engine."""
import copy

import pytest

from cba_engine import (
    PARAMS, VTYPES, appraisal_summary, build_cost_schedule, calculate_matrix, clean_row,
    fit_cost_rows, generate_csv,
    interpolate_modelling_years, make_base_case_costs, make_cost_data,
    run_required_sensitivities, validate_project_file,
)
from conftest import fixture_costs, make_case_traffic

YEARS = [2026, 2056]
INPUTS = {
    "context": "rural",
    "evaluation_period": 30,
    "construction_years": 2,
    "discount_rate": 7,
    "construction_start_year": 2026,
    "discount_base_year": 2026,
}
ANNUALISATION = {vt: {"factor": 1.0, "days": 1} for vt in VTYPES}


def _run(base, proj, sv_proj=None, cost_overrides=None):
    cost = make_cost_data(1, 2, 30)["project_1"]
    cost.update(cost_overrides or {})
    sv_base = dict(PARAMS["safety_vkt"])
    sv_p = dict(sv_base)
    if sv_proj:
        sv_p.update(sv_proj)
    return calculate_matrix(
        INPUTS, base, proj, cost, make_base_case_costs(2, 30), ANNUALISATION,
        sv_base, sv_p, PARAMS,
    )["first_year"]


def _dollars(value):
    return round(value * 1e6, 2)


def _car(vht, vkt):
    return make_case_traffic(YEARS, Car={"vht": vht, "vkt": vkt})


def test_voc_uses_total_cost_difference():
    fy = _run(_car([1000, 1000], [60000, 60000]), _car([750, 750], [60000, 60000]))
    assert _dollars(fy["voc"]) == 720.0


def test_safety_uses_rate_difference():
    fy = _run(_car([1000, 1000], [60000, 60000]), _car([750, 750], [60000, 60000]),
              sv_proj={"Car": 0.100})
    assert _dollars(fy["safety"]) == 3180.0


def test_safety_shorter_route_same_rate():
    fy = _run(_car([1000, 1000], [60000, 60000]), _car([950, 950], [55000, 55000]))
    assert _dollars(fy["safety"]) == 765.0


def test_disbenefit_not_clamped():
    base = make_case_traffic(YEARS, HCV={"vht": [100, 100], "vkt": [8000, 8000]})
    proj = make_case_traffic(YEARS, HCV={"vht": [120, 120], "vkt": [8000, 8000]})
    fy = _run(base, proj)
    assert _dollars(fy["tts"]) == -987.6


def test_interpolation_from_zero():
    assert interpolate_modelling_years([2026, 2056], [0.0, 100.0], 2056) == 100.0
    assert interpolate_modelling_years([2026, 2056], [0.0, 100.0], 2041) == 50.0


def test_rule_of_half_user_benefits_only():
    base = _car([1000, 1000], [60000, 60000])
    proj = _car([800, 800], [64000, 64000])
    fy0 = _run(base, copy.deepcopy(proj))
    fy100 = _run(base, copy.deepcopy(proj), cost_overrides={"generated_demand_pct_global": 100})
    for key in ("tts", "reliability", "voc"):
        assert fy0[key] != 0
        assert fy100[key] == pytest.approx(0.5 * fy0[key])
    for key in ("safety", "env"):
        assert fy0[key] != 0
        assert fy100[key] == pytest.approx(fy0[key])


# ── Yearly cost data model and cost schedule ─────────────────────────────────

def test_schedule_p50():
    cost, base = fixture_costs()
    s = build_cost_schedule(cost, base, 2, 3)
    assert s["capital"] == [8.0, 5.0, 0, 0, 0] and s["capital_total"] == 13.0
    assert s["capital_by_category"]["land"] == pytest.approx(2.363636, abs=1e-6)
    assert s["capital_by_category"]["construction"] == pytest.approx(9.454545, abs=1e-6)
    assert s["upfront_carbon_t"][:2] == pytest.approx([615.384615, 384.615385])
    assert s["construction_years"] == [True, True, False, False, False]
    assert s["project_recurrent"] == [0.5, 0.5, 1.0, 1.0, 1.0]
    assert s["base_recurrent"] == [0.5, 0.5, 0.8, 0.8, 0.8]


def test_schedule_p90():
    cost, base = fixture_costs()
    s = build_cost_schedule(cost, base, 2, 3, capital="p90")
    assert s["capital"] == [9.0, 6.0, 0, 0, 0]
    assert s["capital_total"] == 15.0
    # carbon split is by P50 capital, so unchanged
    assert s["upfront_carbon_t"][:2] == pytest.approx([615.384615, 384.615385])


def test_schedule_delay_1():
    cost, base = fixture_costs()
    s = build_cost_schedule(cost, base, 2, 3, delay_years=1)
    assert s["capital"] == [0, 8.0, 5.0, 0, 0, 0]
    assert s["project_recurrent"] == [0.5, 0.5, 0.5, 1.0, 1.0, 1.0]
    assert s["base_recurrent"] == [0.5, 0.5, 0.8, 0.8, 0.8, 0.8]
    assert s["upfront_carbon_t"][0] == 0
    assert s["construction_years"] == [False, True, True, False, False, False]


def test_schedule_zero_capital():
    cost, base = fixture_costs()
    for row in cost["capex_base"].values():
        row[:] = [0.0, 0.0]
    cost["contingency_p50"] = [0.0, 0.0]
    cost["contingency_p90"] = [0.0, 0.0]
    s = build_cost_schedule(cost, base, 2, 3)
    assert s["capital_total"] == 0
    assert s["upfront_carbon_t"] == [1000.0, 0, 0, 0, 0]
    s1 = build_cost_schedule(cost, base, 2, 3, delay_years=1)
    assert s1["upfront_carbon_t"][1] == 1000.0


def test_fit_cost_rows_pads_and_trims():
    cost, base = fixture_costs()
    fit_cost_rows(cost, 3, 3)
    assert cost["capex_base"]["planning"] == [1.0, 0.0, 0.0]
    assert cost["contingency_p50"] == [1.0, 1.0, 0.0]
    assert len(cost["recurrent"]) == 6
    fit_cost_rows(cost, 3, 2)
    assert len(cost["recurrent"]) == 5
    fit_cost_rows(cost, 2, 2)
    assert cost["capex_base"]["planning"] == [1.0, 0.0]
    assert len(cost["recurrent"]) == 4
    fit_cost_rows(base, 2, 2)
    assert len(base["recurrent"]) == 4
    fit_cost_rows({}, 2, 2)  # absent keys are ignored


def test_clean_row():
    assert clean_row([1, None, float("nan"), "", "2.5"]) == [1.0, 0.0, 0.0, 0.0, 2.5]


def test_make_cost_data_no_shared_rows():
    data = make_cost_data(2, 3, 10)
    assert len(data["project_1"]["recurrent"]) == 13
    assert len(data["project_1"]["capex_base"]["land"]) == 3
    data["project_1"]["recurrent"][0] = 9.0
    data["project_1"]["generated_demand_pct_override"]["Car"] = 5.0
    data["project_1"]["capex_base"]["land"][0] = 1.0
    assert data["project_2"]["recurrent"][0] == 0.0
    assert data["project_2"]["generated_demand_pct_override"]["Car"] is None
    assert data["project_2"]["capex_base"]["land"][0] == 0.0
    assert make_base_case_costs(3, 10) == {"recurrent": [0.0] * 13}


# ── Yearly costs in calculate_matrix ─────────────────────────────────────────

COST_INPUTS = {
    "context": "rural",
    "evaluation_period": 3,
    "construction_years": 2,
    "discount_rate": 0,
    "construction_start_year": 2026,
    "discount_base_year": 2026,
}


def _run_costs(**cost_overrides):
    cost, base = fixture_costs()
    cost["construction_asset_life"] = 40
    cost.update(cost_overrides)
    traffic = make_case_traffic(YEARS)
    return calculate_matrix(
        COST_INPUTS, traffic, copy.deepcopy(traffic), cost, base, ANNUALISATION,
        params=PARAMS,
    )


def test_central_costs_and_lines():
    r = _run_costs()
    assert r["pv_capital"] == pytest.approx(13.0)
    assert r["pv_recurrent"] == pytest.approx(4.0)
    assert r["pv_costs"] == pytest.approx(17.0)
    assert r["pv_by_type"]["avoided_costs"] == pytest.approx(3.4)
    assert r["pv_by_type"]["upfront_carbon"] == pytest.approx(-0.123)
    assert r["pv_by_type"]["residual"] == pytest.approx(11.109091, abs=1e-6)
    assert r["pv_benefits"] == pytest.approx(14.386091, abs=1e-6)
    assert r["bcr"] == pytest.approx(0.846241, abs=1e-6)
    assert r["capital_p50_total"] == pytest.approx(13.0)
    assert r["capital_p90_total"] == pytest.approx(15.0)
    assert "pavement" not in r["benefits_by_type"]


def test_construction_disruption_is_disbenefit():
    r = _run_costs(construction_disbenefit_annual=0.2)
    assert r["pv_by_type"]["construction_disruption"] == pytest.approx(-0.4)
    assert r["benefits_by_type"]["construction_disruption"] == pytest.approx(
        [-0.2, -0.2, 0.0, 0.0, 0.0])
    assert r["pv_costs"] == pytest.approx(17.0)


def test_manual_residual_override():
    r = _run_costs(residual=5.0)
    assert r["pv_by_type"]["residual"] == pytest.approx(5.0)
    assert r["residual"] == pytest.approx(5.0)


def test_validate_project_file():
    msg = ("This project file was saved in an older format and can't be opened. "
           "Please re-enter the project.")
    assert validate_project_file({}) == msg
    assert validate_project_file({"type": "cba_project"}) == msg
    assert validate_project_file({"type": "cba_project", "cost_format": 2}) is None


def test_carbon_sensitivity_includes_upfront_carbon():
    r = _run_costs()
    high = r["sensitivity_carbon"]["High (2.0×, $246/t)"]
    # upfront carbon -0.123 doubles to -0.246; no traffic, so no other carbon
    assert high["pvb"] == pytest.approx(r["pv_benefits"] - 0.123)


# ── Scenario options in calculate_matrix ─────────────────────────────────────

def _run_scenario(scenario=None, traffic=None, **cost_overrides):
    cost, base = fixture_costs()
    cost["construction_asset_life"] = 40
    cost.update(cost_overrides)
    base_traffic, proj_traffic = traffic or (
        make_case_traffic(YEARS), make_case_traffic(YEARS))
    return calculate_matrix(
        COST_INPUTS, base_traffic, proj_traffic, cost, base, ANNUALISATION,
        params=PARAMS, scenario=scenario,
    )


def _saving_traffic():
    """Car VHT/VKT that make a growing travel time saving (project is faster)."""
    base = make_case_traffic(YEARS, Car={"vht": [1000, 2000], "vkt": [60000, 120000]})
    proj = make_case_traffic(YEARS, Car={"vht": [800, 1200], "vkt": [60000, 120000]})
    return base, proj


def test_scenario_none_matches_empty_dict():
    traffic = _saving_traffic()
    central = _run_scenario(traffic=traffic)
    explicit = _run_scenario({}, traffic=traffic)
    assert explicit["pv_benefits"] == central["pv_benefits"]
    assert explicit["pv_costs"] == central["pv_costs"]
    assert explicit["benefits_by_type"] == central["benefits_by_type"]


def test_scenario_p90():
    r = _run_scenario({"capital": "p90"})
    assert r["pv_costs"] == pytest.approx(19.0)
    assert r["pv_by_type"]["residual"] == pytest.approx(12.818182, abs=1e-6)
    assert r["capital_p50_total"] == pytest.approx(13.0)
    assert r["capital_p90_total"] == pytest.approx(15.0)


def test_scenario_cost_factor():
    r = _run_scenario({"cost_factor": 1.2})
    assert r["pv_costs"] == pytest.approx(20.4)
    assert r["pv_by_type"]["residual"] == pytest.approx(13.330909, abs=1e-6)
    assert r["pv_by_type"]["avoided_costs"] == pytest.approx(3.4)


def test_scenario_cost_factor_keeps_manual_residual():
    r = _run_scenario({"cost_factor": 1.4}, residual=5.0)
    assert r["pv_by_type"]["residual"] == pytest.approx(5.0)
    assert r["residual"] == pytest.approx(5.0)


def test_scenario_benefit_factor():
    traffic = _saving_traffic()
    central = _run_scenario(traffic=traffic, walk_pkm_day=1000.0,
                            construction_disbenefit_annual=0.2)
    r = _run_scenario({"benefit_factor": 1.4}, traffic=traffic, walk_pkm_day=1000.0,
                      construction_disbenefit_annual=0.2)
    assert central["pv_by_type"]["tts"] > 0
    for key in ("tts", "reliability", "voc", "safety", "env", "active", "tts_Car"):
        assert r["pv_by_type"][key] == pytest.approx(1.4 * central["pv_by_type"][key])
    for key in ("avoided_costs", "upfront_carbon", "construction_disruption", "residual"):
        assert r["pv_by_type"][key] == pytest.approx(central["pv_by_type"][key])
    assert r["pv_costs"] == pytest.approx(central["pv_costs"])


def test_scenario_delay_1():
    r = _run_scenario({"delay_years": 1})
    assert r["pv_costs"] == pytest.approx(17.5)
    assert r["pv_by_type"]["avoided_costs"] == pytest.approx(4.2)
    assert r["pv_benefits"] == pytest.approx(15.186091, abs=1e-6)
    assert r["total_years"] == 6


def test_scenario_delay_uses_later_traffic():
    traffic = _saving_traffic()
    central = _run_scenario(traffic=traffic)
    delayed = _run_scenario({"delay_years": 1}, traffic=traffic)
    tts = delayed["benefits_by_type"]["tts"]
    assert tts[:3] == [0.0, 0.0, 0.0]
    assert tts[3] > 0
    assert tts[3] == pytest.approx(central["benefits_by_type"]["tts"][3])
    assert tts[3] != pytest.approx(central["benefits_by_type"]["tts"][2])
    assert delayed["first_year"]["tts"] == pytest.approx(tts[3])


def test_scenario_no_growth():
    traffic = _saving_traffic()
    central = _run_scenario(traffic=traffic)
    r = _run_scenario({"growth": "none"}, traffic=traffic)
    tts = r["benefits_by_type"]["tts"]
    assert tts[2] > 0
    assert tts[2:] == pytest.approx([tts[2]] * 3)
    assert tts[2] == pytest.approx(central["benefits_by_type"]["tts"][2])
    assert central["benefits_by_type"]["tts"][4] > central["benefits_by_type"]["tts"][2]


def test_scenario_half_growth():
    inputs = dict(COST_INPUTS, evaluation_period=30)
    cost = make_cost_data(1, 2, 30)["project_1"]
    base = make_case_traffic(YEARS, Car={"vht": [1000, 2000]})
    proj = make_case_traffic(YEARS)  # zero VHT: the saving equals the base VHT
    r = calculate_matrix(
        inputs, base, proj, cost, make_base_case_costs(2, 30), ANNUALISATION,
        params=PARAMS, scenario={"growth": "half"},
    )
    tts = r["benefits_by_type"]["tts_Car"]
    v0 = tts[2]
    n = 10
    g = (interpolate_modelling_years(YEARS, [1000, 2000], 2038)
         / interpolate_modelling_years(YEARS, [1000, 2000], 2028)) ** (1 / n) - 1
    assert v0 > 0
    assert tts[2 + n] == pytest.approx(v0 * (1 + g / 2) ** n, rel=1e-9)
    full = calculate_matrix(
        inputs, base, proj, cost, make_base_case_costs(2, 30), ANNUALISATION,
        params=PARAMS,
    )["benefits_by_type"]["tts_Car"]
    assert tts[2 + n] < full[2 + n]


def test_scenario_discount_rate():
    traffic = _saving_traffic()
    scenario = _run_scenario({"discount_rate": 7}, traffic=traffic)
    cost, base = fixture_costs()
    cost["construction_asset_life"] = 40
    central = calculate_matrix(
        dict(COST_INPUTS, discount_rate=7), traffic[0], traffic[1], cost, base,
        ANNUALISATION, params=PARAMS,
    )
    assert scenario["npv"] == pytest.approx(central["npv"], rel=1e-9)
    assert scenario["bcr"] == pytest.approx(central["bcr"], rel=1e-9)
    assert scenario["dr"] == 7
    assert _run_scenario(traffic=traffic)["dr"] == 0


# ── Required sensitivity table ───────────────────────────────────────────────

REQUIRED_LABELS = [
    "Central", "Discount rate 3%", "Discount rate 4%", "Discount rate 7%",
    "Costs +20%", "Costs \u221220%", "Costs +40%", "Costs \u221240%",
    "Benefits +20%", "Benefits \u221220%", "Benefits +40%", "Benefits \u221240%",
    "P90 capital cost", "Opening delayed 1 year", "Opening delayed 3 years",
    "No traffic growth", "Half traffic growth",
]


def _required_rows(discount_rate=0):
    cost, base = fixture_costs()
    cost["construction_asset_life"] = 40
    base_traffic, proj_traffic = _saving_traffic()
    inputs = dict(COST_INPUTS, discount_rate=discount_rate)
    rows = run_required_sensitivities(
        inputs, base_traffic, proj_traffic, cost, base, ANNUALISATION, params=PARAMS)
    central = calculate_matrix(
        inputs, base_traffic, proj_traffic, cost, base, ANNUALISATION, params=PARAMS)
    return rows, central, (inputs, base_traffic, proj_traffic, cost, base)


def test_required_rows_order_and_central():
    rows, central, _ = _required_rows()
    assert [r["test"] for r in rows] == REQUIRED_LABELS
    assert [r["central"] for r in rows] == [True] + [False] * 16
    assert rows[0]["npv"] == pytest.approx(central["npv"], rel=1e-9)
    assert rows[0]["bcr"] == pytest.approx(central["bcr"], rel=1e-9)
    for r in rows:
        assert set(r) == {"test", "pvb", "pvc", "npv", "bcr", "central"}
        assert r["npv"] == pytest.approx(r["pvb"] - r["pvc"])


def test_required_rows_match_scenarios():
    rows, _, (inputs, bt, pt, cost, base) = _required_rows()
    by = {r["test"]: r for r in rows}

    def run(scn):
        return calculate_matrix(inputs, bt, pt, cost, base, ANNUALISATION,
                                params=PARAMS, scenario=scn)

    for label, scn in [
        ("Costs +20%", {"cost_factor": 1.2}),
        ("Costs \u221240%", {"cost_factor": 0.6}),
        ("Benefits +40%", {"benefit_factor": 1.4}),
        ("Benefits \u221220%", {"benefit_factor": 0.8}),
        ("P90 capital cost", {"capital": "p90"}),
        ("Opening delayed 3 years", {"delay_years": 3}),
        ("No traffic growth", {"growth": "none"}),
        ("Half traffic growth", {"growth": "half"}),
        ("Discount rate 4%", {"discount_rate": 4}),
    ]:
        expected = run(scn)
        assert by[label]["pvc"] == pytest.approx(expected["pv_costs"]), label
        assert by[label]["pvb"] == pytest.approx(expected["pv_benefits"]), label
        assert by[label]["bcr"] == pytest.approx(expected["bcr"]), label
    assert by["Costs +20%"]["pvc"] != pytest.approx(by["Central"]["pvc"])
    assert by["P90 capital cost"]["pvc"] > by["Central"]["pvc"]


def test_required_rows_when_central_is_7():
    rows, central, _ = _required_rows(discount_rate=7)
    assert [r["test"] for r in rows] == REQUIRED_LABELS
    by = {r["test"]: r for r in rows}
    assert by["Discount rate 7%"]["npv"] == pytest.approx(by["Central"]["npv"], rel=1e-9)
    assert by["Central"]["npv"] == pytest.approx(central["npv"], rel=1e-9)
    assert sum(r["central"] for r in rows) == 1


def test_calculate_matrix_drops_old_scenario_tables():
    _, central, _ = _required_rows()
    assert "sensitivity_dr" not in central
    assert "scenarios" not in central


# ── Appraisal summary and CSV ────────────────────────────────────────────────

SUMMARY_KEYS = [
    "P50 outturn capital (nominal $M)", "P90 outturn capital (nominal $M)",
    "PV capital ($M)", "PV recurrent costs ($M)", "PV costs ($M)",
    "PV benefits ($M)", "NPV ($M)", "BCR",
]


def test_summary_outturn_not_entered():
    r = _run_costs()
    cost, _ = fixture_costs()
    cost["outturn_p50_nominal"] = None
    cost["outturn_p90_nominal"] = None
    s = appraisal_summary(r, cost)
    assert list(s) == SUMMARY_KEYS
    assert s["P50 outturn capital (nominal $M)"] == "not entered"
    assert s["P90 outturn capital (nominal $M)"] == "not entered"
    assert s["PV capital ($M)"] == r["pv_capital"]
    assert s["PV recurrent costs ($M)"] == r["pv_recurrent"]
    assert s["PV costs ($M)"] == r["pv_costs"]
    assert s["PV benefits ($M)"] == r["pv_benefits"]
    assert s["NPV ($M)"] == r["npv"]
    assert s["BCR"] == r["bcr"]


def test_summary_outturn_copied():
    r = _run_costs()
    s = appraisal_summary(r, {"outturn_p50_nominal": 395.0, "outturn_p90_nominal": 430.5})
    assert s["P50 outturn capital (nominal $M)"] == 395.0
    assert s["P90 outturn capital (nominal $M)"] == 430.5


def test_csv_sections():
    rows, central, (inputs, bt, pt, cost, base) = _required_rows()
    cost["outturn_p50_nominal"] = 395.0
    summary = appraisal_summary(central, cost)
    text = generate_csv(central, "Test project", summary, rows)
    assert "TfNSW required sensitivity tests" in text
    assert "Avoided base case costs" in text
    assert "P90 capital cost" in text
    assert "P50 outturn capital (nominal $M)" in text
    assert "395.0" in text
    assert "P90 outturn capital (nominal $M),not entered" in text
    assert "PV capital ($M)" in text and "PV recurrent costs ($M)" in text
    assert "Discounted net" in text and "Cumulative" in text
    assert text.index("Appraisal summary") < text.index("Itemised PV") \
        < text.index("TfNSW required sensitivity tests") < text.index("Cashflow by year")
    # one cashflow row per year
    assert text.count("\n") >= central["total_years"] + len(rows)
