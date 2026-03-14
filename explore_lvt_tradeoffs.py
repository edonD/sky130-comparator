#!/usr/bin/env python3
"""With LVT input pair, explore area reduction opportunities."""

import tempfile, shutil, numpy as np
from evaluate import load_design, run_simulation, MC_SIGMA_TARGET

template = load_design()

def quick_eval(params, label=""):
    tmp = tempfile.mkdtemp(prefix="comp_lvt_exp_")
    corners = [("tt", 24, 1.8), ("ss", -40, 1.2), ("fs", -40, 1.2), ("ff", 175, 1.8)]

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
        worst_delay = max(worst_delay, delay)
        if not meas.get("RESULT_SENSITIVITY_OK", 0):
            all_ok = False
        if corner == "tt":
            power_nom = meas.get("RESULT_POWER_UW", 0)

    shutil.rmtree(tmp, ignore_errors=True)

    Win = params['Win']
    Lin = params['Lin']
    sigma = 5.0 / np.sqrt(Win * Lin)
    mc_off = sigma * (np.sqrt(2/np.pi) + MC_SIGMA_TARGET * np.sqrt(1 - 2/np.pi))
    margin = (1 - mc_off/5) * 100
    area = 2*Win*Lin + params['Wtail']*params['Ltail'] + 2*0.5*0.5*2 + 4*params['Wrst']*0.15 + 4*1.5*0.15

    print(f"  {label:40s} | delay={worst_delay:5.2f}ns | mc_off={mc_off:5.2f}mV({margin:4.1f}%) | "
          f"pwr={power_nom:6.2f}μW | area={area:5.0f}μm² | {'OK' if all_ok else 'FAIL'}")
    return worst_delay, mc_off, all_ok

base = {
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

print("=" * 115)
print("LVT INPUT PAIR: Area-delay-offset tradeoff exploration")
print("=" * 115)
for win, lin in [(70, 1.0), (60, 1.0), (50, 1.0), (50, 1.2), (40, 1.2), (40, 1.5), (35, 1.5), (30, 2.0)]:
    p = dict(base)
    p['Win'] = win
    p['Lin'] = lin
    wl = win * lin
    quick_eval(p, f"Win={win:>3}, Lin={lin:>4.1f} (WL={wl:>5.0f})")

print()
print("=" * 115)
print("OPTIMAL: Same offset as Win=70 but different geometry")
print("=" * 115)
# Win=70, Lin=1.0 gives WL=70. What if we use Win=50, Lin=1.4 (WL=70)?
# Same offset but potentially less area-efficient in layout
for win, lin in [(70, 1.0), (60, 1.17), (50, 1.4), (45, 1.55)]:
    p = dict(base)
    p['Win'] = win
    p['Lin'] = lin
    wl = win * lin
    quick_eval(p, f"Win={win:>3}, Lin={lin:>4.2f} (WL={wl:>5.1f})")

print("\nDone.")
