"""Figures for the README and the report. All figures are written as PNG."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .charging import STRATEGIES, STRATEGY_LABELS  # noqa: E402

# Colour roles (validated categorical palette, light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3de"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # blue, orange, aqua
STRATEGY_COLORS = dict(zip(STRATEGIES, SERIES))
MEASURED = "#8a8984"                                  # neutral for measured data

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.labelsize": 9.5,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.frameon": False,
    "legend.fontsize": 8.5,
    "lines.linewidth": 1.8,
    "font.family": "DejaVu Sans",
})


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _clock_ticks(ax, sc):
    ticks = np.arange(0, sc.time_h[-1] + 1e-9, 3)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{(sc.clock_h[0] + t) % 24:02.0f}:00" for t in ticks])
    ax.set_xlim(0, sc.time_h[-1])


# ---------------------------------------------------------------------------
# Battery model
# ---------------------------------------------------------------------------

def plot_ocv(soc_meas, v_meas, ocv_curve, true_ocv, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(100 * soc_meas, v_meas, color=MEASURED, lw=1.0, label="C/20 discharge (measured)")
    s = np.linspace(0, 1, 300)
    ax.plot(100 * s, ocv_curve(s), color=SERIES[0], lw=2, label="Identified OCV curve")
    ax.plot(100 * s, true_ocv(s), color=SERIES[1], lw=1.2, ls="--",
            label="Reference OCV (synthetic data only)")
    ax.set(xlabel="State of charge (%)", ylabel="Voltage (V)",
           title="Stage 1 · Open-circuit voltage vs state of charge")
    ax.legend(loc="lower right")
    _save(fig, path)


def plot_fit(m, ev, title: str, path: Path, zoom: tuple[float, float] | None = None) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(8, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [1.0, 2.2, 1.1]})
    t_min = m.time_s / 60.0
    if zoom is not None:
        mask = (t_min >= zoom[0]) & (t_min <= zoom[1])
    else:
        mask = np.ones_like(t_min, dtype=bool)

    axes[0].plot(t_min[mask], m.current_a[mask], color=INK_2, lw=1.0)
    axes[0].set(ylabel="Current (A)\n>0 discharge", title=title)

    axes[1].plot(t_min[mask], m.voltage_v[mask], color=MEASURED, lw=1.2, label="Measured")
    axes[1].plot(t_min[mask], ev["voltage_model"][mask], color=SERIES[0], lw=1.4,
                 label="1-RC model")
    axes[1].set(ylabel="Terminal voltage (V)")
    axes[1].legend(loc="lower left", ncols=2)

    axes[2].plot(t_min[mask], 1000 * ev["error_v"][mask], color=SERIES[1], lw=1.0)
    axes[2].axhline(0, color=INK_2, lw=0.8)
    axes[2].set(ylabel="Error (mV)", xlabel="Time (min)")
    axes[2].text(0.995, 1.02,
                 f"full test: RMSE {ev['rmse_mv']:.1f} mV · max {ev['max_abs_err_mv']:.1f} mV",
                 transform=axes[2].transAxes, ha="right", va="bottom", fontsize=8.5, color=INK,
                 bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5))
    fig.align_ylabels(axes)
    _save(fig, path)


# ---------------------------------------------------------------------------
# Energy system
# ---------------------------------------------------------------------------

def plot_scenario_inputs(sc, path: Path) -> None:
    """Small multiples, one quantity per panel (no dual axes)."""
    fig, axes = plt.subplots(3, 1, figsize=(8, 6), sharex=True)
    axes[0].fill_between(sc.time_h, sc.pv_kw, color=SERIES[2], alpha=0.25, lw=0)
    axes[0].plot(sc.time_h, sc.pv_kw, color=SERIES[2])
    axes[0].set(ylabel="kW", title="PV generation")
    axes[1].plot(sc.time_h, sc.load_kw, color=SERIES[0])
    axes[1].set(ylabel="kW", title="Household load (without EV)")
    axes[2].step(sc.time_h, 100 * sc.price_eur_kwh, where="post", color=SERIES[1])
    axes[2].axhline(100 * sc.feed_in_eur_kwh, color=INK_2, lw=1, ls="--")
    axes[2].text(sc.time_h[-1], 100 * sc.feed_in_eur_kwh + 1, "feed-in tariff",
                 ha="right", va="bottom", fontsize=8, color=INK_2)
    axes[2].set(ylabel="ct/kWh", title="Time-of-use electricity price")
    axes[2].set_ylim(0, 50)
    _clock_ticks(axes[2], sc)
    fig.align_ylabels(axes)
    fig.tight_layout()
    _save(fig, path)


def plot_strategies(sc, results: dict, title: str, path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1.2]})
    surplus = np.clip(sc.pv_kw - sc.load_kw, 0, None)
    axes[0].fill_between(sc.time_h, surplus, color=SERIES[2], alpha=0.15, lw=0,
                         label="PV surplus available")
    for name in STRATEGIES:
        r = results[name]
        axes[0].plot(sc.time_h, r["p_charger_kw"], color=STRATEGY_COLORS[name],
                     lw=1.6, label=STRATEGY_LABELS[name])
        axes[1].plot(sc.time_h, 100 * r["pack"]["soc"][1:], color=STRATEGY_COLORS[name],
                     lw=1.8, label=STRATEGY_LABELS[name])
    unplugged = ~sc.plugged
    for ax in axes:
        ax.fill_between(sc.time_h, 0, 1, where=unplugged, transform=ax.get_xaxis_transform(),
                        color=GRID, alpha=0.6, lw=0)
    axes[0].set(ylabel="Charger power (kW)", title=title)
    top = max(r["p_charger_kw"].max() for r in results.values())
    axes[0].set_ylim(0, top * 1.4)
    axes[0].legend(loc="upper center", ncols=2)
    axes[1].set(ylabel="Battery SOC (%)")
    axes[1].set_ylim(20, 90)
    axes[1].text(0.005, 0.06, "grey band = vehicle not plugged in",
                 transform=axes[1].transAxes, fontsize=8, color=INK_2)
    _clock_ticks(axes[1], sc)
    fig.align_ylabels(axes)
    _save(fig, path)


def plot_kpis(kpi_table, path: Path) -> None:
    """Three KPI panels side by side, each with its own scale."""
    metrics = [
        ("ev_charging_cost_eur", "EV charging cost (€)"),
        ("peak_grid_import_kw", "Peak grid import (kW)"),
        ("ev_pv_share_pct", "EV energy from own PV (%)"),
    ]
    scenarios = list(kpi_table["scenario"].unique())
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.8))
    width = 0.26
    x = np.arange(len(scenarios))
    for ax, (col, label) in zip(axes, metrics):
        for j, name in enumerate(STRATEGIES):
            vals = [kpi_table[(kpi_table.scenario == s) & (kpi_table.strategy == name)][col].iloc[0]
                    for s in scenarios]
            bars = ax.bar(x + (j - 1) * (width + 0.02), vals, width,
                          color=STRATEGY_COLORS[name], label=STRATEGY_LABELS[name])
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v:.1f}",
                        ha="center", va="bottom", fontsize=7.5, color=INK)
        ax.set_xticks(x)
        ax.set_xticklabels([s.replace("_", "-") for s in scenarios])
        ax.set_title(label, fontsize=10)
        ax.grid(axis="x", visible=False)
        ax.margins(y=0.15)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncols=3, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    _save(fig, path)


def plot_sweep(sweep_df, path: Path) -> None:
    scenarios = list(sweep_df["scenario"].unique())
    fig, axes = plt.subplots(1, len(scenarios), figsize=(10, 3.8), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, s in zip(axes, scenarios):
        d = sweep_df[sweep_df.scenario == s]
        for name in STRATEGIES:
            dd = d[d.strategy == name]
            ax.plot(dd.pv_peak_kwp, dd.ev_charging_cost_eur, color=STRATEGY_COLORS[name],
                    marker="o", ms=5, label=STRATEGY_LABELS[name])
        ax.set(title=s.replace("_", "-"), xlabel="PV system size (kWp)")
    axes[0].set_ylabel("EV charging cost (€ per charge)")
    axes[0].legend(loc="upper right")
    fig.suptitle("Sensitivity · charging cost vs PV size", x=0.01, ha="left",
                 fontsize=11, fontweight="bold", color=INK)
    fig.tight_layout()
    _save(fig, path)
