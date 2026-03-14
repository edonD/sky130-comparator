"""
evaluate.py — Simulation and validation utilities for comparator design.

Provides:
- NGSpice simulation runner (single sim at any PVT corner)
- Offset measurement via binary search
- PVT corner sweep (30 combinations)
- Monte Carlo analysis (200 samples, mean ± 4.5σ)
- Cost function, scoring, and plotting

This file does NOT contain an optimizer. The agent chooses and implements
its own optimization strategy (Bayesian Opt, PSO, CMA-ES, etc.).

Usage as utility library:
    from evaluate import (load_parameters, load_design, load_specs,
                          run_simulation, compute_cost,
                          run_pvt_sweep, run_monte_carlo, ...)

Usage standalone (validate existing best_parameters.csv):
    python evaluate.py                   # full validation
    python evaluate.py --quick           # quick validation (fewer corners)
"""

import os
import sys
import re
import json
import csv
import time
import argparse
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NGSPICE = os.environ.get("NGSPICE", "ngspice")
DESIGN_FILE = "design.cir"
PARAMS_FILE = "parameters.csv"
SPECS_FILE = "specs.json"
RESULTS_FILE = "results.tsv"
PLOTS_DIR = "plots"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# PVT corners
TEMPERATURES = [-40, 24, 175]
SUPPLY_VOLTAGES = [1.2, 1.8]
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]

# Monte Carlo settings
MC_N_SAMPLES = 200
MC_SIGMA_TARGET = 4.5

# Nominal corner
NOMINAL_CORNER = "tt"
NOMINAL_TEMP = 24
NOMINAL_SUPPLY = 1.8

# ---------------------------------------------------------------------------
# Parameter loading
# ---------------------------------------------------------------------------

def load_parameters(path: str = PARAMS_FILE) -> List[Dict]:
    params = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params.append({
                "name": row["name"].strip(),
                "min": float(row["min"]),
                "max": float(row["max"]),
                "scale": row.get("scale", "lin").strip(),
            })
    return params


def load_design(path: str = DESIGN_FILE) -> str:
    with open(path) as f:
        return f.read()


def load_specs(path: str = SPECS_FILE) -> Dict:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_design(template: str, params: List[Dict]) -> List[str]:
    errors = []
    circuit_lines = []
    in_control = False
    for line in template.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith(".control"):
            in_control = True
        if not in_control and not stripped.startswith("*"):
            circuit_lines.append(line)
        if stripped.lower().startswith(".endc"):
            in_control = False
    circuit_text = "\n".join(circuit_lines)
    placeholders = set(re.findall(r'\{(\w+)\}', circuit_text))
    param_names = {p["name"] for p in params}

    # These are set by the evaluator, not design parameters
    evaluator_params = {"corner", "Vsupply", "temperature", "Vinp", "Vinm"}
    design_placeholders = placeholders - evaluator_params

    for m in sorted(design_placeholders - param_names):
        errors.append(f"Placeholder {{{m}}} in design.cir has no entry in parameters.csv")
    for u in sorted(param_names - design_placeholders):
        errors.append(f"Parameter '{u}' in parameters.csv is not used in design.cir")

    return errors


# ---------------------------------------------------------------------------
# NGSpice simulation
# ---------------------------------------------------------------------------

def format_netlist(template: str, param_values: Dict[str, float],
                   corner: str = "tt", temperature: int = 24,
                   supply_v: float = 1.8, vinp: float = 0.9,
                   vinm: float = 0.9) -> str:
    """Substitute all parameters including PVT settings."""
    all_params = dict(param_values)
    all_params["corner"] = corner
    all_params["temperature"] = str(temperature)
    all_params["Vsupply"] = str(supply_v)
    all_params["Vinp"] = str(vinp)
    all_params["Vinm"] = str(vinm)

    def _replace(match):
        key = match.group(1)
        if key in all_params:
            return str(all_params[key])
        return match.group(0)
    return re.sub(r'\{(\w+)\}', _replace, template)


def run_simulation(template: str, param_values: Dict[str, float],
                   idx: int, tmp_dir: str,
                   corner: str = "tt", temperature: int = 24,
                   supply_v: float = 1.8) -> Dict:
    """Run a single comparator simulation at a given PVT corner.

    Returns dict with keys: idx, error, measurements.
    """
    vcm = supply_v / 2.0
    vdiff = 0.005  # 5mV differential for sensitivity check

    try:
        netlist = format_netlist(template, param_values,
                                 corner=corner, temperature=temperature,
                                 supply_v=supply_v,
                                 vinp=vcm + vdiff/2, vinm=vcm - vdiff/2)
    except Exception as e:
        return {"idx": idx, "error": f"format error: {e}", "measurements": {}}

    path = os.path.join(tmp_dir, f"sim_{idx}_{corner}_T{temperature}_V{supply_v}.cir")
    with open(path, "w") as f:
        f.write(netlist)

    try:
        result = subprocess.run(
            [NGSPICE, "-b", path],
            capture_output=True, text=True, timeout=120,
            cwd=PROJECT_DIR
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"idx": idx, "error": "timeout", "measurements": {}}
    except Exception as e:
        return {"idx": idx, "error": str(e), "measurements": {}}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if "RESULT_DONE" not in output:
        return {"idx": idx, "error": "no_RESULT_DONE", "measurements": {},
                "output_tail": output[-500:]}

    measurements = parse_ngspice_output(output)
    measurements = compute_derived_metrics(measurements, supply_v)
    measurements["corner"] = corner
    measurements["temperature"] = temperature
    measurements["supply_v"] = supply_v
    return {"idx": idx, "error": None, "measurements": measurements}


def parse_ngspice_output(output: str) -> Dict[str, float]:
    m = {}
    for line in output.split("\n"):
        if "RESULT_" in line and "RESULT_DONE" not in line:
            match = re.search(r'(RESULT_\w+)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', line)
            if match:
                m[match.group(1)] = float(match.group(2))

        stripped = line.strip()
        if "=" in stripped and not stripped.startswith((".", "*", "+")):
            parts = stripped.split("=", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                val_match = re.search(r'([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', parts[1])
                if val_match and name and len(name) < 40 and not name.startswith("("):
                    try:
                        m[name] = float(val_match.group(1))
                    except ValueError:
                        pass
    return m


def compute_derived_metrics(measurements: Dict[str, float],
                            supply_v: float = 1.8) -> Dict[str, float]:
    """Compute comparator metrics from raw ngspice measurements."""
    # Rise-time delay
    tclk = measurements.get("RESULT_TCLK", 0)
    tout = measurements.get("RESULT_TOUT_RISE", 0)
    if tclk > 0 and tout > tclk:
        rise_delay_ns = (tout - tclk) * 1e9
    else:
        rise_delay_ns = 999.0  # penalize failed measurement
    rise_delay_ns = max(0.1, min(999.0, rise_delay_ns))
    measurements["RESULT_RISE_TIME_DELAY_NS"] = rise_delay_ns

    # Sensitivity check: did the comparator resolve correctly?
    outp = measurements.get("RESULT_OUTP_VAL", 0)
    outm = measurements.get("RESULT_OUTM_VAL", 0)
    if outp > outm:
        measurements["RESULT_SENSITIVITY_OK"] = 1
        measurements["RESULT_OFFSET_MV"] = 0.0  # offset < applied 5mV
    else:
        measurements["RESULT_SENSITIVITY_OK"] = 0
        measurements["RESULT_OFFSET_MV"] = 50.0  # penalize — offset > 5mV

    # Power from average supply current
    avg_idd = measurements.get("RESULT_AVG_IDD", 0)
    power_uw = abs(avg_idd) * supply_v * 1e6
    measurements["RESULT_POWER_UW"] = power_uw

    return measurements


def run_offset_binary_search(template: str, param_values: Dict[str, float],
                              tmp_dir: str, corner: str = "tt",
                              temperature: int = 24, supply_v: float = 1.8,
                              n_steps: int = 12) -> float:
    """Binary search for comparator trip point to accurately measure offset.

    Returns offset in mV.
    """
    vcm = supply_v / 2.0
    v_lo = -50e-3  # -50mV
    v_hi = 50e-3   # +50mV

    for step in range(n_steps):
        v_mid = (v_lo + v_hi) / 2.0
        vinp = vcm + v_mid / 2.0
        vinm = vcm - v_mid / 2.0

        try:
            netlist = format_netlist(template, param_values,
                                     corner=corner, temperature=temperature,
                                     supply_v=supply_v, vinp=vinp, vinm=vinm)
        except Exception:
            return 50.0

        path = os.path.join(tmp_dir, f"offset_search_{step}.cir")
        with open(path, "w") as f:
            f.write(netlist)

        try:
            result = subprocess.run(
                [NGSPICE, "-b", path],
                capture_output=True, text=True, timeout=60,
                cwd=PROJECT_DIR
            )
            output = result.stdout + result.stderr
        except Exception:
            return 50.0
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        if "RESULT_DONE" not in output:
            return 50.0

        measurements = parse_ngspice_output(output)
        outp = measurements.get("RESULT_OUTP_VAL", 0)
        outm = measurements.get("RESULT_OUTM_VAL", 0)

        if outp > outm:
            v_hi = v_mid
        else:
            v_lo = v_mid

    trip_point = (v_lo + v_hi) / 2.0
    offset_mv = abs(trip_point) * 1000.0
    return offset_mv


# ---------------------------------------------------------------------------
# Cost function — usable by any optimizer
# ---------------------------------------------------------------------------

def compute_cost(measurements: Dict[str, float], specs: Dict = None) -> float:
    """Cost function for optimization — evaluates at nominal corner only for speed.

    Returns a scalar cost (lower is better). Any optimizer can call this.
    """
    if not measurements:
        return 1e6

    cost = 0.0

    # Offset penalty
    offset = measurements.get("RESULT_OFFSET_MV", 50.0)
    if offset < 5.0:
        cost -= (5.0 - offset) / 5.0 * 50
    else:
        cost += ((offset - 5.0) / 5.0) ** 2 * 500

    # Rise-time delay penalty
    delay = measurements.get("RESULT_RISE_TIME_DELAY_NS", 999.0)
    if delay < 100.0:
        cost -= (100.0 - delay) / 100.0 * 50
    else:
        cost += ((delay - 100.0) / 100.0) ** 2 * 500

    # Sensitivity check — heavy penalty if comparator doesn't resolve
    if measurements.get("RESULT_SENSITIVITY_OK", 0) == 0:
        cost += 1000

    return cost


def evaluate_params(template: str, param_values: Dict[str, float],
                    specs: Dict = None) -> Tuple[float, Dict]:
    """Convenience: simulate at nominal corner and return (cost, measurements).

    Useful as the objective function for any optimizer.
    """
    tmp_dir = tempfile.mkdtemp(prefix="comp_eval_")
    result = run_simulation(template, param_values, 0, tmp_dir,
                            NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY)
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass

    if result.get("error") or not result.get("measurements"):
        return 1e6, {}

    measurements = result["measurements"]
    cost = compute_cost(measurements, specs)
    return cost, measurements


# ---------------------------------------------------------------------------
# PVT Corner Sweep
# ---------------------------------------------------------------------------

def run_pvt_sweep(template: str, param_values: Dict[str, float],
                  tmp_dir: str = None, quick: bool = False) -> Dict:
    """Run comparator across all PVT corners. Returns worst-case metrics."""
    own_tmp = tmp_dir is None
    if own_tmp:
        tmp_dir = tempfile.mkdtemp(prefix="comp_pvt_")

    corners = PROCESS_CORNERS if not quick else ["tt", "ss"]
    temps = TEMPERATURES if not quick else [24, 175]
    supplies = SUPPLY_VOLTAGES

    results = []
    worst_offset = 0.0
    worst_delay = 0.0

    print("\n--- PVT Corner Sweep ---")
    for corner in corners:
        for temp in temps:
            for supply in supplies:
                offset = run_offset_binary_search(
                    template, param_values, tmp_dir,
                    corner=corner, temperature=temp, supply_v=supply
                )

                sim = run_simulation(
                    template, param_values, 0, tmp_dir,
                    corner=corner, temperature=temp, supply_v=supply
                )

                delay = 999.0
                if sim.get("measurements"):
                    delay = sim["measurements"].get("RESULT_RISE_TIME_DELAY_NS", 999.0)

                results.append({
                    "corner": corner, "temp": temp, "supply": supply,
                    "offset_mv": offset, "delay_ns": delay
                })

                worst_offset = max(worst_offset, offset)
                worst_delay = max(worst_delay, delay)

                status = "PASS" if (offset < 5.0 and delay < 100.0) else "FAIL"
                print(f"  {corner:>2s} T={temp:>4d}°C V={supply:.1f}V: "
                      f"offset={offset:>6.2f}mV  delay={delay:>7.2f}ns  [{status}]")

    if own_tmp:
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    all_pass = all(r["offset_mv"] < 5.0 and r["delay_ns"] < 100.0 for r in results)
    print(f"\n  Worst-case: offset={worst_offset:.2f}mV, delay={worst_delay:.2f}ns")
    print(f"  PVT sweep: {'ALL PASS' if all_pass else 'SOME FAIL'}")
    print("--- PVT Sweep Done ---\n")

    return {
        "results": results,
        "worst_offset_mv": worst_offset,
        "worst_delay_ns": worst_delay,
        "all_pass": all_pass,
    }


# ---------------------------------------------------------------------------
# Monte Carlo Analysis
# ---------------------------------------------------------------------------

def run_monte_carlo(template: str, param_values: Dict[str, float],
                    tmp_dir: str = None, n_samples: int = MC_N_SAMPLES,
                    quick: bool = False) -> Dict:
    """Run Monte Carlo analysis with Vth mismatch.

    Models mismatch by adding random Vth offsets to the input pair.
    In SKY130, Avt ≈ 5 mV·μm for nfet_01v8.
    sigma_Vth = Avt / sqrt(W × L)
    """
    own_tmp = tmp_dir is None
    if own_tmp:
        tmp_dir = tempfile.mkdtemp(prefix="comp_mc_")

    if quick:
        n_samples = 30

    Win = param_values.get("Win", 10.0)
    Lin = param_values.get("Lin", 0.5)
    Avt = 5.0e-3  # V·μm
    sigma_vth = Avt / np.sqrt(Win * Lin)

    print(f"\n--- Monte Carlo Analysis ({n_samples} samples) ---")
    print(f"  Input pair: W={Win:.1f}u, L={Lin:.2f}u")
    print(f"  Vth mismatch sigma: {sigma_vth*1e3:.3f} mV")

    rng = np.random.RandomState(42)
    offsets = rng.normal(0, sigma_vth, size=n_samples)

    offset_measurements = []
    delay_measurements = []

    vcm = NOMINAL_SUPPLY / 2.0

    for i, vth_offset in enumerate(offsets):
        vinp = vcm + vth_offset / 2.0
        vinm = vcm - vth_offset / 2.0

        vinp_test = vinp + 0.0025
        vinm_test = vinm - 0.0025

        try:
            netlist = format_netlist(template, param_values,
                                     corner=NOMINAL_CORNER,
                                     temperature=NOMINAL_TEMP,
                                     supply_v=NOMINAL_SUPPLY,
                                     vinp=vinp_test, vinm=vinm_test)
        except Exception:
            offset_measurements.append(50.0)
            delay_measurements.append(999.0)
            continue

        path = os.path.join(tmp_dir, f"mc_{i}.cir")
        with open(path, "w") as f:
            f.write(netlist)

        try:
            result = subprocess.run(
                [NGSPICE, "-b", path],
                capture_output=True, text=True, timeout=60,
                cwd=PROJECT_DIR
            )
            output = result.stdout + result.stderr
        except Exception:
            offset_measurements.append(50.0)
            delay_measurements.append(999.0)
            continue
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        if "RESULT_DONE" not in output:
            offset_measurements.append(50.0)
            delay_measurements.append(999.0)
            continue

        meas = parse_ngspice_output(output)
        meas = compute_derived_metrics(meas, NOMINAL_SUPPLY)

        offset_measurements.append(abs(vth_offset) * 1e3)
        delay = meas.get("RESULT_RISE_TIME_DELAY_NS", 999.0)
        delay_measurements.append(delay)

        if (i + 1) % 50 == 0:
            print(f"  Completed {i+1}/{n_samples} samples...")

    if own_tmp:
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    offsets_arr = np.array(offset_measurements)
    delays_arr = np.array(delay_measurements)

    offset_mean = np.mean(offsets_arr)
    offset_std = np.std(offsets_arr)
    offset_worst = offset_mean + MC_SIGMA_TARGET * offset_std

    delay_mean = np.mean(delays_arr)
    delay_std = np.std(delays_arr)
    delay_worst = delay_mean + MC_SIGMA_TARGET * delay_std

    print(f"\n  Offset: mean={offset_mean:.3f}mV, std={offset_std:.3f}mV, "
          f"mean+{MC_SIGMA_TARGET}σ={offset_worst:.3f}mV")
    print(f"  Delay:  mean={delay_mean:.3f}ns, std={delay_std:.3f}ns, "
          f"mean+{MC_SIGMA_TARGET}σ={delay_worst:.3f}ns")

    offset_pass = offset_worst < 5.0
    delay_pass = delay_worst < 100.0
    print(f"  Offset at {MC_SIGMA_TARGET}σ: {'PASS' if offset_pass else 'FAIL'}")
    print(f"  Delay at {MC_SIGMA_TARGET}σ: {'PASS' if delay_pass else 'FAIL'}")
    print("--- Monte Carlo Done ---\n")

    return {
        "n_samples": n_samples,
        "offset_mean_mv": offset_mean,
        "offset_std_mv": offset_std,
        "offset_worst_mv": offset_worst,
        "delay_mean_ns": delay_mean,
        "delay_std_ns": delay_std,
        "delay_worst_ns": delay_worst,
        "offset_pass": offset_pass,
        "delay_pass": delay_pass,
        "all_pass": offset_pass and delay_pass,
        "sigma_vth_mv": sigma_vth * 1e3,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _parse_target(target_str: str) -> Tuple[str, float, Optional[float]]:
    target_str = target_str.strip()
    if target_str.startswith(">"):
        return ("above", float(target_str[1:]), None)
    elif target_str.startswith("<"):
        return ("below", float(target_str[1:]), None)
    elif "-" in target_str and not target_str.startswith("-"):
        parts = target_str.split("-")
        return ("range", float(parts[0]), float(parts[1]))
    else:
        return ("exact", float(target_str), None)


def score_measurements(measurements: Dict[str, float], specs: Dict) -> Tuple[float, Dict]:
    details = {}
    total_weight = 0
    weighted_score = 0

    for spec_name, spec_def in specs["measurements"].items():
        target_str = spec_def["target"]
        weight = spec_def["weight"]
        unit = spec_def.get("unit", "")
        total_weight += weight

        direction, val1, val2 = _parse_target(target_str)
        measured = measurements.get(f"RESULT_{spec_name.upper()}", None)

        if measured is None:
            details[spec_name] = {
                "measured": None, "target": target_str, "met": False,
                "score": 0, "unit": unit
            }
            continue

        if direction == "above":
            met = measured >= val1
            spec_score = 1.0 if met else max(0, measured / val1) if val1 != 0 else 0
        elif direction == "below":
            met = measured <= val1
            spec_score = 1.0 if met else max(0, val1 / measured) if measured != 0 else 0
        elif direction == "exact":
            met = abs(measured - val1) < 0.01 * max(abs(val1), 1)
            spec_score = 1.0 if met else max(0, 1.0 - abs(measured - val1) / max(abs(val1), 1))
        else:
            met = False
            spec_score = 0

        weighted_score += weight * spec_score
        details[spec_name] = {
            "measured": measured, "target": target_str, "met": met,
            "score": spec_score, "unit": unit
        }

    overall = weighted_score / total_weight if total_weight > 0 else 0
    return overall, details


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def generate_plots(pvt_results: Dict, mc_results: Dict, measurements: Dict):
    """Generate validation plots."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("  WARNING: matplotlib not available, skipping plots")
        return

    os.makedirs(PLOTS_DIR, exist_ok=True)

    dark_theme = {
        'figure.facecolor': '#1a1a2e', 'axes.facecolor': '#16213e',
        'axes.edgecolor': '#e94560', 'axes.labelcolor': '#eee',
        'text.color': '#eee', 'xtick.color': '#aaa', 'ytick.color': '#aaa',
        'grid.color': '#333', 'grid.alpha': 0.5, 'lines.linewidth': 1.5,
    }
    plt.rcParams.update(dark_theme)

    # --- PVT Corner Plot ---
    if pvt_results and pvt_results.get("results"):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        pvt = pvt_results["results"]
        labels = [f"{r['corner']}\nT={r['temp']}\nV={r['supply']}" for r in pvt]
        offsets = [r["offset_mv"] for r in pvt]
        delays = [r["delay_ns"] for r in pvt]
        colors_off = ['#0f0' if o < 5.0 else '#e94560' for o in offsets]
        colors_del = ['#0f0' if d < 100.0 else '#e94560' for d in delays]

        ax1.bar(range(len(offsets)), offsets, color=colors_off, alpha=0.8)
        ax1.axhline(y=5.0, color='yellow', linestyle='--', label='Spec: 5 mV')
        ax1.set_xlabel('PVT Corner')
        ax1.set_ylabel('Offset (mV)')
        ax1.set_title('Offset across PVT Corners')
        ax1.set_xticks(range(len(labels)))
        ax1.set_xticklabels(labels, fontsize=5, rotation=45)
        ax1.legend(fontsize=8)
        ax1.grid(True)

        ax2.bar(range(len(delays)), delays, color=colors_del, alpha=0.8)
        ax2.axhline(y=100.0, color='yellow', linestyle='--', label='Spec: 100 ns')
        ax2.set_xlabel('PVT Corner')
        ax2.set_ylabel('Rise-time Delay (ns)')
        ax2.set_title('Delay across PVT Corners')
        ax2.set_xticks(range(len(labels)))
        ax2.set_xticklabels(labels, fontsize=5, rotation=45)
        ax2.legend(fontsize=8)
        ax2.grid(True)

        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, 'pvt_corners.png'), dpi=150)
        plt.close()

    # --- Monte Carlo Histograms ---
    if mc_results:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        ax1.axvline(x=5.0, color='yellow', linestyle='--', linewidth=2, label='Spec: 5 mV')
        worst_off = mc_results["offset_worst_mv"]
        ax1.axvline(x=worst_off, color='#e94560' if worst_off >= 5.0 else '#0f0',
                     linestyle='-', linewidth=2, label=f'Mean+{MC_SIGMA_TARGET}σ: {worst_off:.2f} mV')
        ax1.set_xlabel('Offset (mV)')
        ax1.set_ylabel('Count')
        ax1.set_title(f'MC Offset Distribution (σ_Vth={mc_results["sigma_vth_mv"]:.2f}mV)')
        ax1.legend(fontsize=8)
        ax1.grid(True)

        worst_del = mc_results["delay_worst_ns"]
        ax2.axvline(x=100.0, color='yellow', linestyle='--', linewidth=2, label='Spec: 100 ns')
        ax2.axvline(x=worst_del, color='#e94560' if worst_del >= 100.0 else '#0f0',
                     linestyle='-', linewidth=2, label=f'Mean+{MC_SIGMA_TARGET}σ: {worst_del:.2f} ns')
        ax2.set_xlabel('Delay (ns)')
        ax2.set_ylabel('Count')
        ax2.set_title('MC Delay Distribution')
        ax2.legend(fontsize=8)
        ax2.grid(True)

        plt.tight_layout()
        plt.savefig(os.path.join(PLOTS_DIR, 'monte_carlo.png'), dpi=150)
        plt.close()


def generate_progress_plot(results_file: str, plots_dir: str):
    """Generate progress.png from results.tsv."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return

    if not os.path.exists(results_file):
        return

    steps, scores, topos = [], [], []
    with open(results_file) as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            try:
                steps.append(int(row.get("step", len(steps) + 1)))
                scores.append(float(row.get("score", 0)))
                topos.append(row.get("topology", ""))
            except (ValueError, TypeError):
                continue

    if not scores:
        return

    os.makedirs(plots_dir, exist_ok=True)

    plt.rcParams.update({
        'figure.facecolor': '#1a1a2e', 'axes.facecolor': '#16213e',
        'axes.edgecolor': '#e94560', 'axes.labelcolor': '#eee',
        'text.color': '#eee', 'xtick.color': '#aaa', 'ytick.color': '#aaa',
        'grid.color': '#333', 'grid.alpha': 0.5, 'lines.linewidth': 2,
    })

    best_so_far = []
    best = -1e9
    for s in scores:
        best = max(best, s)
        best_so_far.append(best)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(steps, scores, 'o', color='#0f3460', markersize=4, alpha=0.5, label='Run score')
    ax.plot(steps, best_so_far, '-', color='#e94560', linewidth=2, label='Best so far')
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Score')
    ax.set_title('Optimization Progress')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(plots_dir, "progress.png"), dpi=150)
    plt.close()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(best_params: Dict, measurements: Dict, score: float,
                 details: Dict, specs: Dict,
                 pvt_results: Dict, mc_results: Dict, elapsed: float):
    print(f"\n{'='*70}")
    print(f"  VALIDATION REPORT — {specs.get('name', 'Comparator')}")
    print(f"{'='*70}")
    print(f"\n  Score: {score:.2f} / 1.00  |  Time: {elapsed:.1f}s")

    specs_met = sum(1 for d in details.values() if d.get("met"))
    specs_total = len(details)
    print(f"\n  Specs met: {specs_met}/{specs_total}")

    print(f"\n  {'Spec':<25} {'Target':>12} {'Measured':>12} {'Unit':>8} {'Status':>8} {'Score':>6}")
    print(f"  {'-'*73}")

    for spec_name, d in details.items():
        measured = d["measured"]
        if measured is None:
            m_str = "N/A"
        elif abs(measured) > 1e6:
            m_str = f"{measured:.2e}"
        elif abs(measured) < 0.01:
            m_str = f"{measured:.2e}"
        else:
            m_str = f"{measured:.3f}"

        status = "PASS" if d["met"] else "FAIL"
        print(f"  {spec_name:<25} {d['target']:>12} {m_str:>12} {d['unit']:>8} {status:>8} {d['score']:>5.2f}")

    if pvt_results:
        print(f"\n  PVT Worst-case:")
        print(f"    Offset: {pvt_results['worst_offset_mv']:.2f} mV  "
              f"{'PASS' if pvt_results['worst_offset_mv'] < 5.0 else 'FAIL'}")
        print(f"    Delay:  {pvt_results['worst_delay_ns']:.2f} ns  "
              f"{'PASS' if pvt_results['worst_delay_ns'] < 100.0 else 'FAIL'}")

    if mc_results:
        print(f"\n  Monte Carlo (mean ± {MC_SIGMA_TARGET}σ):")
        print(f"    Offset: {mc_results['offset_mean_mv']:.3f} ± "
              f"{mc_results['offset_std_mv']:.3f} mV → "
              f"worst={mc_results['offset_worst_mv']:.3f} mV  "
              f"{'PASS' if mc_results['offset_pass'] else 'FAIL'}")
        print(f"    Delay:  {mc_results['delay_mean_ns']:.3f} ± "
              f"{mc_results['delay_std_ns']:.3f} ns → "
              f"worst={mc_results['delay_worst_ns']:.3f} ns  "
              f"{'PASS' if mc_results['delay_pass'] else 'FAIL'}")

    print(f"\n  Best Parameters:")
    for name, val in sorted(best_params.items()):
        print(f"    {name:<20} = {val:.4e}")
    print(f"\n{'='*70}\n")

    return specs_met, specs_total


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_results(best_params: Dict, measurements: Dict, score: float,
                 details: Dict, pvt_results: Dict = None,
                 mc_results: Dict = None):
    """Save best_parameters.csv and measurements.json."""
    os.makedirs(PLOTS_DIR, exist_ok=True)

    with open("best_parameters.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "value"])
        for name, val in sorted(best_params.items()):
            w.writerow([name, val])

    with open("measurements.json", "w") as f:
        json.dump({
            "measurements": measurements,
            "score": score,
            "details": details,
            "parameters": best_params,
            "pvt": {
                "worst_offset_mv": pvt_results["worst_offset_mv"] if pvt_results else None,
                "worst_delay_ns": pvt_results["worst_delay_ns"] if pvt_results else None,
                "all_pass": pvt_results["all_pass"] if pvt_results else None,
            } if pvt_results else None,
            "monte_carlo": {
                "offset_mean_mv": mc_results["offset_mean_mv"] if mc_results else None,
                "offset_std_mv": mc_results["offset_std_mv"] if mc_results else None,
                "offset_worst_mv": mc_results["offset_worst_mv"] if mc_results else None,
                "delay_mean_ns": mc_results["delay_mean_ns"] if mc_results else None,
                "delay_std_ns": mc_results["delay_std_ns"] if mc_results else None,
                "delay_worst_ns": mc_results["delay_worst_ns"] if mc_results else None,
                "all_pass": mc_results["all_pass"] if mc_results else None,
            } if mc_results else None,
        }, f, indent=2, default=str)

    print(f"Saved: best_parameters.csv, measurements.json")


# ---------------------------------------------------------------------------
# Main — standalone validation of existing parameters
# ---------------------------------------------------------------------------

def main():
    """Validate an existing best_parameters.csv against all PVT corners + MC.

    This does NOT run optimization. The agent implements its own optimizer
    and calls evaluate_params(), run_pvt_sweep(), run_monte_carlo() etc.
    This main() is just for standalone validation.
    """
    parser = argparse.ArgumentParser(
        description="Validate comparator parameters (no optimization — use your own optimizer)")
    parser.add_argument("--quick", action="store_true", help="Quick validation (fewer corners)")
    parser.add_argument("--params-file", type=str, default="best_parameters.csv",
                        help="CSV file with parameter values (name,value)")
    args = parser.parse_args()

    print("Loading design...")
    template = load_design()
    params = load_parameters()
    specs = load_specs()

    errors = validate_design(template, params)
    if errors:
        print("\nVALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # Load parameters to validate
    if not os.path.exists(args.params_file):
        print(f"\nNo {args.params_file} found. Run your optimizer first to generate parameters.")
        print("\nAvailable utilities for your optimizer:")
        print("  from evaluate import evaluate_params, run_pvt_sweep, run_monte_carlo")
        print("  cost, meas = evaluate_params(template, param_dict)")
        sys.exit(1)

    best_params = {}
    with open(args.params_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            best_params[row["name"]] = float(row["value"])

    print(f"Design: {specs.get('name', 'Unknown')}")
    print(f"Parameters: {len(params)} (loaded {len(best_params)} values)")
    print()

    t0 = time.time()

    # Nominal simulation
    tmp_dir = tempfile.mkdtemp(prefix="comp_validate_")
    final = run_simulation(template, best_params, 0, tmp_dir,
                           NOMINAL_CORNER, NOMINAL_TEMP, NOMINAL_SUPPLY)
    measurements = final["measurements"] if not final.get("error") else {}

    # PVT Corner Sweep
    pvt_results = run_pvt_sweep(template, best_params, tmp_dir, quick=args.quick)

    # Monte Carlo Analysis
    mc_results = run_monte_carlo(template, best_params, tmp_dir, quick=args.quick)

    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass

    # Update measurements with worst-case values
    if pvt_results and mc_results:
        measurements["RESULT_OFFSET_MV"] = max(
            pvt_results["worst_offset_mv"],
            mc_results["offset_worst_mv"]
        )
        measurements["RESULT_RISE_TIME_DELAY_NS"] = max(
            pvt_results["worst_delay_ns"],
            mc_results["delay_worst_ns"]
        )

    elapsed = time.time() - t0
    score, details = score_measurements(measurements, specs)

    print_report(best_params, measurements, score, details, specs,
                 pvt_results, mc_results, elapsed)

    generate_plots(pvt_results, mc_results, measurements)
    generate_progress_plot(RESULTS_FILE, PLOTS_DIR)
    save_results(best_params, measurements, score, details, pvt_results, mc_results)

    pvt_ok = pvt_results and pvt_results["all_pass"]
    mc_ok = mc_results and mc_results["all_pass"]
    print(f"Score: {score:.2f} | PVT: {'PASS' if pvt_ok else 'FAIL'} | "
          f"MC: {'PASS' if mc_ok else 'FAIL'}")

    return score


if __name__ == "__main__":
    score = main()
    sys.exit(0 if score >= 0.9 else 1)
