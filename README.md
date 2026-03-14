# SKY130 StrongARM Comparator — Autonomous Design

> **Status:** Not yet optimized — awaiting first design run.

## Overview

Autonomous design of a StrongARM latch comparator in SkyWater SKY130 (130nm) technology, optimized to meet offset and speed specifications across all PVT corners and Monte Carlo mismatch.

| Spec | Target | Worst-Case Result | Margin | Status |
|------|--------|-------------------|--------|--------|
| Input-referred offset | < 5 mV | — | — | Pending |
| Rise-time delay (CLK→output) | < 100 ns | — | — | Pending |

**Validation scope:** 30 PVT corners (3 temps × 2 supplies × 5 process) + 200-sample Monte Carlo at mean ± 4.5σ.

---

## Architecture

*Section will be updated with the chosen topology, schematic, and design rationale.*

<!-- After design: include schematic SVG, topology description, and why this architecture was chosen -->

---

## Design Parameters

*Section will be updated with optimized transistor sizes and key dimensions.*

<!-- After design: table of all parameters with values, units, and brief rationale -->

| Parameter | Value | Unit | Role |
|-----------|-------|------|------|
| — | — | — | — |

---

## Key Design Decisions & Rationale

*Section will be updated with the reasoning behind major design choices.*

<!-- After design: document tradeoffs, why certain sizes were chosen, what was tried and rejected -->

---

## Simulation Results

### Nominal Corner (tt, 24°C, 1.8V)

*Section will be updated with nominal results.*

<!-- After design: offset, delay, power, current densities -->

### Transient Waveforms

*Section will include annotated waveform plots showing proper comparator operation.*

<!-- After design: include plots/waveforms_nominal.png, plots/waveforms_worst.png -->
<!-- Annotate: precharge phase, evaluation phase, regeneration, output valid point -->

### Operating Point Verification

*Section will confirm all transistors operate in expected regions.*

<!-- After design: table showing Vgs, Vds, Vth, region for each transistor at nominal -->

---

## PVT Corner Analysis

*Section will be updated with full PVT sweep results.*

<!-- After design: include plots/pvt_corners.png -->

| Corner | Temp (°C) | Supply (V) | Offset (mV) | Delay (ns) | Status |
|--------|-----------|------------|-------------|------------|--------|
| — | — | — | — | — | — |

**Worst-case corner:** —
**Limiting factor:** —

---

## Monte Carlo Analysis

*Section will be updated with MC results and distribution plots.*

<!-- After design: include plots/monte_carlo.png -->

| Metric | Mean | Std | Mean + 4.5σ | Spec | Status |
|--------|------|-----|-------------|------|--------|
| Offset (mV) | — | — | — | < 5 | — |
| Delay (ns) | — | — | — | < 100 | — |

**Mismatch model:** Avt = 5 mV·μm for sky130 nfet_01v8, σ_Vth = Avt / √(W×L)

---

## Design Quality Assessment

### Power Consumption

| Corner | Power (μW) | Notes |
|--------|-----------|-------|
| — | — | — |

### Current Densities

| Transistor | I/W (μA/μm) | Expected Range | Status |
|------------|-------------|----------------|--------|
| — | — | 1–100 | — |

### Area Estimate

| Metric | Value |
|--------|-------|
| Total gate area (W×L sum) | — μm² |
| Reasonableness | — |

### Design Margin Summary

| Spec | Target | Worst-Case | Margin (%) | Assessment |
|------|--------|-----------|------------|------------|
| Offset | < 5 mV | — | — | — |
| Delay | < 100 ns | — | — | — |

---

## Robustness & Limitations

*Section will document known weaknesses, tradeoffs, and what a designer should watch for in layout.*

<!-- After design: kickback noise, metastability window, sensitivity to layout parasitics -->

---

## Optimization History

*Section will track the optimization approach and iterations.*

| Step | Method | Topology | Score | Specs Met | Notes |
|------|--------|----------|-------|-----------|-------|
| — | — | — | — | — | — |

---

## How to Reproduce

```bash
# 1. Setup PDK models (run once)
bash setup.sh

# 2. Run validation on existing parameters
python evaluate.py

# 3. Run quick validation (fewer corners)
python evaluate.py --quick
```

---

## File Structure

```
sky130-comparator/
├── CLAUDE.md            # Agent instructions
├── program.md           # Design methodology & requirements
├── specs.json           # Target specifications (DO NOT EDIT)
├── design.cir           # Parametric SPICE netlist
├── parameters.csv       # Design parameter ranges
├── evaluate.py          # Simulation & validation utilities
├── setup.sh             # PDK setup script
├── best_parameters.csv  # Optimized parameter values
├── measurements.json    # Latest measurement results
├── results.tsv          # Experiment history log
├── README.md            # This file — design summary & results
└── plots/
    ├── pvt_corners.png  # PVT corner sweep results
    ├── monte_carlo.png  # Monte Carlo distributions
    ├── waveforms_*.png  # Transient waveform plots
    └── progress.png     # Optimization progress
```
