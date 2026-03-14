#!/usr/bin/env python3
"""Fine tail sweep to find the sweet spot."""

import tempfile, shutil
from evaluate import load_design, run_simulation

template = load_design()
baseline = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

print(f"{'Wtail':>6} | {'fs/-40/1.2':>10} | {'ss/-40/1.2':>10} | {'worst':>10} | {'tt/24/1.8':>10} | {'power':>8}")
print("-" * 70)

for wtail in [5, 8, 10, 12, 15, 20, 25, 30]:
    p = dict(baseline)
    p['Wtail'] = wtail
    tmp = tempfile.mkdtemp(prefix="comp_tf_")

    delays = {}
    power = 0
    for corner, temp, supply in [("fs", -40, 1.2), ("ss", -40, 1.2), ("tt", 24, 1.8)]:
        sim = run_simulation(template, p, 0, tmp, corner=corner, temperature=temp, supply_v=supply)
        if sim.get("measurements"):
            d = sim["measurements"].get("RESULT_RISE_TIME_DELAY_NS", 999)
            delays[f"{corner}/{temp}/{supply}"] = d
            if corner == "tt":
                power = sim["measurements"].get("RESULT_POWER_UW", 0)

    shutil.rmtree(tmp, ignore_errors=True)

    fs = delays.get("fs/-40/1.2", 999)
    ss = delays.get("ss/-40/1.2", 999)
    tt = delays.get("tt/24/1.8", 999)
    worst = max(fs, ss)
    print(f"{wtail:>6} | {fs:>10.2f} | {ss:>10.2f} | {worst:>10.2f} | {tt:>10.2f} | {power:>8.2f}")
