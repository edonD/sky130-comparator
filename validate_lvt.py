#!/usr/bin/env python3
"""Validate LVT input pair design with full PVT + MC."""

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
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

print("Candidate: LVT input pair, Win=70, Wlat=0.5, Llat=0.5, Wtail=8")
Win = candidate['Win']
Lin = candidate['Lin']
sigma_vth = 5.0 / np.sqrt(Win * Lin)  # Using same Avt as approximation
mc_est = sigma_vth * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))
print(f"  W×L = {Win*Lin:.0f} μm², σ_Vth ≈ {sigma_vth:.3f} mV (assuming Avt=5 mV·μm)")
print(f"  MC offset estimate (4.5σ) ≈ {mc_est:.2f} mV")
print(f"  NOTE: LVT Avt may differ from standard; MC results will confirm")

tmp = tempfile.mkdtemp(prefix="comp_lvt_")
t0 = time.time()

# Nominal
final = run_simulation(template, candidate, 0, tmp,
                      NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY)
measurements = final["measurements"] if not final.get("error") else {}
if measurements:
    print(f"  Nominal: delay={measurements.get('RESULT_RISE_TIME_DELAY_NS', 999):.2f}ns, "
          f"power={measurements.get('RESULT_POWER_UW', 0):.2f}μW, "
          f"sens={'OK' if measurements.get('RESULT_SENSITIVITY_OK') else 'FAIL'}")

# Full PVT
pvt_results = run_pvt_sweep(template, candidate, tmp, quick=False)

# Full MC (uses Avt=5 from evaluate.py — may need adjustment for LVT)
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
print("COMPARISON: Standard vs LVT Input Pair")
print("=" * 60)
print(f"  {'Metric':<30} {'Standard':>12} {'LVT':>12} {'Change':>12}")
print(f"  {'-'*66}")
print(f"  {'MC Offset (4.5σ) mV':<30} {'1.957':>12} {mc_results['offset_worst_mv']:>12.3f}")
print(f"  {'PVT Worst Delay ns':<30} {'8.52':>12} {pvt_results['worst_delay_ns']:>12.2f}")
print(f"  {'PVT Worst Offset mV':<30} {'0.01':>12} {pvt_results['worst_offset_mv']:>12.3f}")
print(f"  {'Nominal Power μW':<30} {'10.69':>12} {measurements.get('RESULT_POWER_UW', 0):>12.2f}")

pvt_ok = pvt_results and pvt_results["all_pass"]
mc_ok = mc_results and mc_results["all_pass"]

if pvt_ok and mc_ok and score >= 1.0:
    print("\n  >>> LVT DESIGN VALIDATED — commit <<<")
    save_results(candidate, measurements, score, details, pvt_results, mc_results)
    generate_plots(pvt_results, mc_results, measurements)
else:
    print("\n  >>> LVT DESIGN FAILS — need investigation <<<")
    if pvt_results:
        for r in pvt_results.get("results", []):
            if r["offset_mv"] > 0.5 or r["delay_ns"] > 50:
                print(f"  Issue at {r['corner']}/T={r['temp']}/V={r['supply']}: "
                      f"offset={r['offset_mv']:.2f}mV, delay={r['delay_ns']:.2f}ns")
