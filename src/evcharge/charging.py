"""Charging strategies and the home energy balance.

Power flow at every time step (AC side, kW):
    grid_import - grid_export = household_load + charger_power - pv

Three strategies decide the charger power while the vehicle is plugged in:
    uncontrolled  charge at maximum power from plug-in until the target SOC
    tariff        minimise the cost of the charging energy using only the
                  time-of-use price (no knowledge of PV)
    pv_tariff     minimise the total household electricity bill with PV,
                  load and price forecasts (linear program)

The schedules are planned on energy, then checked by simulating the battery
pack with the identified equivalent circuit model. If the simulated SOC falls
short of the target (because of battery losses), the energy requirement is
increased and the schedule is re-planned.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from .ecm import BatteryPack
from .profiles import Scenario

STRATEGIES = ("uncontrolled", "tariff", "pv_tariff")
STRATEGY_LABELS = {
    "uncontrolled": "Uncontrolled",
    "tariff": "Tariff-based",
    "pv_tariff": "PV + tariff optimised",
}


@dataclass
class ChargerSpec:
    max_power_kw: float
    efficiency: float          # AC -> DC
    grid_limit_kw: float       # house connection limit


# ---------------------------------------------------------------------------
# Energy requirement
# ---------------------------------------------------------------------------

def stored_energy_needed_kwh(pack: BatteryPack, soc0: float, soc_target: float) -> float:
    """Chemical energy needed to move the pack from soc0 to soc_target."""
    socs = np.linspace(soc0, soc_target, 400)
    v = np.asarray(pack.cell.ocv(socs)) * pack.n_series
    return float(np.trapezoid(v, socs) * pack.capacity_ah / 1000.0)


# ---------------------------------------------------------------------------
# Schedulers (return AC charger power in kW per step)
# ---------------------------------------------------------------------------

def schedule_uncontrolled(sc: Scenario, ch: ChargerSpec, e_ac_kwh: float) -> np.ndarray:
    p = np.zeros(len(sc.time_h))
    remaining = e_ac_kwh
    for k in np.flatnonzero(sc.plugged):
        if remaining <= 1e-9:
            break
        p[k] = min(ch.max_power_kw, remaining / sc.dt_h)
        remaining -= p[k] * sc.dt_h
    return p


def _solve_lp(c, a_eq, b_eq, bounds):
    res = linprog(c, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"charging LP infeasible: {res.message}")
    return res.x


def schedule_tariff(sc: Scenario, ch: ChargerSpec, e_ac_kwh: float) -> np.ndarray:
    """Cheapest-hours charging: min sum(price * P_ch * dt)."""
    n = len(sc.time_h)
    # A tiny time-dependent term breaks ties between equal prices by charging
    # as late as possible inside a cheap band (keeps the battery at low SOC
    # longer, which is gentler for ageing).
    c = sc.price_eur_kwh * sc.dt_h - 1e-7 * np.arange(n)
    a_eq = np.full((1, n), sc.dt_h)
    bounds = [(0.0, ch.max_power_kw if plugged else 0.0) for plugged in sc.plugged]
    return _solve_lp(c, a_eq, [e_ac_kwh], bounds)


def schedule_pv_tariff(sc: Scenario, ch: ChargerSpec, e_ac_kwh: float) -> np.ndarray:
    """Minimise the household bill with PV:  x = [P_ch, P_imp, P_exp]."""
    n = len(sc.time_h)
    dt = sc.dt_h
    c = np.concatenate([-1e-7 * np.arange(n), sc.price_eur_kwh * dt,
                        -sc.feed_in_eur_kwh * dt * np.ones(n)])
    eye = np.eye(n)
    a_balance = np.hstack([-eye, eye, -eye])          # P_imp - P_exp - P_ch = load - pv
    b_balance = sc.load_kw - sc.pv_kw
    a_energy = np.concatenate([np.full(n, dt), np.zeros(2 * n)])[None, :]
    a_eq = np.vstack([a_balance, a_energy])
    b_eq = np.concatenate([b_balance, [e_ac_kwh]])
    bounds = (
        [(0.0, ch.max_power_kw if p else 0.0) for p in sc.plugged]
        + [(0.0, ch.grid_limit_kw)] * n
        + [(0.0, float(pv)) for pv in sc.pv_kw]
    )
    return _solve_lp(c, a_eq, b_eq, bounds)[:n]


SCHEDULERS = {
    "uncontrolled": schedule_uncontrolled,
    "tariff": schedule_tariff,
    "pv_tariff": schedule_pv_tariff,
}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def grid_flows(sc: Scenario, p_charger: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    net = sc.load_kw + p_charger - sc.pv_kw
    return np.clip(net, 0, None), np.clip(-net, 0, None)


def kpis(sc: Scenario, p_charger: np.ndarray, pack_result: dict, ch: ChargerSpec,
         soc_target: float) -> dict[str, float]:
    dt = sc.dt_h
    imp, exp = grid_flows(sc, p_charger)
    imp0, exp0 = grid_flows(sc, np.zeros_like(p_charger))   # household without EV

    bill = float(np.sum(imp * sc.price_eur_kwh - exp * sc.feed_in_eur_kwh) * dt)
    bill0 = float(np.sum(imp0 * sc.price_eur_kwh - exp0 * sc.feed_in_eur_kwh) * dt)

    surplus = np.clip(sc.pv_kw - sc.load_kw, 0, None)
    pv_to_ev = np.minimum(p_charger, surplus)
    e_ev_ac = float(np.sum(p_charger) * dt)
    pv_total = float(np.sum(sc.pv_kw) * dt)

    return {
        "ev_energy_ac_kwh": e_ev_ac,
        "ev_charging_cost_eur": bill - bill0,
        "ev_cost_ct_per_kwh": 100 * (bill - bill0) / e_ev_ac if e_ev_ac > 0 else float("nan"),
        "household_bill_eur": bill,
        "grid_import_kwh": float(np.sum(imp) * dt),
        "grid_export_kwh": float(np.sum(exp) * dt),
        "peak_grid_import_kw": float(imp.max()),
        "pv_self_consumption_pct": 100 * (pv_total - float(np.sum(exp) * dt)) / pv_total
        if pv_total > 0 else float("nan"),
        "ev_pv_share_pct": 100 * float(np.sum(pv_to_ev) * dt) / e_ev_ac if e_ev_ac > 0 else 0.0,
        "charger_loss_kwh": e_ev_ac * (1 - ch.efficiency),
        "battery_loss_kwh": float(np.sum(pack_result["power_loss_kw"]) * dt),
        "final_soc_pct": 100 * float(pack_result["soc"][-1]),
        "target_reached": bool(pack_result["soc"][-1] >= soc_target - 1e-3),
    }


def run_strategy(name: str, sc: Scenario, pack: BatteryPack, ch: ChargerSpec,
                 soc0: float, soc_target: float, max_iter: int = 5) -> dict:
    """Plan a schedule, simulate the pack, and re-plan until the target is met."""
    e_stored = stored_energy_needed_kwh(pack, soc0, soc_target)
    e_ac = e_stored / (ch.efficiency * 0.98)   # first guess: 2 % battery losses
    scheduler = SCHEDULERS[name]

    for _ in range(max_iter):
        p_ac = scheduler(sc, ch, e_ac)
        res = pack.charge_with_power(p_ac * ch.efficiency, sc.dt_h * 3600.0, soc0,
                                     soc_max=soc_target)
        shortfall = soc_target - res["soc"][-1]
        if shortfall <= 1e-4:
            break
        e_ac += shortfall * pack.capacity_ah * pack.cell.ocv(soc_target) * pack.n_series \
            / 1000.0 / ch.efficiency * 1.05

    # Power actually drawn by the charger (the BMS stops at the target SOC)
    p_ac_actual = res["power_used_kw"] / ch.efficiency
    return {
        "name": name,
        "p_charger_kw": p_ac_actual,
        "pack": res,
        "kpi": kpis(sc, p_ac_actual, res, ch, soc_target),
    }
