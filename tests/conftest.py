"""Shared fixture builders for the CBA test suite."""
import os
import sys

# Make the repository root importable (cba_engine.py, app.py live there).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cba_engine import VTYPES  # noqa: E402


def make_case_traffic(years, **by_vtype):
    """Return a traffic case dict for ``years`` with every vehicle type in VTYPES.

    All metrics are zero unless given. ``by_vtype`` maps a vehicle type name
    (e.g. ``Car``) to a dict of metric lists, e.g. ``Car={"vht": [1000, 750]}``.
    """
    n = len(years)
    case = {"years": list(years)}
    for vt in VTYPES:
        case[vt] = {
            "vht": [0.0] * n, "vkt": [0.0] * n,
            "stops": [0.0] * n, "demand": [0.0] * n,
        }
        for metric, values in by_vtype.get(vt, {}).items():
            case[vt][metric] = [float(v) for v in values]
    return case
