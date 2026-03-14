#!/usr/bin/env python3
"""
Focused exploration of design improvements.
Current baseline: Win=50, Lin=1.0, Wlatp=1, Llatp=0.5, Wlatn=1, Llatn=0.5,
                  Wtail=25, Ltail=0.15, Wrst=3
Results: offset=2.32mV@4.5σ, delay=8.97ns worst PVT, power=8.2μW

Exploration axes:
1. Tail current reduction (Wtail sweep)
2. Input pair area increase for better offset margin
3. Power/area optimization
"""

import os
import sys
import tempfile
import shutil
import numpy as np

from evaluate import (
    load_design, load_parameters, load_specs,
    run_simulation, run_offset_binary_search,
    run_pvt_sweep, run_monte_carlo,
    NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY,
    MC_SIGMA_TARGET
)

template = load_design()

# Baseline parameters
baseline = {
    'Win': 50.0, 'Lin': 1.0,
    'Wlatp': 1.0, 'Llatp': 0.5,
    'Wlatn': 1.0, 'Llatn': 0.5,
    'Wtail': 25.0, 'Ltail': 0.15,
    'Wrst': 3.0,
}

def quick_eval(params, label=""):
    """Quick evaluation at a few critical corners."""
    tmp = tempfile.mkdtemp(prefix="comp_explore_")
    corners = [
        ("tt", 24, 1.8),
        ("ss", -40, 1.2),  # worst delay
        ("fs", -40, 1.2),  # worst delay alt
        ("ff", 175, 1.8),  # fast corner
    ]

    worst_delay = 0
    worst_offset = 0
    power_nom = 0
    all_ok = True

    for corner, temp, supply in corners:
        sim = run_simulation(template, params, 0, tmp,
                            corner=corner, temperature=temp, supply_v=supply)
        if sim.get("error") or not sim.get("measurements"):
            all_ok = False
            continue

        meas = sim["measurements"]
        delay = meas.get("RESULT_RISE_TIME_DELAY_NS", 999)
        sens = meas.get("RESULT_SENSITIVITY_OK", 0)
        power = meas.get("RESULT_POWER_UW", 0)

        worst_delay = max(worst_delay, delay)
        if not sens:
            all_ok = False

        if corner == "tt":
            power_nom = power

    # Analytical MC offset estimate
    Win = params['Win']
    Lin = params['Lin']
    sigma_vth = 5.0 / np.sqrt(Win * Lin)  # mV
    mc_offset = sigma_vth * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"  {label:30s} | delay={worst_delay:6.2f}ns | mc_off={mc_offset:5.2f}mV | "
          f"power={power_nom:6.2f}μW | {'OK' if all_ok else 'FAIL'}")

    return worst_delay, mc_offset, power_nom, all_ok


print("=" * 90)
print("EXPERIMENT 1: Tail current sweep (Wtail)")
print("=" * 90)
for wtail in [5, 8, 10, 15, 20, 25, 30]:
    p = dict(baseline)
    p['Wtail'] = wtail
    quick_eval(p, f"Wtail={wtail}")

print()
print("=" * 90)
print("EXPERIMENT 2: Tail length sweep (Ltail) with Wtail=15")
print("=" * 90)
for ltail in [0.15, 0.20, 0.30, 0.50, 1.0]:
    p = dict(baseline)
    p['Wtail'] = 15
    p['Ltail'] = ltail
    quick_eval(p, f"Wtail=15, Ltail={ltail}")

print()
print("=" * 90)
print("EXPERIMENT 3: Input pair area (offset margin improvement)")
print("=" * 90)
for win, lin in [(50, 1.0), (60, 1.0), (70, 1.0), (50, 1.2), (50, 1.5), (40, 1.5)]:
    p = dict(baseline)
    p['Win'] = win
    p['Lin'] = lin
    wl = win * lin
    sigma = 5.0 / np.sqrt(wl)
    quick_eval(p, f"Win={win}, Lin={lin}, WL={wl}, σ={sigma:.3f}mV")

print()
print("=" * 90)
print("EXPERIMENT 4: Combined optimization candidates")
print("=" * 90)
# Try reducing tail while keeping good offset
candidates = [
    {'Win': 50, 'Lin': 1.0, 'Wtail': 15, 'Ltail': 0.15, 'Wrst': 2.0},
    {'Win': 50, 'Lin': 1.0, 'Wtail': 10, 'Ltail': 0.15, 'Wrst': 2.0},
    {'Win': 60, 'Lin': 1.0, 'Wtail': 15, 'Ltail': 0.15, 'Wrst': 2.0},
    {'Win': 50, 'Lin': 1.2, 'Wtail': 15, 'Ltail': 0.15, 'Wrst': 2.0},
    {'Win': 50, 'Lin': 1.0, 'Wtail': 10, 'Ltail': 0.20, 'Wrst': 2.0},
    {'Win': 60, 'Lin': 1.0, 'Wtail': 10, 'Ltail': 0.15, 'Wrst': 2.0},
]
for c in candidates:
    p = dict(baseline)
    p.update(c)
    label = f"Win={c['Win']},Lin={c['Lin']},Wt={c['Wtail']},Lt={c['Ltail']}"
    quick_eval(p, label)

print("\nDone.")
