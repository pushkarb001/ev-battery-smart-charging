import numpy as np
import pytest

from evcharge import data, identification
from evcharge.ecm import BatteryPack, OCVCurve, TheveninModel


def flat_cell(r0=0.03, r1=0.01, c1=2000.0):
    ocv = OCVCurve(np.array([0.0, 1.0]), np.array([3.6, 3.6]))
    return TheveninModel(3.0, r0, (r1,), (c1,), ocv)


def test_open_circuit_voltage_at_rest():
    cell = flat_cell()
    t = np.arange(0, 100.0)
    sim = cell.simulate(t, np.zeros_like(t), soc0=0.5)
    assert np.allclose(sim["voltage"], 3.6)
    assert np.allclose(sim["soc"], 0.5)


def test_rc_reaches_steady_state():
    cell = flat_cell()
    t = np.arange(0, 2000.0)
    i = np.full_like(t, 3.0)
    v = cell.simulate(t, i, soc0=0.9)["voltage"]
    # after >> tau (20 s) the drop is (R0 + R1) * I on a flat OCV
    assert v[-1] == pytest.approx(3.6 - (0.03 + 0.01) * 3.0, abs=1e-6)


def test_coulomb_counting():
    cell = flat_cell()
    t = np.arange(0, 3601.0)
    sim = cell.simulate(t, np.full_like(t, 1.5), soc0=1.0)   # 0.5C for 1 h
    assert sim["soc"][-1] == pytest.approx(0.5, abs=1e-3)


def test_identification_recovers_reference_cell():
    ds = data.make_synthetic_dataset(seed=3)
    q = identification.estimate_capacity(ds["ocv"])
    ocv = identification.fit_ocv(ds["ocv"], q)
    fit = identification.fit_rc(ds["pulse"], q, ocv)
    ref = data.reference_cell()
    assert q == pytest.approx(ref.capacity_ah, rel=0.02)
    # 1-RC fitted to a 2-RC cell: R0 close, total resistance close
    assert fit.model.r0 == pytest.approx(ref.r0, rel=0.25)
    assert fit.model.r0 + fit.model.r_rc[0] == pytest.approx(ref.r0 + sum(ref.r_rc), rel=0.25)
    val = identification.evaluate(fit.model, ds["dynamic"])
    assert val["rmse_mv"] < 20.0


def test_pack_charging_energy_balance():
    cell = flat_cell()
    pack = BatteryPack(cell, n_series=96, n_parallel=50)
    p = np.full(60, 10.0)                       # 10 kW for 60 min
    res = pack.charge_with_power(p, 60.0, soc0=0.2, soc_max=0.9)
    assert np.allclose(res["power_used_kw"], 10.0, rtol=1e-6)
    stored = res["power_stored_kw"].sum() / 60.0
    loss = res["power_loss_kw"].sum() / 60.0
    assert stored + loss == pytest.approx(10.0, rel=1e-6)
    assert 0 < loss < 0.05 * 10.0
