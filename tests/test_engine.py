"""Regression tests pinning current behaviour of cba_engine."""
import copy

import pytest

from cba_engine import (
    PARAMS, VTYPES, build_cost_schedule, calculate_matrix, clean_row, fit_cost_rows,
    interpolate_modelling_years, make_base_case_costs, make_cost_data,
    validate_project_file,
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
