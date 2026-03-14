#!/usr/bin/env python3
"""
Round 2 exploration: diminishing returns analysis and LVT exploration.
"""

import os
import sys
import tempfile
import shutil
import numpy as np

from evaluate import (
    load_design, load_parameters, load_specs,
    run_simulation, run_offset_binary_search,
    NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY,
    MC_SIGMA_TARGET
)

template = load_design()

baseline = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 1.0, 'Llatp': 0.5,
    'Wlatn': 1.0, 'Llatn': 0.5,
    'Wtail': 5.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

def quick_eval(params, label=""):
    """Quick evaluation at critical corners."""
    tmp = tempfile.mkdtemp(prefix="comp_r2_")
    corners = [
        ("tt", 24, 1.8),
        ("ss", -40, 1.2),
        ("fs", -40, 1.2),
        ("ff", 175, 1.8),
    ]

    worst_delay = 0
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

    Win = params['Win']
    Lin = params['Lin']
    sigma_vth = 5.0 / np.sqrt(Win * Lin)
    mc_offset = sigma_vth * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))
    margin = (1 - mc_offset / 5.0) * 100

    shutil.rmtree(tmp, ignore_errors=True)

    area = 2*Win*Lin + params['Wtail']*params['Ltail'] + 2*params['Wlatp']*params['Llatp'] + \
           2*params['Wlatn']*params['Llatn'] + 4*params['Wrst']*0.15 + 4*1.5*0.15

    print(f"  {label:35s} | delay={worst_delay:6.2f}ns | mc_off={mc_offset:5.2f}mV({margin:4.1f}%) | "
          f"power={power_nom:6.2f}μW | area={area:5.0f}μm² | {'OK' if all_ok else 'FAIL'}")

    return worst_delay, mc_offset, power_nom, all_ok


print("=" * 110)
print("DIMINISHING RETURNS: Input pair width sweep")
print("=" * 110)
for win in [50, 60, 70, 80, 90, 100]:
    p = dict(baseline)
    p['Win'] = win
    wl = win * 1.0
    sigma = 5.0 / np.sqrt(wl)
    quick_eval(p, f"Win={win} (WL={wl:.0f}, σ={sigma:.3f}mV)")

print()
print("=" * 110)
print("LATCH SIZING: Can we improve worst-corner delay?")
print("=" * 110)
# Try different latch configurations
configs = [
    {'Wlatp': 1.0, 'Llatp': 0.5, 'Wlatn': 1.0, 'Llatn': 0.5},  # baseline
    {'Wlatp': 0.5, 'Llatp': 0.5, 'Wlatn': 0.5, 'Llatn': 0.5},  # smaller latch
    {'Wlatp': 2.0, 'Llatp': 0.5, 'Wlatn': 2.0, 'Llatn': 0.5},  # larger latch
    {'Wlatp': 1.0, 'Llatp': 0.3, 'Wlatn': 1.0, 'Llatn': 0.3},  # shorter latch L
    {'Wlatp': 2.0, 'Llatp': 0.3, 'Wlatn': 2.0, 'Llatn': 0.3},  # wider+shorter
    {'Wlatp': 1.0, 'Llatp': 0.5, 'Wlatn': 2.0, 'Llatn': 0.5},  # asymmetric: larger N latch
]
for c in configs:
    p = dict(baseline)
    p.update(c)
    label = f"Wlatp={c['Wlatp']},Llatp={c['Llatp']},Wlatn={c['Wlatn']},Llatn={c['Llatn']}"
    quick_eval(p, label)

print()
print("=" * 110)
print("RESET SIZING: Impact on delay")
print("=" * 110)
for wrst in [1.0, 1.5, 2.0, 3.0, 5.0]:
    p = dict(baseline)
    p['Wrst'] = wrst
    quick_eval(p, f"Wrst={wrst}")

print()
print("=" * 110)
print("TAIL SIZING FINER SWEEP")
print("=" * 110)
for wtail in [2, 3, 5, 8, 10]:
    p = dict(baseline)
    p['Wtail'] = wtail
    quick_eval(p, f"Wtail={wtail}")

print("\nDone.")
