#!/usr/bin/env python3
"""With massive delay margin from LVT, explore power reduction."""

import tempfile, shutil, numpy as np
from evaluate import load_design, run_simulation, MC_SIGMA_TARGET

template = load_design()
base = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

def quick_eval(params, label=""):
    tmp = tempfile.mkdtemp(prefix="comp_pwr_")
    corners = [("tt", 24, 1.8), ("ss", -40, 1.2), ("fs", -40, 1.2)]
    worst_delay = 0
    power_nom = 0
    all_ok = True

    for corner, temp, supply in corners:
        sim = run_simulation(template, params, 0, tmp,
                            corner=corner, temperature=temp, supply_v=supply)
        if sim.get("error") or not sim.get("measurements"):
            all_ok = False; continue
        meas = sim["measurements"]
        delay = meas.get("RESULT_RISE_TIME_DELAY_NS", 999)
        worst_delay = max(worst_delay, delay)
        if not meas.get("RESULT_SENSITIVITY_OK", 0): all_ok = False
        if corner == "tt": power_nom = meas.get("RESULT_POWER_UW", 0)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  {label:40s} | delay={worst_delay:5.2f}ns | pwr={power_nom:6.2f}μW | {'OK' if all_ok else 'FAIL'}")
    return worst_delay, power_nom, all_ok

print("=" * 80)
print("POWER REDUCTION: Tail and reset sweep with LVT")
print("=" * 80)
for wtail in [2, 3, 4, 5, 8, 10]:
    p = dict(base); p['Wtail'] = wtail
    quick_eval(p, f"Wtail={wtail}")

print()
for wrst in [0.5, 1.0, 1.5, 2.0, 3.0]:
    p = dict(base); p['Wrst'] = wrst
    quick_eval(p, f"Wrst={wrst}")

print()
print("=" * 80)
print("COMBINED: Lower power candidates")
print("=" * 80)
combos = [
    {"Wtail": 8, "Wrst": 2.0},   # baseline
    {"Wtail": 5, "Wrst": 1.5},
    {"Wtail": 4, "Wrst": 1.0},
    {"Wtail": 3, "Wrst": 1.0},
    {"Wtail": 3, "Wrst": 0.5},
]
for c in combos:
    p = dict(base); p.update(c)
    quick_eval(p, f"Wtail={c['Wtail']}, Wrst={c['Wrst']}")

print("\nDone.")
