"""Headless smoke test of the Streamlit app."""
import copy
import io
import json
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


class _FakeUpload(io.BytesIO):
    """Stand-in for Streamlit's UploadedFile: bytes plus a stable file_id."""

    def __init__(self, data, file_id):
        super().__init__(data)
        self.file_id = file_id


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
    assert _metric(at, "Net Present Value")
    assert _metric(at, "Benefit-Cost Ratio") == "1.69"
    labels = [m.label for m in at.metric]
    assert "Internal Rate of Return" not in labels
    assert "First Year Rate of Return" not in labels
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
    _number_input(at, "Number of options").set_value(2).run()
    assert not at.exception
    assert at.session_state["base_case_costs"]["recurrent"] == base_before
    assert len(base_before) == 33
    assert len(at.session_state["cost_data"]["project_2"]["recurrent"]) == 33


def test_adding_option_and_changing_years_keep_costs():
    at = _app_with_sample()
    before = copy.deepcopy(at.session_state["cost_data"]["project_1"])
    _number_input(at, "Number of options").set_value(2).run()
    assert not at.exception
    costs = at.session_state["cost_data"]
    assert costs["project_1"]["capex_base"] == before["capex_base"]
    assert costs["project_1"]["recurrent"] == before["recurrent"]
    assert costs["project_1"] == before
    p2 = costs["project_2"]
    assert all(len(row) == 3 for row in p2["capex_base"].values())
    assert len(p2["contingency_p50"]) == 3 and len(p2["contingency_p90"]) == 3
    assert len(p2["recurrent"]) == 33
    traffic_p1 = copy.deepcopy(at.session_state["traffic_data"]["project_1"])
    assert traffic_p1["Car"]["vht"] == [980.0, 1100.0, 1270.0, 1480.0]
    assert "project_2" in at.session_state["traffic_data"]

    at.text_input(key="modelling_years_widget").set_value("2026, 2031, 2041, 2061").run()
    assert not at.exception
    assert at.session_state["modelling_years"] == [2026, 2031, 2041, 2061]
    assert at.session_state["cost_data"]["project_1"] == before
    assert len(at.session_state["cost_data"]["project_2"]["recurrent"]) == 33


def test_option_change_keeps_periods():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    _number_input(at, "Construction Period (years)").set_value(5).run()
    _number_input(at, "Evaluation Period (years)").set_value(40).run()
    _number_input(at, "Construction Start Year").set_value(2030).run()
    _number_input(at, "Number of options").set_value(2).run()
    assert not at.exception
    assert at.session_state["const_years"] == 5
    assert at.session_state["eval_period"] == 40
    assert at.session_state["construction_start_year"] == 2030
    assert len(at.session_state["cost_data"]["project_1"]["recurrent"]) == 45
    assert len(at.session_state["cost_data"]["project_2"]["recurrent"]) == 45


def test_sample_resets_periods():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    _number_input(at, "Construction Period (years)").set_value(5).run()
    _number_input(at, "Evaluation Period (years)").set_value(40).run()
    _number_input(at, "Construction Start Year").set_value(2030).run()
    at.checkbox(key="confirm_load_sample").check().run()
    [btn] = [b for b in at.button if b.label == "Load Sample Data"]
    btn.click().run()
    assert not at.exception
    assert at.session_state["const_years"] == 3
    assert at.session_state["eval_period"] == 30
    assert at.session_state["construction_start_year"] == 2026
    assert _metric(at, "Benefit-Cost Ratio") == "1.69"


def test_empty_project_no_errors():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not at.exception
    assert not at.error
    assert _metric(at, "P50 capital ($M, real)") == "$0.0M"


def test_empty_state_loads_sample():
    """With nothing entered the Results tab offers the sample; the button loads it."""
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not [m for m in at.metric if m.label == "Benefit-Cost Ratio"]
    [btn] = [b for b in at.button if b.label == "Load sample project"]
    btn.click().run()
    assert not at.exception
    assert at.session_state["const_years"] == 3
    assert _metric(at, "Benefit-Cost Ratio") == "1.69"
    assert not [b for b in at.button if b.label == "Load sample project"]


def test_save_load_round_trip_keeps_periods(monkeypatch):
    """Save at a 4-year construction period, open in a fresh session (default 3).

    AppTest cannot drive file uploads, so the save button's data is captured
    and handed back through the project uploader on every run, as a real
    uploader keeps returning the file until it is removed.
    """
    saved = _capture_saves(monkeypatch)
    at = _app_with_sample()
    _number_input(at, "Construction Period (years)").set_value(4).run()
    _number_input(at, "Construction Start Year").set_value(2027).run()
    cost = at.session_state["cost_data"]["project_1"]
    cost["capex_base"]["construction"] = [60.0, 120.0, 80.0, 40.0]
    at.session_state["cost_data"] = at.session_state["cost_data"]
    at.run()  # the save button now holds the 4-year rows
    assert not at.exception
    fresh = _open_in_fresh_app(monkeypatch, saved[-1], file_id="saved-project-1")
    assert fresh.session_state["const_years"] == 4
    assert fresh.session_state["eval_period"] == 30
    assert fresh.session_state["construction_start_year"] == 2027
    loaded = fresh.session_state["cost_data"]["project_1"]
    assert loaded["capex_base"]["construction"] == [60.0, 120.0, 80.0, 40.0]
    assert len(loaded["recurrent"]) == 34
    assert loaded["recurrent"][12] == 8.2 and loaded["recurrent"][33] == 0.0
    assert _metric(fresh, "P50 capital ($M, real)") == "$390.0M"

    # The file is still in the uploader; later edits must not be reverted by it.
    _number_input(fresh, "Construction Period (years)").set_value(5).run()
    assert not fresh.exception
    assert fresh.session_state["const_years"] == 5
    loaded = fresh.session_state["cost_data"]["project_1"]
    assert loaded["capex_base"]["construction"] == [60.0, 120.0, 80.0, 40.0, 0.0]
    assert len(loaded["recurrent"]) == 35


def _capture_saves(monkeypatch):
    """Record every 'Save Project (.json)' payload the app renders."""
    saved = []
    real_download = streamlit.download_button

    def capture_download(label, data, *args, **kwargs):
        if label == "Save Project (.json)":
            saved.append(data)
        return real_download(label, data, *args, **kwargs)

    monkeypatch.setattr(streamlit, "download_button", capture_download)
    return saved


def _open_in_fresh_app(monkeypatch, payload, file_id):
    """Load a saved payload into a new session through the project uploader."""
    real_uploader = streamlit.file_uploader

    def upload_always(label, *args, **kwargs):
        if kwargs.get("key") == "load_project_uploader":
            real_uploader(label, *args, **kwargs)
            return _FakeUpload(payload.encode("utf-8"), file_id=file_id)
        return real_uploader(label, *args, **kwargs)

    monkeypatch.setattr(streamlit, "file_uploader", upload_always)
    monkeypatch.setattr(policies, "_shown_default_value_warning", False)
    fresh = AppTest.from_file(APP_PATH, default_timeout=60).run()
    assert not fresh.exception
    assert not fresh.error
    assert not [w for w in fresh.warning if "default value" in w.value]
    return fresh


def test_save_load_round_trip_keeps_settings(monkeypatch):
    """Discount rate, context, base year, zero-growth flag and name survive a reload."""
    saved = _capture_saves(monkeypatch)
    at = _app_with_sample()
    _number_input(at, "Discount Rate (%)").set_value(7.0).run()
    _number_input(at, "Discount Base Year").set_value(2025).run()
    [ctx] = [s for s in at.selectbox if s.label == "Context"]
    ctx.set_value("rural").run()
    [zg] = [c for c in at.checkbox if c.label == "Zero growth after last modelling year"]
    zg.check().run()
    [name] = [t for t in at.text_input if t.label == "Project Name"]
    name.set_value("Picton Bypass").run()
    assert not at.exception
    payload = saved[-1]

    fresh = _open_in_fresh_app(monkeypatch, payload, file_id="saved-settings-1")
    assert _number_input(fresh, "Discount Rate (%)").value == 7.0
    assert _number_input(fresh, "Discount Base Year").value == 2025
    assert [s for s in fresh.selectbox if s.label == "Context"][0].value == "rural"
    assert [c for c in fresh.checkbox
            if c.label == "Zero growth after last modelling year"][0].value is True
    assert [t for t in fresh.text_input if t.label == "Project Name"][0].value == "Picton Bypass"

    # The file stays in the uploader; a later edit must stick.
    _number_input(fresh, "Discount Rate (%)").set_value(4.0).run()
    assert not fresh.exception
    assert _number_input(fresh, "Discount Rate (%)").value == 4.0


def test_save_includes_edit_made_this_run(monkeypatch):
    """A cost edit is in the save file rendered on the same run, not one run later."""
    saved = _capture_saves(monkeypatch)
    at = _app_with_sample()
    _number_input(at, "Upfront carbon (tCO₂e)").set_value(12345.0).run()
    assert not at.exception
    assert json.loads(saved[-1])["cost_data"]["project_1"]["upfront_carbon_t"] == 12345.0


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
    assert list(frames[0].columns) == ["Option 1"]
    assert frames[0].loc[key, "Option 1"] == "395.0"
    assert frames[0].loc["P90 outturn capital (nominal $M)", "Option 1"] == "432.0"



def test_new_session_is_untitled_and_sample_sets_name():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not at.exception
    assert [t for t in at.text_input if t.label == "Project Name"][0].value == "Untitled project"
    at.checkbox(key="confirm_load_sample").check().run()
    [btn] = [b for b in at.button if b.label == "Load Sample Data"]
    btn.click().run()
    assert not at.exception
    assert [t for t in at.text_input if t.label == "Project Name"][0].value == "Sample Road Upgrade"


def test_parameter_override_changes_result_and_is_listed():
    at = _app_with_sample()
    central = _metric(at, "Benefit-Cost Ratio")
    at.session_state["param_vtts_urban_Car"] = 30.0
    at.run()
    assert not at.exception
    assert _metric(at, "Benefit-Cost Ratio") != central
    assert any("Changed from default" in c.value and "Car Urban: 19.76 → 30" in c.value
               for c in at.caption)


def test_save_keeps_parameter_values_not_widget_keys(monkeypatch):
    saved = _capture_saves(monkeypatch)
    at = _app_with_sample()
    at.session_state["param_vtts_urban_Car"] = 30.0
    at.session_state["param_vtts_urban_Car_num"] = 30.0  # left by older versions
    at.run()
    data = json.loads(saved[-1])
    assert data["param_vtts_urban_Car"] == 30.0
    assert "param_vtts_urban_Car_num" not in data


def test_benefit_assumptions_on_traffic_tab():
    at = _app_with_sample()
    [walk] = [w for w in at.number_input if w.label == "Additional walking (person-km/day)"]
    walk.set_value(500.0).run()
    assert not at.exception
    assert at.session_state["cost_data"]["project_1"]["walk_pkm_day"] == 500.0
