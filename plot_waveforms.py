#!/usr/bin/env python3
"""Generate waveform plots for the current best design."""

import os
import sys
import csv
import re
import tempfile
import subprocess
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from evaluate import load_design, format_netlist, PROJECT_DIR, NGSPICE

PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

# Load best parameters
best_params = {}
with open("best_parameters.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        best_params[row["name"]] = float(row["value"])

print("Parameters:", best_params)
template = load_design()

dark_theme = {
    'figure.facecolor': '#1a1a2e', 'axes.facecolor': '#16213e',
    'axes.edgecolor': '#e94560', 'axes.labelcolor': '#eee',
    'text.color': '#eee', 'xtick.color': '#aaa', 'ytick.color': '#aaa',
    'grid.color': '#333', 'grid.alpha': 0.5, 'lines.linewidth': 1.5,
}
plt.rcParams.update(dark_theme)


def run_transient_and_save(params, corner, temp, supply, label, filename):
    """Run transient and save raw data, then plot."""
    vcm = supply / 2.0
    vdiff = 0.005  # 5mV

    # Create netlist that saves raw data
    netlist = format_netlist(template, params,
                            corner=corner, temperature=temp,
                            supply_v=supply,
                            vinp=vcm + vdiff/2, vinm=vcm - vdiff/2)

    # Replace .control section to write rawfile
    netlist_save = netlist.replace(
        ".control\n",
        ".control\nset filetype=ascii\n"
    )
    # Add wrdata before the echo lines
    netlist_save = netlist_save.replace(
        'echo "RESULT_OUTP_VAL',
        f'wrdata {PLOTS_DIR}/{filename}.dat v(clk) v(d1) v(d2) v(outp) v(outn) v(bufp) v(bufn) v(ntail)\necho "RESULT_OUTP_VAL'
    )

    tmp = tempfile.mktemp(suffix=".cir", prefix="waveform_")
    with open(tmp, "w") as f:
        f.write(netlist_save)

    result = subprocess.run(
        [NGSPICE, "-b", tmp],
        capture_output=True, text=True, timeout=120,
        cwd=PROJECT_DIR
    )
    os.unlink(tmp)

    # Parse the wrdata output
    datafile = f"{PLOTS_DIR}/{filename}.dat"
    if not os.path.exists(datafile):
        print(f"  WARNING: {datafile} not found")
        return

    # wrdata format: time v1 v2 v3 ...
    data = []
    with open(datafile) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('T'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    vals = [float(x) for x in parts]
                    data.append(vals)
                except ValueError:
                    continue

    if not data:
        print(f"  WARNING: No data in {datafile}")
        return

    data = np.array(data)
    # wrdata outputs two columns per signal (real, imag for complex)
    # For transient: time, v1_real, v1_imag, v2_real, v2_imag, ...
    time_ns = data[:, 0] * 1e9

    # Extract every other column (real parts only)
    clk = data[:, 1]
    d1 = data[:, 3] if data.shape[1] > 3 else np.zeros_like(time_ns)
    d2 = data[:, 5] if data.shape[1] > 5 else np.zeros_like(time_ns)
    outp = data[:, 7] if data.shape[1] > 7 else np.zeros_like(time_ns)
    outn = data[:, 9] if data.shape[1] > 9 else np.zeros_like(time_ns)
    bufp = data[:, 11] if data.shape[1] > 11 else np.zeros_like(time_ns)
    bufn = data[:, 13] if data.shape[1] > 13 else np.zeros_like(time_ns)
    ntail = data[:, 15] if data.shape[1] > 15 else np.zeros_like(time_ns)

    # Plot
    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)

    axes[0].plot(time_ns, clk, color='#e94560', label='CLK')
    axes[0].set_ylabel('CLK (V)')
    axes[0].legend(loc='upper right', fontsize=8)
    axes[0].set_title(f'StrongARM Waveforms — {label}')
    axes[0].grid(True)

    axes[1].plot(time_ns, d1, color='#0f3460', label='d1')
    axes[1].plot(time_ns, d2, color='#e94560', label='d2', linestyle='--')
    axes[1].set_ylabel('Internal (V)')
    axes[1].legend(loc='upper right', fontsize=8)
    axes[1].grid(True)

    axes[2].plot(time_ns, outp, color='#0f3460', label='outp')
    axes[2].plot(time_ns, outn, color='#e94560', label='outn', linestyle='--')
    axes[2].set_ylabel('Latch (V)')
    axes[2].legend(loc='upper right', fontsize=8)
    axes[2].grid(True)

    axes[3].plot(time_ns, bufp, color='#0f3460', label='bufp')
    axes[3].plot(time_ns, bufn, color='#e94560', label='bufn', linestyle='--')
    axes[3].set_ylabel('Buffer (V)')
    axes[3].set_xlabel('Time (ns)')
    axes[3].legend(loc='upper right', fontsize=8)
    axes[3].grid(True)

    plt.tight_layout()
    plt.savefig(f'{PLOTS_DIR}/{filename}.png', dpi=150)
    plt.close()
    print(f"  Saved {PLOTS_DIR}/{filename}.png")

    # Clean up data file
    os.unlink(datafile)


# Generate waveforms at key corners
print("Generating nominal waveform...")
run_transient_and_save(best_params, "tt", 24, 1.8,
                       "tt/24°C/1.8V, Vdiff=5mV", "waveforms_nominal")

print("Generating worst-delay waveform...")
run_transient_and_save(best_params, "fs", -40, 1.2,
                       "fs/-40°C/1.2V, Vdiff=5mV (worst delay)", "waveforms_worst_delay")

print("Generating swap test waveform...")
# Swap inputs to verify comparator works
params_swap = dict(best_params)
# We need to modify the netlist for swapped inputs
template_swap = template  # Will swap via vinp/vinm
vcm = 1.8 / 2.0
netlist_normal = format_netlist(template, best_params, corner="tt", temperature=24,
                               supply_v=1.8, vinp=vcm + 0.0025, vinm=vcm - 0.0025)
netlist_swap = format_netlist(template, best_params, corner="tt", temperature=24,
                              supply_v=1.8, vinp=vcm - 0.0025, vinm=vcm + 0.0025)

# Run swap test
for name, nl in [("normal", netlist_normal), ("swapped", netlist_swap)]:
    tmp = tempfile.mktemp(suffix=".cir")
    with open(tmp, "w") as f:
        f.write(nl)
    result = subprocess.run([NGSPICE, "-b", tmp], capture_output=True, text=True,
                           timeout=120, cwd=PROJECT_DIR)
    os.unlink(tmp)
    output = result.stdout + result.stderr

    # Parse results
    for line in output.split("\n"):
        if "RESULT_OUTP_VAL" in line:
            match = re.search(r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', line.split("RESULT_OUTP_VAL")[1])
            if match:
                print(f"  {name}: bufp = {float(match.group(1)):.4f}V")
        if "RESULT_OUTM_VAL" in line:
            match = re.search(r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', line.split("RESULT_OUTM_VAL")[1])
            if match:
                print(f"  {name}: bufn = {float(match.group(1)):.4f}V")

print("\nDone generating waveforms.")
