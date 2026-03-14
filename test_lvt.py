#!/usr/bin/env python3
"""Test LVT input pair transistors for better low-voltage performance."""

import os, re, tempfile, subprocess, shutil
import numpy as np
from evaluate import PROJECT_DIR, NGSPICE, MC_SIGMA_TARGET

best_params = {
    'Win': 70.0, 'Lin': 1.0,
    'Wlatp': 0.5, 'Llatp': 0.5,
    'Wlatn': 0.5, 'Llatn': 0.5,
    'Wtail': 8.0, 'Ltail': 0.15,
    'Wrst': 2.0,
}

def make_netlist(params, corner, temp, supply, vdiff=0.005, use_lvt_input=False):
    vcm = supply / 2.0
    vinp = vcm + vdiff/2
    vinm = vcm - vdiff/2

    input_device = "sky130_fd_pr__nfet_01v8_lvt" if use_lvt_input else "sky130_fd_pr__nfet_01v8"

    return f"""* SKY130 StrongARM — LVT test
.lib "sky130_models/sky130.lib.spice" {corner}

Vdd vdd 0 DC {supply}
Vss vss 0 DC 0
Vclk clk 0 PULSE(0 {supply} 0 0.1n 0.1n 50n 100n)
Vinp inp 0 DC {vinp}
Vinm inm 0 DC {vinm}

XMtail ntail clk vss vss sky130_fd_pr__nfet_01v8 W={params['Wtail']}u L={params['Ltail']}u nf=1

* Input pair — {'LVT' if use_lvt_input else 'standard'}
XM1 d1 inp ntail vss {input_device} W={params['Win']}u L={params['Lin']}u nf=1
XM2 d2 inm ntail vss {input_device} W={params['Win']}u L={params['Lin']}u nf=1

XMr1 d1 clk vdd vdd sky130_fd_pr__pfet_01v8 W={params['Wrst']}u L=0.15u nf=1
XMr2 d2 clk vdd vdd sky130_fd_pr__pfet_01v8 W={params['Wrst']}u L=0.15u nf=1
XMr3 outn clk vdd vdd sky130_fd_pr__pfet_01v8 W={params['Wrst']}u L=0.15u nf=1
XMr4 outp clk vdd vdd sky130_fd_pr__pfet_01v8 W={params['Wrst']}u L=0.15u nf=1

XMp1 outp outn vdd vdd sky130_fd_pr__pfet_01v8 W={params['Wlatp']}u L={params['Llatp']}u nf=1
XMp2 outn outp vdd vdd sky130_fd_pr__pfet_01v8 W={params['Wlatp']}u L={params['Llatp']}u nf=1

XMn1 outp outn d1 vss sky130_fd_pr__nfet_01v8 W={params['Wlatn']}u L={params['Llatn']}u nf=1
XMn2 outn outp d2 vss sky130_fd_pr__nfet_01v8 W={params['Wlatn']}u L={params['Llatn']}u nf=1

XMbp1 bufp outp vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u nf=1
XMbn1 bufp outp vss vss sky130_fd_pr__nfet_01v8 W=1u L=0.15u nf=1
XMbp2 bufn outn vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u nf=1
XMbn2 bufn outn vss vss sky130_fd_pr__nfet_01v8 W=1u L=0.15u nf=1

.options reltol=0.003 method=gear
.temp {temp}

.control
tran 0.1n 300n
meas tran outp_val find v(bufp) at=125n
meas tran outm_val find v(bufn) at=125n
meas tran tclk when v(clk)=0.9 rise=2
meas tran tout_rise when v(bufp)=0.9 rise=2
meas tran avg_idd avg i(Vdd) from=50n to=250n
echo "RESULT_OUTP_VAL $&outp_val"
echo "RESULT_OUTM_VAL $&outm_val"
echo "RESULT_TCLK $&tclk"
echo "RESULT_TOUT_RISE $&tout_rise"
echo "RESULT_AVG_IDD $&avg_idd"
echo "RESULT_DONE"
.endc
.end
"""


def run_sim(params, corner, temp, supply, use_lvt=False):
    netlist = make_netlist(params, corner, temp, supply, use_lvt_input=use_lvt)
    tmp = tempfile.mktemp(suffix=".cir")
    with open(tmp, "w") as f:
        f.write(netlist)

    result = subprocess.run([NGSPICE, "-b", tmp], capture_output=True, text=True,
                           timeout=120, cwd=PROJECT_DIR)
    os.unlink(tmp)
    output = result.stdout + result.stderr

    if "RESULT_DONE" not in output:
        return {"delay": 999, "ok": False, "power": 0}

    measurements = {}
    for line in output.split("\n"):
        if "RESULT_" in line and "RESULT_DONE" not in line:
            match = re.search(r'(RESULT_\w+)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', line)
            if match:
                measurements[match.group(1)] = float(match.group(2))

    tclk = measurements.get("RESULT_TCLK", 0)
    tout = measurements.get("RESULT_TOUT_RISE", 0)
    delay = (tout - tclk) * 1e9 if tclk > 0 and tout > tclk else 999
    delay = max(0.1, min(999, delay))

    outp = measurements.get("RESULT_OUTP_VAL", 0)
    outm = measurements.get("RESULT_OUTM_VAL", 0)
    ok = outp > outm

    avg_idd = measurements.get("RESULT_AVG_IDD", 0)
    power = abs(avg_idd) * supply * 1e6

    return {"delay": delay, "ok": ok, "power": power}


# Compare standard vs LVT at key corners
corners = [
    ("tt", 24, 1.8),
    ("tt", 24, 1.2),
    ("ss", -40, 1.2),
    ("fs", -40, 1.2),
    ("ff", 175, 1.8),
    ("sf", -40, 1.2),
]

print("=" * 100)
print("STANDARD vs LVT INPUT PAIR COMPARISON")
print("=" * 100)
print(f"{'Corner':<15} | {'Std Delay':>10} {'Std OK':>7} {'Std Pwr':>8} | "
      f"{'LVT Delay':>10} {'LVT OK':>7} {'LVT Pwr':>8} | {'Speed Δ':>8}")
print("-" * 100)

for corner, temp, supply in corners:
    std = run_sim(best_params, corner, temp, supply, use_lvt=False)
    lvt = run_sim(best_params, corner, temp, supply, use_lvt=True)

    delta = ((std["delay"] - lvt["delay"]) / std["delay"] * 100) if std["delay"] > 0 else 0

    print(f"{corner:>2}/{temp:>4}°C/{supply:.1f}V | "
          f"{std['delay']:>10.2f} {'OK' if std['ok'] else 'FAIL':>7} {std['power']:>7.2f}μW | "
          f"{lvt['delay']:>10.2f} {'OK' if lvt['ok'] else 'FAIL':>7} {lvt['power']:>7.2f}μW | "
          f"{delta:>+7.1f}%")

print("\nDone.")
