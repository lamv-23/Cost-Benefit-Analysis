"""Regression tests pinning current behaviour of cba_engine."""
import copy

import pytest

from cba_engine import (
    PARAMS, VTYPES, calculate_matrix, interpolate_modelling_years, make_cost_data,
)
from conftest import make_case_traffic

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
    cost = make_cost_data(1)["project_1"]
    cost.update(cost_overrides or {})
    sv_base = dict(PARAMS["safety_vkt"])
    sv_p = dict(sv_base)
    if sv_proj:
        sv_p.update(sv_proj)
    return calculate_matrix(
        INPUTS, base, proj, cost, ANNUALISATION, sv_base, sv_p, PARAMS,
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
