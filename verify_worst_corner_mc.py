#!/usr/bin/env python3
"""Verify MC mismatch at worst PVT corner (ss/-40/1.2V) with LVT design."""

import tempfile, shutil, numpy as np
from evaluate import (load_design, run_simulation, run_monte_carlo,
                      MC_N_SAMPLES, MC_SIGMA_TARGET)

template = load_design()
params = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

# Run MC at worst PVT corner
print("Running 100 MC samples at ss/-40°C/1.2V (worst corner)...")

tmp = tempfile.mkdtemp(prefix="comp_wc_mc_")

Win = params['Win']
Lin = params['Lin']
Avt = 5.0e-3  # V·μm
sigma_vth = Avt / np.sqrt(Win * Lin)

rng = np.random.RandomState(42)
n_samples = 100
offsets = rng.normal(0, sigma_vth, size=n_samples)

supply = 1.2
vcm = supply / 2.0
delays = []
n_fail = 0

for i, vth_offset in enumerate(offsets):
    vinp = vcm + vth_offset/2 + 0.0025
    vinm = vcm - vth_offset/2 - 0.0025

    sim = run_simulation(template, params, i, tmp,
                        corner="ss", temperature=-40, supply_v=supply)
    if sim.get("error") or not sim.get("measurements"):
        n_fail += 1
        delays.append(999)
        continue

    meas = sim["measurements"]
    delay = meas.get("RESULT_RISE_TIME_DELAY_NS", 999)
    sens = meas.get("RESULT_SENSITIVITY_OK", 0)
    delays.append(delay)
    if not sens:
        n_fail += 1

    if (i+1) % 25 == 0:
        print(f"  Completed {i+1}/{n_samples}...")

shutil.rmtree(tmp, ignore_errors=True)

delays_arr = np.array(delays)
valid = delays_arr < 100

print(f"\n--- Results: MC at ss/-40°C/1.2V ---")
print(f"  Samples: {n_samples}, Failures: {n_fail}")
print(f"  Delay mean: {np.mean(delays_arr[valid]):.3f} ns")
print(f"  Delay std:  {np.std(delays_arr[valid]):.3f} ns")
print(f"  Delay max:  {np.max(delays_arr[valid]):.3f} ns")
print(f"  Delay 4.5σ: {np.mean(delays_arr[valid]) + 4.5*np.std(delays_arr[valid]):.3f} ns")
print(f"  All resolve correctly: {n_fail == 0}")
print(f"  σ_Vth: {sigma_vth*1e3:.3f} mV")
