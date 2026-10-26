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


def fixture_costs():
    """Return ``(cost, base_costs)`` for C=2 construction years, E=3 appraisal years."""
    cost = {
        "capex_base": {
            "planning": [1.0, 0.0],
            "land": [2.0, 0.0],
            "construction": [4.0, 4.0],
        },
        "contingency_p50": [1.0, 1.0],
        "contingency_p90": [2.0, 2.0],
        "recurrent": [0.5, 0.5, 1.0, 1.0, 1.0],
        "upfront_carbon_t": 1000.0,
    }
    base_costs = {"recurrent": [0.5, 0.5, 0.8, 0.8, 0.8]}
    return cost, base_costs
