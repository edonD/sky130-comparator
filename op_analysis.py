#!/usr/bin/env python3
"""Operating point analysis — verify transistor operating regions and current densities."""

import os, re, tempfile, subprocess, csv
import numpy as np
from evaluate import load_design, format_netlist, PROJECT_DIR, NGSPICE

# Load best parameters
best_params = {}
with open("best_parameters.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        best_params[row["name"]] = float(row["value"])

print("Parameters:", best_params)
template = load_design()

# Create an OP analysis netlist (at nominal corner during evaluation phase)
vcm = 0.9
vdiff = 0.005
supply = 1.8

# Modify the netlist for OP analysis at mid-evaluation
# Set CLK=VDD (evaluation mode), inputs at Vcm ± Vdiff/2
op_netlist = f"""* SKY130 StrongARM — Operating Point Analysis
* During evaluation phase (CLK=VDD)
.lib "sky130_models/sky130.lib.spice" tt

Vdd vdd 0 DC {supply}
Vss vss 0 DC 0
Vclk clk 0 DC {supply}
Vinp inp 0 DC {vcm + vdiff/2}
Vinm inm 0 DC {vcm - vdiff/2}

* Tail NMOS
XMtail ntail clk vss vss sky130_fd_pr__nfet_01v8 W={best_params['Wtail']}u L={best_params['Ltail']}u nf=1

* Input differential pair
XM1 d1 inp ntail vss sky130_fd_pr__nfet_01v8 W={best_params['Win']}u L={best_params['Lin']}u nf=1
XM2 d2 inm ntail vss sky130_fd_pr__nfet_01v8 W={best_params['Win']}u L={best_params['Lin']}u nf=1

* Reset PMOS (CLK=VDD → OFF during evaluation)
XMr1 d1 clk vdd vdd sky130_fd_pr__pfet_01v8 W={best_params['Wrst']}u L=0.15u nf=1
XMr2 d2 clk vdd vdd sky130_fd_pr__pfet_01v8 W={best_params['Wrst']}u L=0.15u nf=1
XMr3 outn clk vdd vdd sky130_fd_pr__pfet_01v8 W={best_params['Wrst']}u L=0.15u nf=1
XMr4 outp clk vdd vdd sky130_fd_pr__pfet_01v8 W={best_params['Wrst']}u L=0.15u nf=1

* Cross-coupled PMOS latch
XMp1 outp outn vdd vdd sky130_fd_pr__pfet_01v8 W={best_params['Wlatp']}u L={best_params['Llatp']}u nf=1
XMp2 outn outp vdd vdd sky130_fd_pr__pfet_01v8 W={best_params['Wlatp']}u L={best_params['Llatp']}u nf=1

* Cross-coupled NMOS latch
XMn1 outp outn d1 vss sky130_fd_pr__nfet_01v8 W={best_params['Wlatn']}u L={best_params['Llatn']}u nf=1
XMn2 outn outp d2 vss sky130_fd_pr__nfet_01v8 W={best_params['Wlatn']}u L={best_params['Llatn']}u nf=1

* Buffers
XMbp1 bufp outp vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u nf=1
XMbn1 bufp outp vss vss sky130_fd_pr__nfet_01v8 W=1u L=0.15u nf=1
XMbp2 bufn outn vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u nf=1
XMbn2 bufn outn vss vss sky130_fd_pr__nfet_01v8 W=1u L=0.15u nf=1

.temp 24

.control
op

* Print node voltages
echo "=== NODE VOLTAGES ==="
print v(vdd) v(clk) v(inp) v(inm)
print v(ntail) v(d1) v(d2) v(outp) v(outn) v(bufp) v(bufn)

* Print device operating info
echo "=== DEVICE CURRENTS ==="
echo "Tail: @m.xmtail.msky130_fd_pr__nfet_01v8[id]"
print @m.xmtail.msky130_fd_pr__nfet_01v8[id]
print @m.xmtail.msky130_fd_pr__nfet_01v8[vgs]
print @m.xmtail.msky130_fd_pr__nfet_01v8[vds]
print @m.xmtail.msky130_fd_pr__nfet_01v8[vth]
print @m.xmtail.msky130_fd_pr__nfet_01v8[gm]

echo "Input M1: @m.xm1.msky130_fd_pr__nfet_01v8[id]"
print @m.xm1.msky130_fd_pr__nfet_01v8[id]
print @m.xm1.msky130_fd_pr__nfet_01v8[vgs]
print @m.xm1.msky130_fd_pr__nfet_01v8[vds]
print @m.xm1.msky130_fd_pr__nfet_01v8[vth]
print @m.xm1.msky130_fd_pr__nfet_01v8[gm]

echo "Input M2: @m.xm2.msky130_fd_pr__nfet_01v8[id]"
print @m.xm2.msky130_fd_pr__nfet_01v8[id]
print @m.xm2.msky130_fd_pr__nfet_01v8[vgs]
print @m.xm2.msky130_fd_pr__nfet_01v8[vds]
print @m.xm2.msky130_fd_pr__nfet_01v8[vth]
print @m.xm2.msky130_fd_pr__nfet_01v8[gm]

echo "PMOS latch P1: @m.xmp1.msky130_fd_pr__pfet_01v8[id]"
print @m.xmp1.msky130_fd_pr__pfet_01v8[id]
print @m.xmp1.msky130_fd_pr__pfet_01v8[vgs]
print @m.xmp1.msky130_fd_pr__pfet_01v8[vds]

echo "NMOS latch N1: @m.xmn1.msky130_fd_pr__nfet_01v8[id]"
print @m.xmn1.msky130_fd_pr__nfet_01v8[id]
print @m.xmn1.msky130_fd_pr__nfet_01v8[vgs]
print @m.xmn1.msky130_fd_pr__nfet_01v8[vds]

echo "OP_DONE"
.endc

.end
"""

tmp = tempfile.mktemp(suffix=".cir", prefix="op_")
with open(tmp, "w") as f:
    f.write(op_netlist)

result = subprocess.run([NGSPICE, "-b", tmp], capture_output=True, text=True,
                       timeout=120, cwd=PROJECT_DIR)
os.unlink(tmp)

output = result.stdout + result.stderr
print("\n" + "=" * 70)
print("OPERATING POINT ANALYSIS — tt/24°C/1.8V, CLK=VDD (evaluation)")
print("=" * 70)

# Parse and display
for line in output.split("\n"):
    line = line.strip()
    if "===" in line or "OP_DONE" in line:
        print(f"\n{line}")
    elif "=" in line and ("v(" in line.lower() or "@" in line.lower()):
        print(f"  {line}")
    elif line.startswith("m.") or line.startswith("@m."):
        print(f"  {line}")

# Extract key values for analysis
print("\n" + "=" * 70)
print("DESIGN QUALITY ANALYSIS")
print("=" * 70)

# Parse values from output
values = {}
for line in output.split("\n"):
    for pattern in [r'v\((\w+)\)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)',
                    r'@(m\.\w+\.\w+\[\w+\])\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)']:
        matches = re.findall(pattern, line)
        for name, val in matches:
            values[name] = float(val)

# Print useful info
Win = best_params['Win']
Lin = best_params['Lin']
Wtail = best_params['Wtail']
Ltail = best_params['Ltail']

# Try to extract tail current
for key in values:
    if 'xmtail' in key and 'id' in key:
        itail = abs(values[key])
        print(f"\n  Tail current: {itail*1e6:.2f} μA")
        print(f"  Tail current density: {itail*1e6/Wtail:.2f} μA/μm (target: 1-100)")
    if 'xm1' in key and 'id' in key:
        im1 = abs(values[key])
        print(f"  Input M1 current: {im1*1e6:.2f} μA")
        print(f"  Input pair current density: {im1*1e6/Win:.2f} μA/μm (target: 1-100)")

# Node voltages
for node in ['ntail', 'd1', 'd2', 'outp', 'outn']:
    if node in values:
        print(f"  V({node}) = {values[node]:.4f}V")

print(f"\n  Input pair: W={Win}μm, L={Lin}μm, W×L={Win*Lin:.0f}μm²")
print(f"  Tail: W={Wtail}μm, L={Ltail}μm")
print(f"  σ_Vth = {5.0/np.sqrt(Win*Lin):.3f} mV")
