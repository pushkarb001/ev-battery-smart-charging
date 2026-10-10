"""Two-stage parameter identification of a 1-RC equivalent circuit model.

Stage 1  OCV-SOC curve from a low-rate (C/20) discharge. At C/20 the
         polarisation is small, so the terminal voltage is close to OCV after
         correcting for the ohmic drop R0 * I.
Stage 2  R0, R1 and C1 by nonlinear least squares on a pulse test, with the
         OCV curve from stage 1 fixed.
Validation on a separate dynamic profile that was not used for fitting.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from .data import Measurement
from .ecm import OCVCurve, TheveninModel


@dataclass
class FitResult:
    model: TheveninModel
    rmse_mv: float
    max_abs_err_mv: float
    cost: float


def coulomb_soc(m: Measurement, capacity_ah: float) -> np.ndarray:
    dt = np.diff(m.time_s, prepend=m.time_s[0])
    return m.soc0 - np.cumsum(m.current_a * dt) / (3600.0 * capacity_ah)


def estimate_capacity(m: Measurement) -> float:
    """Capacity from the charge removed during a full low-rate discharge."""
    dt = np.diff(m.time_s, prepend=m.time_s[0])
    return float(np.sum(m.current_a * dt) / 3600.0)


def fit_ocv(m: Measurement, capacity_ah: float, r0_guess: float = 0.03,
            n_points: int = 41) -> OCVCurve:
    """Stage 1: OCV-SOC lookup table from a C/20 discharge."""
    soc = coulomb_soc(m, capacity_ah)
    v_ocv = m.voltage_v + r0_guess * m.current_a  # undo ohmic drop
    grid = np.linspace(0.0, 1.0, n_points)
    # Smooth the noisy data in SOC bins, then interpolate on the grid
    bins = np.linspace(soc.min(), soc.max(), 120)
    idx = np.digitize(soc, bins)
    s_mean = np.array([soc[idx == b].mean() for b in np.unique(idx)])
    v_mean = np.array([v_ocv[idx == b].mean() for b in np.unique(idx)])
    order = np.argsort(s_mean)
    v_grid = np.interp(grid, s_mean[order], v_mean[order])
    return OCVCurve(grid, v_grid)


def _model_from_params(p, capacity_ah, ocv) -> TheveninModel:
    r0, r1, tau1 = p
    return TheveninModel(capacity_ah, r0, (r1,), (tau1 / r1,), ocv, name="identified 1-RC")


def fit_rc(m: Measurement, capacity_ah: float, ocv: OCVCurve,
           x0=(0.02, 0.02, 30.0)) -> FitResult:
    """Stage 2: R0, R1, tau1 by least squares on the pulse test."""

    def residuals(p):
        model = _model_from_params(p, capacity_ah, ocv)
        v = model.simulate(m.time_s, m.current_a, m.soc0)["voltage"]
        return v - m.voltage_v

    sol = least_squares(
        residuals,
        x0=np.asarray(x0),
        bounds=([1e-4, 1e-4, 1.0], [0.2, 0.2, 2000.0]),
        x_scale=[0.01, 0.01, 10.0],
    )
    model = _model_from_params(sol.x, capacity_ah, ocv)
    err = sol.fun
    return FitResult(model, 1000 * np.sqrt(np.mean(err**2)), 1000 * np.max(np.abs(err)), sol.cost)


def evaluate(model: TheveninModel, m: Measurement) -> dict[str, np.ndarray | float]:
    """Simulate a measurement with the model and compute error metrics."""
    sim = model.simulate(m.time_s, m.current_a, m.soc0)
    err = sim["voltage"] - m.voltage_v
    return {
        "voltage_model": sim["voltage"],
        "error_v": err,
        "soc": sim["soc"],
        "rmse_mv": float(1000 * np.sqrt(np.mean(err**2))),
        "max_abs_err_mv": float(1000 * np.max(np.abs(err))),
    }
