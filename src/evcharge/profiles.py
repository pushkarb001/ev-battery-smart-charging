"""Input profiles for the home energy scenario: PV, household load, tariff.

All profiles are synthetic but shaped after typical German residential data:
a south-facing rooftop PV system on a clear-to-partly-cloudy day, a household
with morning and evening load peaks, and a three-level time-of-use tariff.
Replace them with measured CSV profiles via `load_profile_csv` if available.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Scenario:
    time_h: np.ndarray        # hours since simulation start
    clock_h: np.ndarray       # wall-clock hour of day (0-24)
    pv_kw: np.ndarray
    load_kw: np.ndarray
    price_eur_kwh: np.ndarray
    feed_in_eur_kwh: float
    plugged: np.ndarray       # bool, vehicle connected to charger
    dt_h: float

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({
            "time_h": self.time_h, "clock_h": self.clock_h, "pv_kw": self.pv_kw,
            "load_kw": self.load_kw, "price_eur_kwh": self.price_eur_kwh,
            "plugged": self.plugged.astype(int),
        })


def pv_profile(clock_h: np.ndarray, peak_kwp: float, sunrise: float, sunset: float,
               cloudiness: float, rng: np.random.Generator) -> np.ndarray:
    """Bell-shaped clear-sky PV output with random cloud dips."""
    x = (clock_h - sunrise) / (sunset - sunrise)
    clear = np.where((x > 0) & (x < 1), np.sin(np.pi * np.clip(x, 0, 1)) ** 1.5, 0.0)
    # Clouds: smoothed random attenuation (0 = clear, 1 = overcast)
    noise = rng.normal(0.0, 1.0, len(clock_h))
    kernel = np.ones(45) / 45
    smooth = np.convolve(noise, kernel, mode="same")
    attenuation = np.clip(1.0 - cloudiness * (0.5 + 2.5 * smooth), 0.25, 1.0)
    # 0.82 = typical inverter + temperature + soiling derating
    return peak_kwp * 0.82 * clear * attenuation


def household_load(clock_h: np.ndarray, dt_h: float, daily_kwh: float,
                   rng: np.random.Generator) -> np.ndarray:
    """Base load plus morning, noon and evening peaks, scaled to daily energy."""
    shape = (
        0.25
        + 0.6 * np.exp(-((clock_h - 7.5) ** 2) / (2 * 0.8**2))
        + 0.35 * np.exp(-((clock_h - 12.5) ** 2) / (2 * 1.0**2))
        + 1.0 * np.exp(-((clock_h - 19.0) ** 2) / (2 * 1.5**2))
    )
    shape = shape * (1 + 0.15 * rng.normal(0, 1, len(clock_h)))
    shape = np.clip(shape, 0.1, None)
    days = len(clock_h) * dt_h / 24.0
    return shape * daily_kwh * days / (shape.sum() * dt_h)


def tou_tariff(clock_h: np.ndarray, bands: list[dict]) -> np.ndarray:
    """Time-of-use price from a list of {start, end, price} bands (hours)."""
    price = np.full(len(clock_h), np.nan)
    for b in bands:
        start, end = b["start"], b["end"]
        if start <= end:
            mask = (clock_h >= start) & (clock_h < end)
        else:  # band crosses midnight
            mask = (clock_h >= start) | (clock_h < end)
        price[mask] = b["price"]
    if np.isnan(price).any():
        raise ValueError("tariff bands do not cover the full day")
    return price


def build_scenario(cfg: dict, seed: int = 11) -> Scenario:
    rng = np.random.default_rng(seed)
    sim = cfg["simulation"]
    dt_h = sim["time_step_min"] / 60.0
    time_h = np.arange(0.0, sim["duration_h"], dt_h)
    clock_h = (sim["start_hour"] + time_h) % 24.0

    pv = pv_profile(clock_h, cfg["pv"]["peak_kwp"], cfg["pv"]["sunrise_h"],
                    cfg["pv"]["sunset_h"], cfg["pv"]["cloudiness"], rng)
    load = household_load(clock_h, dt_h, cfg["household"]["daily_kwh"], rng)
    price = tou_tariff(clock_h, cfg["tariff"]["bands"])

    plug_in = cfg["vehicle"]["plug_in_h"]           # hours after start
    departure = cfg["vehicle"]["departure_h"]
    plugged = (time_h >= plug_in) & (time_h < departure)

    return Scenario(time_h, clock_h, pv, load, price,
                    cfg["tariff"]["feed_in_eur_kwh"], plugged, dt_h)


def load_profile_csv(path: str, column: str) -> np.ndarray:
    return pd.read_csv(path)[column].to_numpy(float)
