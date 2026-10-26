"""Headless smoke test of the Streamlit app."""
import os

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _metric(at, label):
    matches = [m for m in at.metric if m.label == label]
    assert matches, f"metric {label!r} not found; have {[m.label for m in at.metric]}"
    return matches[0].value


def test_sample_data_runs():
    at = AppTest.from_file(APP_PATH, default_timeout=300).run()
    assert not at.exception
    at.checkbox(key="confirm_load_sample").check().run()
    [btn] = [b for b in at.button if b.label == "Load Sample Data"]
    btn.click().run()
    assert not at.exception
    assert _metric(at, "Benefit-Cost Ratio") == "1.68"
    assert _metric(at, "PV Benefits") == "$614.6M"
    assert _metric(at, "PV Costs") == "$365.0M"
