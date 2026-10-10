"""Equivalent circuit battery models (Thevenin type).

Sign convention used throughout the project:
    current > 0  -> discharge
    current < 0  -> charge

Terminal voltage of an n-RC Thevenin model:
    v = OCV(soc) - R0 * i - sum(v_k)
    dv_k/dt = -v_k / (R_k C_k) + i / C_k
    dsoc/dt = -i / (3600 * Q)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Open-circuit voltage
# ---------------------------------------------------------------------------

@dataclass
class OCVCurve:
    """OCV(SOC) described by a lookup table with linear interpolation."""

    soc: np.ndarray
    voltage: np.ndarray

    def __post_init__(self) -> None:
        order = np.argsort(self.soc)
        self.soc = np.asarray(self.soc, dtype=float)[order]
        self.voltage = np.asarray(self.voltage, dtype=float)[order]

    def __call__(self, soc: np.ndarray | float) -> np.ndarray | float:
        return np.interp(np.clip(soc, 0.0, 1.0), self.soc, self.voltage)


def nmc_reference_ocv(soc: np.ndarray | float) -> np.ndarray | float:
    """Smooth NMC/graphite-like OCV shape used to generate the reference cell.

    The functional form (combined exponential/log terms) is a common empirical
    OCV description; the coefficients are chosen to give 3.0 V at 0 % SOC and
    about 4.18 V at 100 % SOC, typical for an 18650 NMC cell.
    """
    s = np.clip(soc, 0.0, 1.0)
    return (
        3.42
        + 0.68 * s
        - 0.38 * np.exp(-s / 0.045)
        + 0.06 * np.tanh((s - 0.55) / 0.12)
        + 0.03 * np.exp((s - 1.0) / 0.04)
    )


# ---------------------------------------------------------------------------
# Generic n-RC model
# ---------------------------------------------------------------------------

@dataclass
class TheveninModel:
    """n-RC equivalent circuit model of a single cell."""

    capacity_ah: float
    r0: float
    r_rc: tuple[float, ...]
    c_rc: tuple[float, ...]
    ocv: OCVCurve | callable
    name: str = "cell"
    _tau: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.r_rc) != len(self.c_rc):
            raise ValueError("r_rc and c_rc must have the same length")
        self._tau = np.asarray(self.r_rc) * np.asarray(self.c_rc)

    @property
    def n_rc(self) -> int:
        return len(self.r_rc)

    def simulate(
        self,
        time_s: np.ndarray,
        current_a: np.ndarray,
        soc0: float,
    ) -> dict[str, np.ndarray]:
        """Simulate the terminal voltage for a given current profile.

        The RC states are updated with the exact zero-order-hold solution, so
        the result does not depend on the step size as long as the current is
        constant within each step.
        """
        time_s = np.asarray(time_s, dtype=float)
        current_a = np.asarray(current_a, dtype=float)
        n = len(time_s)
        dt = np.diff(time_s, prepend=time_s[0])

        soc = np.empty(n)
        v_rc = np.zeros((n, self.n_rc))
        r_rc = np.asarray(self.r_rc)

        soc[0] = soc0
        for k in range(1, n):
            i_prev = current_a[k - 1]
            a = np.exp(-dt[k] / self._tau)
            v_rc[k] = a * v_rc[k - 1] + r_rc * (1.0 - a) * i_prev
            soc[k] = soc[k - 1] - i_prev * dt[k] / (3600.0 * self.capacity_ah)

        voltage = self.ocv(soc) - self.r0 * current_a - v_rc.sum(axis=1)
        return {"soc": soc, "voltage": voltage, "v_rc": v_rc}


# ---------------------------------------------------------------------------
# Battery pack built from identified cells
# ---------------------------------------------------------------------------

@dataclass
class BatteryPack:
    """Pack of identical cells in an n_series x n_parallel arrangement.

    Cell-to-cell variation and thermal effects are neglected (see README).
    """

    cell: TheveninModel
    n_series: int
    n_parallel: int

    @property
    def capacity_ah(self) -> float:
        return self.cell.capacity_ah * self.n_parallel

    def nominal_energy_kwh(self, soc_lo: float = 0.0, soc_hi: float = 1.0) -> float:
        socs = np.linspace(soc_lo, soc_hi, 200)
        v_mean = float(np.mean(self.cell.ocv(socs)))
        return v_mean * self.n_series * self.capacity_ah * (soc_hi - soc_lo) / 1000.0

    def charge_with_power(
        self,
        power_kw: np.ndarray,
        dt_s: float,
        soc0: float,
        soc_max: float = 1.0,
    ) -> dict[str, np.ndarray]:
        """Charge the pack with a DC power profile (power > 0 into the battery).

        For every step the cell current is solved from P = V(i) * i using the
        quadratic form of the Thevenin terminal equation. The step stops
        charging once soc_max is reached.
        Returns per-step SOC, pack voltage, current, delivered energy and losses.
        """
        cell = self.cell
        n = len(power_kw)
        r_rc = np.asarray(cell.r_rc)
        tau = np.asarray(cell.r_rc) * np.asarray(cell.c_rc)

        soc = np.empty(n + 1)
        soc[0] = soc0
        v_rc = np.zeros(cell.n_rc)

        pack_v = np.zeros(n)
        pack_i = np.zeros(n)
        p_stored = np.zeros(n)
        p_loss = np.zeros(n)
        p_used = np.zeros(n)

        for k in range(n):
            p_cell = power_kw[k] * 1000.0 / (self.n_series * self.n_parallel)
            if p_cell <= 0 or soc[k] >= soc_max:
                v_rc = v_rc * np.exp(-dt_s / tau)
                soc[k + 1] = soc[k]
                pack_v[k] = (cell.ocv(soc[k]) + v_rc.sum()) * self.n_series
                continue

            # Charging current i_c > 0 (model current = -i_c):
            #   V = OCV + R0*i_c + v_rc_mean(i_c),  P = V * i_c
            # Solved as a quadratic in i_c with a short fixed-point iteration
            # for the (step-averaged) RC overvoltage.
            a = np.exp(-dt_s / tau)
            i_max = (soc_max - soc[k]) * 3600.0 * cell.capacity_ah / dt_s
            v_rc_mean = v_rc
            for _ in range(6):
                e = cell.ocv(soc[k]) + v_rc_mean.sum()
                i_c = (-e + np.sqrt(e * e + 4.0 * cell.r0 * p_cell)) / (2.0 * cell.r0)
                i_c = min(i_c, i_max)            # do not overshoot soc_max
                v_rc_new = a * v_rc + r_rc * (1.0 - a) * i_c
                v_rc_mean = 0.5 * (v_rc + v_rc_new)

            v_cell = cell.ocv(soc[k]) + cell.r0 * i_c + v_rc_mean.sum()
            p_cell_used = v_cell * i_c
            p_cell_loss = cell.r0 * i_c**2 + np.sum(v_rc_mean**2 / r_rc)

            soc[k + 1] = soc[k] + i_c * dt_s / (3600.0 * cell.capacity_ah)
            v_rc = v_rc_new

            scale = self.n_series * self.n_parallel / 1000.0  # W -> kW for pack
            pack_v[k] = v_cell * self.n_series
            pack_i[k] = i_c * self.n_parallel
            p_used[k] = p_cell_used * scale
            p_loss[k] = p_cell_loss * scale
            p_stored[k] = p_used[k] - p_loss[k]

        return {
            "soc": soc,
            "pack_voltage": pack_v,
            "pack_current": pack_i,
            "power_used_kw": p_used,
            "power_loss_kw": p_loss,
            "power_stored_kw": p_stored,
        }
