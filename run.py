"""Run the full study: battery identification -> charging simulation -> report.

Usage
    python run.py                         # default configuration
    python run.py --config config/x.yaml  # custom case
    python run.py --skip-sweep            # faster, no sensitivity study
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent / "src"))

from evcharge import charging, data, identification, plotting, profiles  # noqa: E402
from evcharge.ecm import BatteryPack, nmc_reference_ocv  # noqa: E402


def identify_battery(cfg: dict, out: Path):
    bcfg = cfg["battery_identification"]
    if bcfg["data_source"] == "synthetic":
        ds = data.make_synthetic_dataset(seed=bcfg["seed"])
        data.save_dataset(ds, out / "data")
    else:
        c = bcfg["csv"]
        ds = {
            "ocv": data.load_measurement_csv(c["ocv_test"], c["soc0_ocv"], "OCV test"),
            "pulse": data.load_measurement_csv(c["pulse_test"], c["soc0_pulse"], "pulse test"),
            "dynamic": data.load_measurement_csv(c["validation_test"], c["soc0_validation"],
                                                 "validation"),
        }

    capacity = identification.estimate_capacity(ds["ocv"])
    ocv = identification.fit_ocv(ds["ocv"], capacity)
    fit = identification.fit_rc(ds["pulse"], capacity, ocv)
    ev_fit = identification.evaluate(fit.model, ds["pulse"])
    ev_val = identification.evaluate(fit.model, ds["dynamic"])

    fig = out / "figures"
    soc_ocv = identification.coulomb_soc(ds["ocv"], capacity)
    true_ocv = nmc_reference_ocv if bcfg["data_source"] == "synthetic" else ocv
    plotting.plot_ocv(soc_ocv, ds["ocv"].voltage_v, ocv, true_ocv, fig / "01_ocv_curve.png")
    plotting.plot_fit(ds["pulse"], ev_fit,
                      "Stage 2 · Parameter fit on the pulse test (first two pulse blocks)",
                      fig / "02_parameter_fit.png", zoom=(0, 45))
    plotting.plot_fit(ds["dynamic"], ev_val,
                      "Validation · driving-like profile not used for fitting (first 30 min)",
                      fig / "03_validation.png", zoom=(0, 30))

    m = fit.model
    params = {
        "capacity_ah": round(capacity, 4),
        "r0_mohm": round(1000 * m.r0, 3),
        "r1_mohm": round(1000 * m.r_rc[0], 3),
        "c1_f": round(m.c_rc[0], 1),
        "tau1_s": round(m.r_rc[0] * m.c_rc[0], 2),
        "fit_rmse_mv": round(ev_fit["rmse_mv"], 2),
        "validation_rmse_mv": round(ev_val["rmse_mv"], 2),
        "validation_max_err_mv": round(ev_val["max_abs_err_mv"], 2),
        "data_source": bcfg["data_source"],
    }
    pd.Series(ocv.voltage, index=ocv.soc, name="ocv_v").rename_axis("soc").to_csv(
        out / "ocv_table.csv")
    (out / "battery_parameters.json").write_text(json.dumps(params, indent=2))
    return m, params


def simulate_case(cfg: dict, pack: BatteryPack) -> tuple[profiles.Scenario, dict]:
    sc = profiles.build_scenario(cfg, seed=cfg["simulation"]["seed"])
    ch = charging.ChargerSpec(**cfg["charger"])
    v = cfg["vehicle"]
    results = {s: charging.run_strategy(s, sc, pack, ch, v["soc_initial"], v["soc_target"])
               for s in charging.STRATEGIES}
    return sc, results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--config", default="config/default.yaml")
    ap.add_argument("--skip-sweep", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    cfg = yaml.safe_load(Path(args.config).read_text())
    out = Path(cfg["output_dir"])
    fig = out / "figures"
    out.mkdir(parents=True, exist_ok=True)

    print("[1/4] Identifying battery model ...")
    cell, params = identify_battery(cfg, out)
    for k, v in params.items():
        print(f"      {k:24s} {v}")

    pack = BatteryPack(cell, cfg["pack"]["n_series"], cfg["pack"]["n_parallel"])
    print(f"      pack {pack.n_series}s{pack.n_parallel}p, "
          f"{pack.nominal_energy_kwh():.1f} kWh usable (0-100 % SOC)")

    print("[2/4] Simulating charging strategies ...")
    rows = []
    for i, (key, scn) in enumerate(cfg["scenarios"].items()):
        c = copy.deepcopy(cfg)
        c["vehicle"]["plug_in_h"] = scn["plug_in_h"]
        sc, results = simulate_case(c, pack)
        if i == 0:
            plotting.plot_scenario_inputs(sc, fig / "04_scenario_inputs.png")
        plotting.plot_strategies(sc, results, scn["label"], fig / f"05_strategies_{key}.png")
        ts = sc.to_frame()
        for name, r in results.items():
            rows.append({"scenario": key, "strategy": name, **r["kpi"]})
            ts[f"p_charger_{name}_kw"] = r["p_charger_kw"]
            ts[f"soc_{name}"] = r["pack"]["soc"][1:]
        ts.to_csv(out / f"timeseries_{key}.csv", index=False, float_format="%.4f")

    kpi = pd.DataFrame(rows)
    kpi.to_csv(out / "kpi_summary.csv", index=False, float_format="%.3f")
    plotting.plot_kpis(kpi, fig / "06_kpi_comparison.png")

    if not args.skip_sweep:
        print("[3/4] Running PV-size sensitivity sweep ...")
        sweep_rows = []
        for key, scn in cfg["scenarios"].items():
            for kwp in cfg["sweep"]["pv_peak_kwp"]:
                c = copy.deepcopy(cfg)
                c["vehicle"]["plug_in_h"] = scn["plug_in_h"]
                c["pv"]["peak_kwp"] = kwp
                _, results = simulate_case(c, pack)
                for name, r in results.items():
                    sweep_rows.append({"scenario": key, "pv_peak_kwp": kwp, "strategy": name,
                                       **r["kpi"]})
        sweep = pd.DataFrame(sweep_rows)
        sweep.to_csv(out / "sweep_pv_size.csv", index=False, float_format="%.3f")
        plotting.plot_sweep(sweep, fig / "07_sweep_pv_size.png")
    else:
        print("[3/4] Sweep skipped")

    print("[4/4] Summary")
    cols = ["scenario", "strategy", "ev_charging_cost_eur", "ev_cost_ct_per_kwh",
            "peak_grid_import_kw", "ev_pv_share_pct", "pv_self_consumption_pct",
            "battery_loss_kwh", "final_soc_pct"]
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(kpi[cols].round(2).to_string(index=False))
    print(f"\nDone in {time.time() - t0:.1f} s. Results in '{out}/'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
