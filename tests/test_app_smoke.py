"""Headless smoke test of the Streamlit app."""
import os

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _metric(at, label):
    matches = [m for m in at.metric if m.label == label]
    assert matches, f"metric {label!r} not found; have {[m.label for m in at.metric]}"
    return matches[0].value


def _number_input(at, label):
    [widget] = [w for w in at.number_input if w.label == label]
    return widget


def _app_with_sample():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not at.exception
    at.checkbox(key="confirm_load_sample").check().run()
    [btn] = [b for b in at.button if b.label == "Load Sample Data"]
    btn.click().run()
    assert not at.exception
    return at


def test_sample_data_runs():
    at = _app_with_sample()
    assert _metric(at, "PV Costs")
    assert _metric(at, "Benefit-Cost Ratio") == "1.69"
    assert _metric(at, "P50 capital ($M, real)") == "$350.0M"
    assert _metric(at, "P90 capital ($M, real)") == "$383.0M"
    cost = at.session_state["cost_data"]["project_1"]
    assert cost["upfront_carbon_t"] == 45000.0
    assert cost["outturn_p50_nominal"] == 395.0


def test_change_construction_years_keeps_costs():
    at = _app_with_sample()
    _number_input(at, "Construction Period (years)").set_value(4).run()
    assert not at.exception
    cost = at.session_state["cost_data"]["project_1"]
    assert cost["capex_base"]["construction"] == [60.0, 120.0, 80.0, 0.0]
    assert len(cost["recurrent"]) == 34
    assert len(at.session_state["base_case_costs"]["recurrent"]) == 34


def test_two_options_share_base_costs():
    at = _app_with_sample()
    base_before = list(at.session_state["base_case_costs"]["recurrent"])
    _number_input(at, "Number of Project Cases").set_value(2).run()
    assert not at.exception
    assert at.session_state["base_case_costs"]["recurrent"] == base_before
    assert len(base_before) == 33
    assert len(at.session_state["cost_data"]["project_2"]["recurrent"]) == 33


def test_empty_project_no_errors():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not at.exception
    assert not at.error
    assert _metric(at, "P50 capital ($M, real)") == "$0.0M"
