#!/usr/bin/env python3
"""Explore asymmetric latch: wider PMOS to help at fs corner."""

import tempfile, shutil, numpy as np
from evaluate import (load_design, run_simulation, NOMINAL_CORNER, NOMINAL_TEMP,
                      NOMINAL_SUPPLY, MC_SIGMA_TARGET)

template = load_design()
baseline = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

def eval_at_corners(params, label):
    tmp = tempfile.mkdtemp(prefix="comp_asym_")
    corners = [
        ("tt", 24, 1.8),
        ("fs", -40, 1.2),  # worst delay
        ("ss", -40, 1.2),  # second worst delay
        ("ff", 175, 1.8),
    ]
    results = {}
    for corner, temp, supply in corners:
        sim = run_simulation(template, params, 0, tmp,
                            corner=corner, temperature=temp, supply_v=supply)
        if sim.get("error") or not sim.get("measurements"):
            results[f"{corner}/{temp}/{supply}"] = {"delay": 999, "ok": False}
            continue
        meas = sim["measurements"]
        results[f"{corner}/{temp}/{supply}"] = {
            "delay": meas.get("RESULT_RISE_TIME_DELAY_NS", 999),
            "ok": meas.get("RESULT_SENSITIVITY_OK", 0) == 1,
            "power": meas.get("RESULT_POWER_UW", 0),
        }
    shutil.rmtree(tmp, ignore_errors=True)

    fs_delay = results.get("fs/-40/1.2", {}).get("delay", 999)
    ss_delay = results.get("ss/-40/1.2", {}).get("delay", 999)
    tt_delay = results.get("tt/24/1.8", {}).get("delay", 999)
    tt_power = results.get("tt/24/1.8", {}).get("power", 0)
    worst = max(fs_delay, ss_delay)
    all_ok = all(r.get("ok", False) for r in results.values())

    print(f"  {label:45s} | fs={fs_delay:6.2f}ns | ss={ss_delay:6.2f}ns | "
          f"worst={worst:6.2f}ns | tt={tt_delay:5.2f}ns | pwr={tt_power:6.2f}μW | {'OK' if all_ok else 'FAIL'}")
    return worst, all_ok

print("=" * 120)
print("ASYMMETRIC LATCH: Wider PMOS to help at fs corner (slow PMOS)")
print("=" * 120)
for wlatp in [0.5, 0.75, 1.0, 1.5, 2.0]:
    p = dict(baseline)
    p['Wlatp'] = wlatp
    eval_at_corners(p, f"Wlatp={wlatp}, Wlatn=0.5")

print()
print("=" * 120)
print("ASYMMETRIC LATCH: Wider NMOS latch")
print("=" * 120)
for wlatn in [0.5, 0.75, 1.0, 1.5, 2.0]:
    p = dict(baseline)
    p['Wlatn'] = wlatn
    eval_at_corners(p, f"Wlatp=0.5, Wlatn={wlatn}")

print()
print("=" * 120)
print("COMBINED: Best from above")
print("=" * 120)
combos = [
    {'Wlatp': 0.5, 'Wlatn': 0.5, 'Wtail': 8},  # baseline
    {'Wlatp': 0.75, 'Wlatn': 0.5, 'Wtail': 8},
    {'Wlatp': 0.75, 'Wlatn': 0.5, 'Wtail': 10},
    {'Wlatp': 0.5, 'Wlatn': 0.5, 'Wtail': 10},
    {'Wlatp': 0.5, 'Wlatn': 0.5, 'Wtail': 12},
]
for c in combos:
    p = dict(baseline)
    p.update(c)
    eval_at_corners(p, f"Wlatp={c['Wlatp']}, Wlatn={c['Wlatn']}, Wtail={c['Wtail']}")

print("\nDone.")
