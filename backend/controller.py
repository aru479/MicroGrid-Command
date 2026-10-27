"""Transition controller: rules from the problem statement (section 6) + a simple battery model.

Mode rule      demand > 160 kW  OR  hour in 18..22 (inclusive)  -> Renewable Storage Mode, else Main Grid Mode
Overload rule  demand >= 200 kW -> Critical Overload Alert (independent of the mode)

The battery numbers are ASSUMPTIONS for the dashboard simulation (the problem statement gives none).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

RENEWABLE_THRESHOLD_KW = 160.0
OVERLOAD_THRESHOLD_KW = 200.0
EVENING_START, EVENING_END = 18, 22
RENEWABLE, MAIN_GRID = "Renewable Storage Mode", "Main Grid Mode"


@dataclass
class Battery:
    capacity_kwh: float = 800.0
    soc_pct: float = 90.0
    min_soc_pct: float = 10.0
    max_discharge_kw: float = 150.0
    max_charge_kw: float = 100.0


def grid_mode(demand_kw: float, hour: int) -> str:
    if demand_kw > RENEWABLE_THRESHOLD_KW or EVENING_START <= hour <= EVENING_END:
        return RENEWABLE
    return MAIN_GRID


def is_overload(demand_kw: float) -> bool:
    return demand_kw >= OVERLOAD_THRESHOLD_KW


def dispatch(timestamps, demands, battery: Optional[Battery] = None) -> list:
    """One dict per forecast hour. Steps are 1 hour, so kW == kWh. battery_kw: +discharge / -charge."""
    b = battery or Battery()
    soc = b.soc_pct
    rows = []
    for ts, d in zip(timestamps, demands):
        d = float(d)
        mode = grid_mode(d, ts.hour)
        depleted = False
        if mode == RENEWABLE:
            available = max(0.0, (soc - b.min_soc_pct) / 100 * b.capacity_kwh)
            wanted = min(d, b.max_discharge_kw)
            battery_kw = min(wanted, available)
            depleted = battery_kw < wanted - 1e-9
            soc -= battery_kw / b.capacity_kwh * 100
        else:
            charge = min(b.max_charge_kw, (100 - soc) / 100 * b.capacity_kwh)
            soc += charge / b.capacity_kwh * 100
            battery_kw = -charge
        rows.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "hour": int(ts.hour),
            "predicted_demand_kw": round(d, 2),
            "grid_mode": mode,
            "overload_alert": is_overload(d),
            "battery_kw": round(battery_kw, 1),
            "grid_kw": round(max(0.0, d - max(battery_kw, 0.0)), 1),
            "soc_pct": round(soc, 1),
            "battery_depleted": bool(depleted),
        })
    return rows


def summarize(rows: list) -> dict:
    if not rows:
        return {}
    peak = max(rows, key=lambda r: r["predicted_demand_kw"])
    n = len(rows)
    return {
        "hours": n,
        "peak_kw": peak["predicted_demand_kw"],
        "peak_time": peak["timestamp"],
        "avg_kw": round(sum(r["predicted_demand_kw"] for r in rows) / n, 1),
        "renewable_hours": sum(r["grid_mode"] == RENEWABLE for r in rows),
        "main_grid_hours": sum(r["grid_mode"] == MAIN_GRID for r in rows),
        "overload_hours": sum(r["overload_alert"] for r in rows),
        "min_soc_pct": min(r["soc_pct"] for r in rows),
        "end_soc_pct": rows[-1]["soc_pct"],
        "depleted_hours": sum(r["battery_depleted"] for r in rows),
    }
