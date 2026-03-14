#!/usr/bin/env python3
"""Validate Win=70 candidate with full PVT + MC."""

import tempfile
import shutil
import time
import numpy as np

from evaluate import (
    load_design, load_specs,
    run_simulation, run_pvt_sweep, run_monte_carlo,
    score_measurements, save_results, generate_plots,
    print_report,
    NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY,
    MC_SIGMA_TARGET
)

template = load_design()
specs = load_specs()

candidate = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 1.0, 'Llatp': 0.5,
    'Wlatn': 1.0, 'Llatn': 0.5,
    'Wtail': 5.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

print("Candidate: Win=70, Wtail=5, Wrst=2")
Win = candidate['Win']
Lin = candidate['Lin']
sigma_vth = 5.0 / np.sqrt(Win * Lin)
mc_est = sigma_vth * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))
print(f"  W×L = {Win*Lin:.0f} μm², σ_Vth = {sigma_vth:.3f} mV, MC offset est = {mc_est:.2f} mV")

tmp = tempfile.mkdtemp(prefix="comp_v2_")
t0 = time.time()

# Nominal
final = run_simulation(template, candidate, 0, tmp,
                      NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY)
measurements = final["measurements"] if not final.get("error") else {}
if measurements:
    print(f"  Nominal: delay={measurements.get('RESULT_RISE_TIME_DELAY_NS', 999):.2f}ns, "
          f"power={measurements.get('RESULT_POWER_UW', 0):.2f}μW")

# Full PVT
pvt_results = run_pvt_sweep(template, candidate, tmp, quick=False)

# Full MC
mc_results = run_monte_carlo(template, candidate, tmp, quick=False)

shutil.rmtree(tmp, ignore_errors=True)

if pvt_results and mc_results:
    measurements["RESULT_OFFSET_MV"] = max(
        pvt_results["worst_offset_mv"], mc_results["offset_worst_mv"])
    measurements["RESULT_RISE_TIME_DELAY_NS"] = max(
        pvt_results["worst_delay_ns"], mc_results["delay_worst_ns"])

elapsed = time.time() - t0
score, details = score_measurements(measurements, specs)

print_report(candidate, measurements, score, details, specs,
            pvt_results, mc_results, elapsed)

# Comparison
print("=" * 60)
print("COMPARISON TO CURRENT BEST (Win=60)")
print("=" * 60)
print(f"  {'Metric':<30} {'Current':>12} {'Candidate':>12}")
print(f"  {'-'*54}")
print(f"  {'MC Offset (4.5σ) mV':<30} {'2.113':>12} {mc_results['offset_worst_mv']:>12.3f}")
print(f"  {'PVT Worst Delay ns':<30} {'9.21':>12} {pvt_results['worst_delay_ns']:>12.2f}")
print(f"  {'Nominal Power μW':<30} {'9.25':>12} {measurements.get('RESULT_POWER_UW', 0):>12.2f}")

area = 2*Win*Lin + 5*0.15 + 2*1*0.5 + 2*1*0.5 + 4*2*0.15 + 4*1.5*0.15
print(f"  {'Total Gate Area μm²':<30} {'125.8':>12} {area:>12.1f}")

pvt_ok = pvt_results and pvt_results["all_pass"]
mc_ok = mc_results and mc_results["all_pass"]

if pvt_ok and mc_ok and score >= 1.0:
    print("\n  >>> CANDIDATE PASSES — evaluate if improvement is worth the tradeoff <<<")
    save_results(candidate, measurements, score, details, pvt_results, mc_results)
    generate_plots(pvt_results, mc_results, measurements)
else:
    print("\n  >>> CANDIDATE FAILS <<<")
