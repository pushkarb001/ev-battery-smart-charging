from pathlib import Path

import numpy as np
import pytest
import yaml

from evcharge import charging, data, identification, profiles
from evcharge.ecm import BatteryPack

CFG = yaml.safe_load((Path(__file__).parents[1] / "config" / "default.yaml").read_text())


@pytest.fixture(scope="module")
def pack():
    ds = data.make_synthetic_dataset(seed=CFG["battery_identification"]["seed"])
    q = identification.estimate_capacity(ds["ocv"])
    ocv = identification.fit_ocv(ds["ocv"], q)
    cell = identification.fit_rc(ds["pulse"], q, ocv).model
    return BatteryPack(cell, CFG["pack"]["n_series"], CFG["pack"]["n_parallel"])


@pytest.fixture(scope="module")
def results(pack):
    sc = profiles.build_scenario(CFG, seed=CFG["simulation"]["seed"])
    ch = charging.ChargerSpec(**CFG["charger"])
    v = CFG["vehicle"]
    res = {s: charging.run_strategy(s, sc, pack, ch, v["soc_initial"], v["soc_target"])
           for s in charging.STRATEGIES}
    return sc, ch, res


def test_tariff_bands_cover_day():
    clock = np.arange(0, 24, 0.25)
    price = profiles.tou_tariff(clock, CFG["tariff"]["bands"])
    assert not np.isnan(price).any()


def test_household_load_energy():
    sc = profiles.build_scenario(CFG)
    assert np.sum(sc.load_kw) * sc.dt_h == pytest.approx(CFG["household"]["daily_kwh"], rel=1e-6)


def test_all_strategies_reach_target(results):
    _, _, res = results
    for r in res.values():
        assert r["kpi"]["target_reached"]


def test_charging_only_when_plugged(results):
    sc, ch, res = results
    for r in res.values():
        assert np.all(r["p_charger_kw"][~sc.plugged] == 0)
        assert r["p_charger_kw"].max() <= ch.max_power_kw + 1e-6


def test_optimised_strategy_is_cheapest(results):
    _, _, res = results
    cost = {k: r["kpi"]["ev_charging_cost_eur"] for k, r in res.items()}
    assert cost["pv_tariff"] <= cost["tariff"] + 1e-6
    assert cost["pv_tariff"] <= cost["uncontrolled"] + 1e-6


def test_energy_balance(results):
    sc, ch, res = results
    for r in res.values():
        imp, exp = charging.grid_flows(sc, r["p_charger_kw"])
        lhs = imp - exp
        rhs = sc.load_kw + r["p_charger_kw"] - sc.pv_kw
        assert np.allclose(lhs, rhs)
