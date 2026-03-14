#!/usr/bin/env python3
"""
Comparator optimizer — focused on offset reduction across PVT corners.

Key insights:
- Delay is trivially met (<15ns vs 100ns spec) — not the bottleneck
- MC offset ~ 3.5 * Avt / sqrt(Win*Lin) — analytically driven by input pair area
- PVT offset at fs/ff corners is the real challenge
- Strategy: two-phase optimization
  Phase 1: Quick DE on key corners (tt, ss/175/1.2, fs/24/1.8, ff/-40/1.8)
  Phase 2: Full PVT + MC validation
"""

import os
import sys
import csv
import json
import time
import shutil
import tempfile
import numpy as np
from scipy.optimize import differential_evolution

from evaluate import (
    load_design, load_parameters, load_specs, validate_design,
    run_simulation, run_offset_binary_search, compute_cost,
    evaluate_params, run_pvt_sweep, run_monte_carlo,
    score_measurements, save_results, generate_plots,
    generate_progress_plot, print_report,
    NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY,
    PROCESS_CORNERS, TEMPERATURES, SUPPLY_VOLTAGES,
    RESULTS_FILE, PLOTS_DIR, PROJECT_DIR,
    MC_SIGMA_TARGET
)


def fast_cost(param_values, template):
    """Fast cost function evaluating only the critical corners.

    Key corners for offset:
    - fs/24/1.8: typically worst offset (fast N, slow P)
    - ff/-40/1.8: second worst offset corner
    - sf/24/1.8: opposite skew
    - ss/175/1.2: worst for delay (but delay is easy)
    """
    corners = [
        ("tt", 24, 1.8),
        ("fs", 24, 1.8),
        ("ff", -40, 1.8),
        ("sf", 24, 1.8),
        ("ss", 175, 1.2),
        ("fs", -40, 1.2),   # fs at low voltage too
        ("ff", 175, 1.2),   # ff at worst delay corner
    ]

    tmp = tempfile.mkdtemp(prefix="comp_opt_")
    worst_offset = 0.0
    worst_delay = 0.0
    n_fail = 0

    for corner, temp, supply in corners:
        # Quick sensitivity check first (no binary search)
        sim = run_simulation(template, param_values, 0, tmp,
                            corner=corner, temperature=temp, supply_v=supply)
        if sim.get("error") or not sim.get("measurements"):
            n_fail += 1
            continue

        meas = sim["measurements"]
        delay = meas.get("RESULT_RISE_TIME_DELAY_NS", 999.0)
        sens_ok = meas.get("RESULT_SENSITIVITY_OK", 0)
        worst_delay = max(worst_delay, delay)

        if not sens_ok:
            # If it fails 5mV sensitivity, do binary search to measure actual offset
            offset = run_offset_binary_search(template, param_values, tmp,
                                               corner=corner, temperature=temp,
                                               supply_v=supply, n_steps=10)
            worst_offset = max(worst_offset, offset)
            n_fail += 1
        else:
            # Passed 5mV test — do finer binary search only at critical corners
            if corner in ("fs", "ff"):
                offset = run_offset_binary_search(template, param_values, tmp,
                                                   corner=corner, temperature=temp,
                                                   supply_v=supply, n_steps=10)
                worst_offset = max(worst_offset, offset)

    shutil.rmtree(tmp, ignore_errors=True)

    # MC offset estimate (analytical)
    Win = param_values.get("Win", 10)
    Lin = param_values.get("Lin", 0.5)
    Avt = 5.0  # mV·μm
    sigma_vth = Avt / np.sqrt(Win * Lin)  # mV
    # For half-normal: mean + 4.5σ ≈ 3.51 * sigma_vth (see derivation)
    # Actually: mean(|X|) = σ*sqrt(2/π), std(|X|) = σ*sqrt(1-2/π)
    # worst = mean + 4.5*std = σ*(sqrt(2/π) + 4.5*sqrt(1-2/π))
    mc_offset = sigma_vth * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))

    # Cost function — minimize worst-case offset
    cost = 0.0

    # PVT offset penalty (heavy weight)
    if worst_offset < 5.0:
        cost -= (5.0 - worst_offset) / 5.0 * 40  # reward margin
    else:
        cost += (worst_offset - 5.0) ** 2 * 300  # heavy penalty

    # MC offset penalty
    if mc_offset < 5.0:
        cost -= (5.0 - mc_offset) / 5.0 * 40
    else:
        cost += (mc_offset - 5.0) ** 2 * 300

    # Delay penalty (light — it's easy to meet)
    if worst_delay >= 100.0:
        cost += (worst_delay - 100.0) ** 2 * 50
    else:
        cost -= (100.0 - worst_delay) / 100.0 * 10

    # Failure penalty
    cost += n_fail * 200

    # Mild area penalty to avoid enormous transistors
    area = Win * Lin
    if area > 200:
        cost += (area - 200) * 0.05

    return cost


def optimize():
    template = load_design()
    params = load_parameters()
    specs = load_specs()

    errors = validate_design(template, params)
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return None

    # Build bounds for DE (log-space for log-scaled params)
    bounds = []
    param_names = []
    for p in params:
        param_names.append(p["name"])
        if p["scale"] == "log":
            bounds.append((np.log10(p["min"]), np.log10(p["max"])))
        else:
            bounds.append((p["min"], p["max"]))

    print(f"Parameters ({len(params)}):")
    for p in params:
        print(f"  {p['name']}: [{p['min']}, {p['max']}] ({p['scale']})")

    eval_count = [0]
    best_cost = [1e9]
    best_pv = [None]

    def objective(x):
        eval_count[0] += 1
        pv = {}
        for i, p in enumerate(params):
            if p["scale"] == "log":
                pv[p["name"]] = 10 ** x[i]
            else:
                pv[p["name"]] = x[i]

        cost = fast_cost(pv, template)

        if cost < best_cost[0]:
            best_cost[0] = cost
            best_pv[0] = dict(pv)
            Win = pv.get("Win", 0)
            Lin = pv.get("Lin", 0)
            Avt = 5.0
            sigma_vth = Avt / np.sqrt(Win * Lin)
            mc_est = sigma_vth * (np.sqrt(2/np.pi) + 4.5 * np.sqrt(1 - 2/np.pi))
            print(f"  [{eval_count[0]:4d}] cost={cost:>8.2f}  "
                  f"Win={Win:.1f} Lin={Lin:.2f} WL={Win*Lin:.1f}  "
                  f"mc_offset_est={mc_est:.2f}mV")

        return cost

    # Good starting point based on analog design intuition:
    # - Large input pair for low offset: Win=40, Lin=1.0 → WL=40, σ_Vth=0.79mV
    # - Moderate latch for fast regeneration
    # - Strong tail for current
    # - Adequate reset devices
    x0_values = {
        'Win': 40.0, 'Lin': 1.0,
        'Wlatp': 4.0, 'Llatp': 0.20,
        'Wlatn': 4.0, 'Llatn': 0.20,
        'Wtail': 25.0, 'Ltail': 0.5,
        'Wrst': 3.0,
    }

    x0 = []
    for p in params:
        val = x0_values.get(p["name"], (p["min"] + p["max"]) / 2)
        if p["scale"] == "log":
            x0.append(np.log10(val))
        else:
            x0.append(val)

    print(f"\nStarting Differential Evolution (Phase 1: key corners)...")
    t0 = time.time()

    result = differential_evolution(
        objective,
        bounds=bounds,
        x0=x0,
        maxiter=40,
        popsize=12,
        tol=0.005,
        seed=42,
        mutation=(0.5, 1.5),
        recombination=0.85,
        polish=False,
        disp=True,
        workers=1,
    )

    elapsed = time.time() - t0
    print(f"\nDE Phase 1 done in {elapsed:.0f}s, {eval_count[0]} evaluations")
    print(f"Best cost: {result.fun:.4f}")

    # Extract best parameters
    best_params = {}
    for i, p in enumerate(params):
        if p["scale"] == "log":
            best_params[p["name"]] = 10 ** result.x[i]
        else:
            best_params[p["name"]] = result.x[i]

    print("\nBest parameters:")
    for name, val in sorted(best_params.items()):
        print(f"  {name}: {val:.4f}")

    # Compute metrics
    Win = best_params["Win"]
    Lin = best_params["Lin"]
    sigma_vth = 5.0 / np.sqrt(Win * Lin)
    mc_est = sigma_vth * (np.sqrt(2/np.pi) + 4.5 * np.sqrt(1 - 2/np.pi))
    print(f"\n  Input pair W*L = {Win*Lin:.1f} μm²")
    print(f"  σ_Vth = {sigma_vth:.3f} mV")
    print(f"  MC offset estimate (4.5σ) = {mc_est:.2f} mV")

    return best_params


def validate_and_save(best_params):
    """Full validation: PVT + MC, then save."""
    template = load_design()
    specs = load_specs()

    tmp = tempfile.mkdtemp(prefix="comp_validate_")
    t0 = time.time()

    # Nominal simulation
    final = run_simulation(template, best_params, 0, tmp,
                          NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY)
    measurements = final["measurements"] if not final.get("error") else {}

    # Full PVT sweep (all 30 corners)
    print("=" * 60)
    print("FULL PVT SWEEP (30 corners)")
    print("=" * 60)
    pvt_results = run_pvt_sweep(template, best_params, tmp, quick=False)

    # Full Monte Carlo (200 samples)
    print("=" * 60)
    print("FULL MONTE CARLO (200 samples)")
    print("=" * 60)
    mc_results = run_monte_carlo(template, best_params, tmp, quick=False)

    shutil.rmtree(tmp, ignore_errors=True)

    # Combine worst-case
    if pvt_results and mc_results:
        measurements["RESULT_OFFSET_MV"] = max(
            pvt_results["worst_offset_mv"],
            mc_results["offset_worst_mv"]
        )
        measurements["RESULT_RISE_TIME_DELAY_NS"] = max(
            pvt_results["worst_delay_ns"],
            mc_results["delay_worst_ns"]
        )

    elapsed = time.time() - t0
    score, details = score_measurements(measurements, specs)

    print_report(best_params, measurements, score, details, specs,
                pvt_results, mc_results, elapsed)

    generate_plots(pvt_results, mc_results, measurements)
    generate_progress_plot(RESULTS_FILE, PLOTS_DIR)
    save_results(best_params, measurements, score, details, pvt_results, mc_results)

    # Log to results.tsv
    step = 1
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            step = sum(1 for line in f)  # header + existing rows

    with open(RESULTS_FILE, "a") as f:
        pvt_ok = pvt_results and pvt_results["all_pass"]
        mc_ok = mc_results and mc_results["all_pass"]
        specs_met = sum(1 for d in details.values() if d.get("met"))
        wo = pvt_results["worst_offset_mv"] if pvt_results else 999
        wd = pvt_results["worst_delay_ns"] if pvt_results else 999
        mco = mc_results["offset_worst_mv"] if mc_results else 999
        notes = (f"pvt={'PASS' if pvt_ok else 'FAIL'} mc={'PASS' if mc_ok else 'FAIL'} "
                f"wo={wo:.2f}mV wd={wd:.2f}ns mc_o={mco:.2f}mV")
        f.write(f"{step}\t\t{score:.4f}\tStrongARM\t{specs_met}/2\t{notes}\n")

    return score, pvt_results, mc_results, details


if __name__ == "__main__":
    best_params = optimize()
    if best_params:
        score, pvt, mc, details = validate_and_save(best_params)
        print(f"\nFinal score: {score:.4f}")
        pvt_ok = pvt and pvt["all_pass"]
        mc_ok = mc and mc["all_pass"]
        print(f"PVT: {'PASS' if pvt_ok else 'FAIL'}")
        print(f"MC: {'PASS' if mc_ok else 'FAIL'}")

        if pvt_ok and mc_ok:
            print("\n*** ALL SPECS MET — DESIGN VALIDATED ***")
        else:
            print("\n*** SOME SPECS FAILED — needs more optimization ***")
