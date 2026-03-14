#!/usr/bin/env python3
"""Validate a specific candidate design with full PVT + MC."""

import tempfile
import shutil
import time
import numpy as np

from evaluate import (
    load_design, load_specs,
    run_simulation, run_pvt_sweep, run_monte_carlo,
    score_measurements, save_results, generate_plots,
    generate_progress_plot, print_report,
    NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY,
    RESULTS_FILE, PLOTS_DIR, MC_SIGMA_TARGET
)

template = load_design()
specs = load_specs()

# Candidate: Win=60 for better offset, Wtail=5 for area savings
candidate = {
    'Win': 60.0, 'Lin': 1.0,
    'Wlatp': 1.0, 'Llatp': 0.5,
    'Wlatn': 1.0, 'Llatn': 0.5,
    'Wtail': 5.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

print("Candidate parameters:")
for k, v in sorted(candidate.items()):
    print(f"  {k}: {v}")

Win = candidate['Win']
Lin = candidate['Lin']
sigma_vth = 5.0 / np.sqrt(Win * Lin)
mc_est = sigma_vth * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))
print(f"\n  Input pair W×L = {Win*Lin:.0f} μm²")
print(f"  σ_Vth = {sigma_vth:.3f} mV")
print(f"  MC offset estimate (4.5σ) = {mc_est:.2f} mV")

tmp = tempfile.mkdtemp(prefix="comp_validate_")
t0 = time.time()

# Nominal simulation
print("\n--- Nominal Simulation ---")
final = run_simulation(template, candidate, 0, tmp,
                      NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY)
measurements = final["measurements"] if not final.get("error") else {}
if measurements:
    print(f"  Delay: {measurements.get('RESULT_RISE_TIME_DELAY_NS', 999):.2f} ns")
    print(f"  Power: {measurements.get('RESULT_POWER_UW', 0):.2f} μW")
    print(f"  Sensitivity: {'OK' if measurements.get('RESULT_SENSITIVITY_OK') else 'FAIL'}")

# Full PVT sweep
pvt_results = run_pvt_sweep(template, candidate, tmp, quick=False)

# Full Monte Carlo
mc_results = run_monte_carlo(template, candidate, tmp, quick=False)

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

print_report(candidate, measurements, score, details, specs,
            pvt_results, mc_results, elapsed)

# Compare to baseline
print("\n" + "=" * 60)
print("COMPARISON TO BASELINE")
print("=" * 60)
print(f"  {'Metric':<30} {'Baseline':>12} {'Candidate':>12} {'Change':>12}")
print(f"  {'-'*66}")
print(f"  {'MC Offset (4.5σ) mV':<30} {'2.315':>12} {mc_results['offset_worst_mv']:>12.3f} "
      f"{'BETTER' if mc_results['offset_worst_mv'] < 2.315 else 'WORSE':>12}")
print(f"  {'PVT Worst Delay ns':<30} {'8.97':>12} {pvt_results['worst_delay_ns']:>12.2f} "
      f"{'BETTER' if pvt_results['worst_delay_ns'] < 8.97 else 'WORSE':>12}")
print(f"  {'Nominal Power μW':<30} {'8.16':>12} {measurements.get('RESULT_POWER_UW', 0):>12.2f}")
print(f"  {'Total Gate Area μm²':<30} {'118':>12} ", end="")

# Calculate area
area = (2 * Win * Lin +  # input pair
        candidate['Wtail'] * candidate['Ltail'] +  # tail
        2 * candidate['Wlatp'] * candidate['Llatp'] +  # PMOS latch
        2 * candidate['Wlatn'] * candidate['Llatn'] +  # NMOS latch
        4 * candidate['Wrst'] * 0.15 +  # reset
        4 * 1.5 * 0.15)  # buffers
print(f"{area:>12.1f}")
print(f"  {'Score':<30} {'1.00':>12} {score:>12.4f}")

pvt_ok = pvt_results and pvt_results["all_pass"]
mc_ok = mc_results and mc_results["all_pass"]
print(f"\n  PVT: {'PASS' if pvt_ok else 'FAIL'}")
print(f"  MC:  {'PASS' if mc_ok else 'FAIL'}")

if pvt_ok and mc_ok and score >= 1.0:
    print("\n  >>> CANDIDATE IS BETTER — should commit <<<")
    # Save results
    save_results(candidate, measurements, score, details, pvt_results, mc_results)
    generate_plots(pvt_results, mc_results, measurements)
else:
    print("\n  >>> CANDIDATE DOES NOT IMPROVE — discard <<<")
