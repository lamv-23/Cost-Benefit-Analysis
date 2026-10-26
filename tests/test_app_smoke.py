"""Headless smoke test of the Streamlit app."""
import io
import os

import streamlit
from streamlit.elements.lib import policies
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


def test_save_load_round_trip_keeps_periods(monkeypatch):
    """Save at a 4-year construction period, open in a fresh session (default 3).

    AppTest cannot drive file uploads, so the save button's data is captured
    and handed back once through the project uploader.
    """
    saved = {}
    real_download, real_uploader = streamlit.download_button, streamlit.file_uploader

    def capture_download(label, data, *args, **kwargs):
        if label == "Save Project (.json)":
            saved["json"] = data
        return real_download(label, data, *args, **kwargs)

    monkeypatch.setattr(streamlit, "download_button", capture_download)
    at = _app_with_sample()
    _number_input(at, "Construction Period (years)").set_value(4).run()
    _number_input(at, "Construction Start Year").set_value(2027).run()
    cost = at.session_state["cost_data"]["project_1"]
    cost["capex_base"]["construction"] = [60.0, 120.0, 80.0, 40.0]
    at.session_state["cost_data"] = at.session_state["cost_data"]
    at.run()  # the save button now holds the 4-year rows
    assert not at.exception
    payload = saved["json"]

    pending = [payload]

    def upload_once(label, *args, **kwargs):
        if kwargs.get("key") == "load_project_uploader" and pending:
            real_uploader(label, *args, **kwargs)
            return io.BytesIO(pending.pop().encode("utf-8"))
        return real_uploader(label, *args, **kwargs)

    monkeypatch.setattr(streamlit, "file_uploader", upload_once)
    monkeypatch.setattr(policies, "_shown_default_value_warning", False)
    fresh = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not fresh.exception
    assert not fresh.error
    assert not [w for w in fresh.warning if "default value" in w.value]
    assert fresh.session_state["const_years"] == 4
    assert fresh.session_state["eval_period"] == 30
    assert fresh.session_state["construction_start_year"] == 2027
    loaded = fresh.session_state["cost_data"]["project_1"]
    assert loaded["capex_base"]["construction"] == [60.0, 120.0, 80.0, 40.0]
    assert len(loaded["recurrent"]) == 34
    assert loaded["recurrent"][12] == 8.2 and loaded["recurrent"][33] == 0.0
    assert _metric(fresh, "P50 capital ($M, real)") == "$390.0M"


def test_sensitivity_table_present():
    at = _app_with_sample()
    assert not at.exception
    labels = [
        "Central", "Discount rate 3%", "Discount rate 4%", "Discount rate 7%",
        "Costs +20%", "Costs \u221220%", "Costs +40%", "Costs \u221240%",
        "Benefits +20%", "Benefits \u221220%", "Benefits +40%", "Benefits \u221240%",
        "P90 capital cost", "Opening delayed 1 year", "Opening delayed 3 years",
        "No traffic growth", "Half traffic growth",
    ]
    found = []
    for df in at.dataframe:
        frame = df.value
        if "Test" in frame.columns:
            found.append(list(frame["Test"]))
        else:
            found.append(list(frame.index))
    assert any(all(label in names for label in labels) for names in found), found


def _dr_chart_labels(at):
    import json
    for el in at.get("plotly_chart"):
        for trace in json.loads(el.proto.spec)["data"]:
            x = trace.get("x")
            if trace.get("type") == "bar" and x is not None and str(x[0]).endswith("%"):
                return list(x)
    raise AssertionError("discount-rate chart not found")


def test_discount_rate_chart_has_no_duplicate_points():
    at = _app_with_sample()
    assert _dr_chart_labels(at) == ["3%", "4%", "5%", "7%"]
    _number_input(at, "Discount Rate (%)").set_value(7.0).run()
    assert not at.exception
    assert _dr_chart_labels(at) == ["3%", "4%", "7%"]
    frames = [d.value for d in at.dataframe if "Test" in d.value.columns]
    assert len(frames[0]) == 17


def test_dashboard_summary():
    at = _app_with_sample()
    assert not at.exception
    key = "P50 outturn capital (nominal $M)"
    frames = [d.value for d in at.dataframe if key in list(d.value.index)]
    assert frames, "appraisal summary table not found"
    assert list(frames[0].columns) == ["Project 1"]
    assert frames[0].loc[key, "Project 1"] == "395.0"
    assert frames[0].loc["P90 outturn capital (nominal $M)", "Project 1"] == "432.0"

