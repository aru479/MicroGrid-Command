import pandas as pd

from backend.controller import MAIN_GRID, RENEWABLE, Battery, dispatch, grid_mode, is_overload


def test_mode_rules_boundaries():
    assert grid_mode(160.0, 12) == MAIN_GRID          # 160 is NOT > 160
    assert grid_mode(160.01, 12) == RENEWABLE
    assert grid_mode(100, 17) == MAIN_GRID
    assert grid_mode(100, 18) == RENEWABLE            # window start inclusive
    assert grid_mode(100, 22) == RENEWABLE            # window end inclusive
    assert grid_mode(100, 23) == MAIN_GRID
    assert grid_mode(100, 0) == MAIN_GRID


def test_overload_threshold():
    assert not is_overload(199.99) and is_overload(200.0) and is_overload(250)


def test_overload_independent_of_mode():
    ts = [pd.Timestamp("2026-01-01 03:00"), pd.Timestamp("2026-01-01 20:00")]
    rows = dispatch(ts, [210, 210])
    assert all(r["overload_alert"] for r in rows)
    assert [r["grid_mode"] for r in rows] == [RENEWABLE, RENEWABLE]
    rows = dispatch([pd.Timestamp("2026-01-01 03:00")], [100])
    assert rows[0]["grid_mode"] == MAIN_GRID and not rows[0]["overload_alert"]


def test_battery_discharges_in_storage_mode_and_charges_otherwise():
    ts = [pd.Timestamp("2026-01-01 10:00"), pd.Timestamp("2026-01-01 11:00")]
    rows = dispatch(ts, [100, 100], Battery(soc_pct=50))
    assert rows[0]["soc_pct"] > 50 and rows[0]["battery_kw"] < 0
    rows = dispatch([pd.Timestamp("2026-01-01 19:00")], [200], Battery(soc_pct=50))
    assert rows[0]["soc_pct"] < 50 and rows[0]["battery_kw"] > 0


def test_battery_respects_reserve_floor():
    ts = [pd.Timestamp("2026-01-01 18:00") + pd.Timedelta(hours=i) for i in range(5)]
    rows = dispatch(ts, [250] * 5, Battery(soc_pct=15))
    assert min(r["soc_pct"] for r in rows) >= 10.0
    assert any(r["battery_depleted"] for r in rows)
def test_grid_covers_demand_when_battery_hits_reserve():
    ts = [
        pd.Timestamp("2026-01-01 18:00") + pd.Timedelta(hours=i)
        for i in range(8)
    ]
    rows = dispatch(ts, [250] * 8, Battery(soc_pct=15))

    assert min(r["soc_pct"] for r in rows) >= 10.0
    assert rows[-1]["grid_kw"] >= 0
    assert rows[-1]["battery_kw"] <= 0
    assert abs(rows[-1]["grid_kw"] + max(0, -rows[-1]["battery_kw"]) - rows[-1]["predicted_demand_kw"]) < 0.1



def test_grid_import_includes_battery_charging():
    ts = [pd.Timestamp("2026-01-01 23:00")]
    rows = dispatch(ts, [150.0], Battery(soc_pct=10.0))
    row = rows[0]

    assert row["battery_kw"] == -100.0
    assert row["grid_kw"] == 250.0
    assert row["soc_pct"] == 22.5


def test_grid_import_accounts_for_battery_discharge():
    ts = [pd.Timestamp("2026-01-01 19:00")]
    rows = dispatch(ts, [250.0], Battery(soc_pct=90.0))
    row = rows[0]

    assert row["battery_kw"] == 150.0
    assert row["grid_kw"] == 100.0


def test_battery_soc_stays_within_limits():
    ts = [
        pd.Timestamp("2026-01-01 18:00") + pd.Timedelta(hours=i)
        for i in range(24)
    ]
    rows = dispatch(ts, [250.0] * 24, Battery(soc_pct=90.0))

    assert min(row["soc_pct"] for row in rows) >= 10.0
    assert max(row["soc_pct"] for row in rows) <= 100.0
    assert max(row["battery_kw"] for row in rows) <= 150.0
    assert max(-row["battery_kw"] for row in rows) <= 100.0
