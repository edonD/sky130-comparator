# SKY130 StrongARM Comparator — Autonomous Design

> **Status: VALIDATED — Score 1.00/1.00, all specs met with healthy margin.**

## Overview

StrongARM latch comparator in SkyWater SKY130 (130nm) technology, designed and validated across all PVT corners and Monte Carlo mismatch.

| Spec | Target | Worst-Case Result | Margin | Status |
|------|--------|-------------------|--------|--------|
| Input-referred offset | < 5 mV | 2.32 mV (MC 4.5σ) | 53.7% | **PASS** |
| Rise-time delay (CLK→output) | < 100 ns | 11.83 ns (PVT) | 88.2% | **PASS** |

**Validation scope:** 30 PVT corners (3 temps × 2 supplies × 5 process) + 200-sample Monte Carlo at mean ± 4.5σ.

---

## Architecture

Classic StrongARM latch comparator with output buffers:

```
                    VDD
                     |
            +--[Reset PMOS]--+--[Reset PMOS]--+
            |                |                |
   CLK--[Reset]     +--[Latch PMOS]--+        |
            |       |        |       |        |
           outp ----+--------+---- outn       |
            |       |                |        |
   +--[Latch NMOS]--+        +--[Latch NMOS]--+
   |                         |
   d1                        d2
   |                         |
  [M1 inp]            [M2 inm]   <-- Input differential pair
   |                         |
   +--------[Tail NMOS]------+   <-- CLK-gated tail current
                |
               VSS
```

**Why StrongARM?** The StrongARM topology is ideal for this application because:
- Zero static power (dynamic-only switching during evaluation)
- Natural rail-to-rail outputs (no need for sense amplifier)
- Excellent common-mode rejection through the differential pair
- Well-understood offset vs. area tradeoff

**Output buffers:** Simple CMOS inverters (W_p=2u, W_n=1u, L=0.15u) provide clean digital outputs.

---

## Design Parameters

| Parameter | Value | Unit | Role |
|-----------|-------|------|------|
| Win | 50.0 | μm | Input pair width — large for low offset |
| Lin | 1.0 | μm | Input pair length — contributes to W×L area |
| Wlatp | 5.0 | μm | PMOS latch width |
| Llatp | 0.5 | μm | PMOS latch length — longer L eliminates PVT offset |
| Wlatn | 5.0 | μm | NMOS latch width |
| Llatn | 0.5 | μm | NMOS latch length — longer L eliminates PVT offset |
| Wtail | 25.0 | μm | Tail current source width |
| Ltail | 0.5 | μm | Tail current source length |
| Wrst | 3.0 | μm | Reset PMOS width (L=0.15μm fixed) |

---

## Key Design Decisions & Rationale

### 1. Large Input Pair (W×L = 50 μm²)

The input-referred offset is dominated by Vth mismatch: σ_Vth = Avt / √(W×L), where Avt ≈ 5 mV·μm for SKY130 nfet_01v8.

With Win=50μm, Lin=1.0μm: σ_Vth = 5/√50 = 0.707 mV. At 4.5σ, the Monte Carlo offset bound is ~2.3 mV, providing 53% margin on the 5 mV spec.

### 2. Longer Latch Channel Length (L=0.5μm)

**This was the critical design insight.** Initial designs with minimum-length latch devices (L=0.15-0.20μm) showed significant systematic offset at process skew corners (ff, fs), reaching 4.75-5.13 mV at ff/175/1.8V.

Increasing latch L from 0.20μm to 0.50μm completely eliminated this systematic PVT offset (from ~5mV to <0.01mV at all 30 corners). The mechanism: longer channels reduce short-channel effects that create asymmetric behavior across process corners.

**Tradeoff:** Longer latch L slightly increases delay due to larger parasitic capacitance, but delay was never close to the 100ns spec (worst case: 11.83 ns).

### 3. What Was Tried and Rejected

| Configuration | ff/175/1.8 Offset | fs/175/1.8 Offset | Problem |
|---|---|---|---|
| Win=30, Lin=1.0, Llat=0.15 | 4.75 mV | 5.13 mV | fs corner fails |
| Win=50, Lin=1.0, Llat=0.20 | 4.75 mV | 4.55 mV | Both marginal |
| Win=70, Lin=1.0, Llat=0.20 | 6.46 mV | 0.01 mV | ff corner fails |
| Win=50, Lin=1.5, Llat=0.20 | 7.78 mV | 8.48 mV | Both fail worse |
| **Win=50, Lin=1.0, Llat=0.50** | **0.01 mV** | **0.01 mV** | **Both pass** |

The key finding: simply increasing input pair size does NOT fix systematic PVT offset. The latch channel length is the critical knob.

---

## Simulation Results

### Nominal Corner (tt, 24°C, 1.8V)

| Metric | Value |
|--------|-------|
| Offset | < 0.01 mV |
| Rise-time delay | 0.36 ns |
| Power | 9.83 μW |
| Output levels | bufp = 1.800V, bufn = 0.000V |

### Transient Waveforms

**Nominal (tt/24°C/1.8V, 5mV input differential):**

![Nominal Waveforms](plots/waveforms_nominal.png)

Clean StrongARM behavior:
- **Precharge (CLK=0):** d1, d2, outp, outn all precharged to VDD by reset PMOS
- **Evaluation (CLK=1):** Input pair pulls d1 down faster than d2 (since Vinp > Vinm)
- **Regeneration:** Cross-coupled latch amplifies the difference → outp goes to 0, outn stays at VDD
- **Buffer outputs:** bufp = VDD (high), bufn = 0 (low)

**Worst Delay Corner (ss/-40°C/1.2V, 5mV input differential):**

![Worst Delay Waveforms](plots/waveforms_worst_delay.png)

Slower regeneration visible but still resolves cleanly within the 50ns evaluation window.

### Swap Test Verification

| Input | bufp | bufn | Correct? |
|-------|------|------|----------|
| +5mV (Vinp > Vinm) | 1.800V | 0.000V | Yes |
| -5mV (Vinp < Vinm) | 0.000V | 1.800V | Yes |

Outputs correctly swap when inputs are swapped — the circuit is genuinely comparing, not stuck.

---

## PVT Corner Analysis

![PVT Corners](plots/pvt_corners.png)

All 30 PVT corners pass with negligible systematic offset:

| Corner | Temp (°C) | Supply (V) | Offset (mV) | Delay (ns) | Status |
|--------|-----------|------------|-------------|------------|--------|
| tt | -40 | 1.2 | 0.01 | 6.51 | PASS |
| tt | -40 | 1.8 | 0.01 | 0.31 | PASS |
| tt | 24 | 1.2 | 0.01 | 2.67 | PASS |
| tt | 24 | 1.8 | 0.01 | 0.36 | PASS |
| tt | 175 | 1.2 | 0.01 | 1.32 | PASS |
| tt | 175 | 1.8 | 0.01 | 0.46 | PASS |
| ss | -40 | 1.2 | 0.01 | 11.60 | PASS |
| ss | -40 | 1.8 | 0.01 | 0.38 | PASS |
| ss | 24 | 1.2 | 0.01 | 4.18 | PASS |
| ss | 24 | 1.8 | 0.01 | 0.42 | PASS |
| ss | 175 | 1.2 | 0.01 | 1.72 | PASS |
| ss | 175 | 1.8 | 0.01 | 0.51 | PASS |
| ff | -40 | 1.2 | 0.01 | 3.66 | PASS |
| ff | -40 | 1.8 | 0.01 | 0.27 | PASS |
| ff | 24 | 1.2 | 0.01 | 1.70 | PASS |
| ff | 24 | 1.8 | 0.01 | 0.31 | PASS |
| ff | 175 | 1.2 | 0.01 | 1.04 | PASS |
| ff | 175 | 1.8 | 0.01 | 0.42 | PASS |
| sf | -40 | 1.2 | 0.01 | 3.68 | PASS |
| sf | -40 | 1.8 | 0.01 | 0.33 | PASS |
| sf | 24 | 1.2 | 0.01 | 1.87 | PASS |
| sf | 24 | 1.8 | 0.01 | 0.37 | PASS |
| sf | 175 | 1.2 | 0.01 | 1.17 | PASS |
| sf | 175 | 1.8 | 0.01 | 0.46 | PASS |
| fs | -40 | 1.2 | 0.01 | 11.83 | PASS |
| fs | -40 | 1.8 | 0.01 | 0.33 | PASS |
| fs | 24 | 1.2 | 0.01 | 3.99 | PASS |
| fs | 24 | 1.8 | 0.01 | 0.36 | PASS |
| fs | 175 | 1.2 | 0.01 | 1.52 | PASS |
| fs | 175 | 1.8 | 0.01 | 0.48 | PASS |

**Worst-case corner for delay:** ss/-40°C/1.2V and fs/-40°C/1.2V (~11.8 ns)
**Limiting factor for delay:** Low supply voltage + cold temperature + slow process = reduced drive current and higher threshold voltages.

---

## Monte Carlo Analysis

![Monte Carlo](plots/monte_carlo.png)

| Metric | Mean | Std | Mean + 4.5σ | Spec | Status |
|--------|------|-----|-------------|------|--------|
| Offset (mV) | 0.523 | 0.398 | 2.315 | < 5 | **PASS** |
| Delay (ns) | 0.358 | 0.002 | 0.369 | < 100 | **PASS** |

**Mismatch model:** Avt = 5 mV·μm for sky130 nfet_01v8, σ_Vth = Avt / √(W×L) = 0.707 mV

The offset distribution follows a half-normal distribution (absolute value of Gaussian mismatch). With σ_Vth = 0.707 mV, the 4.5σ bound of 2.315 mV provides 53.7% margin on the 5 mV spec.

---

## Design Quality Assessment

### Power Consumption

| Corner | Power (μW) | Notes |
|--------|-----------|-------|
| tt/24°C/1.8V | 9.83 | Nominal |
| ss/-40°C/1.2V | 2.49 | Minimum power (slow, cold, low voltage) |
| ff/175°C/1.8V | 19.03 | Maximum power (fast, hot, high voltage) |

Power is reasonable for a clocked StrongARM comparator in 130nm (zero static power, only dynamic during evaluation).

### Area Estimate

| Component | W×L (μm²) | Count | Total (μm²) |
|-----------|-----------|-------|-------------|
| Input pair | 50.0 | 2 | 100.0 |
| Tail NMOS | 12.5 | 1 | 12.5 |
| Latch PMOS | 2.5 | 2 | 5.0 |
| Latch NMOS | 2.5 | 2 | 5.0 |
| Reset PMOS | 0.45 | 4 | 1.8 |
| Buffers | 0.45 | 4 | 1.8 |
| **Total** | | | **126.1 μm²** |

Total gate area of 126 μm² is reasonable for a comparator in 130nm. The input pair dominates (79% of total area), which is expected since offset is the primary spec driver.

### Design Margin Summary

| Spec | Target | Worst-Case | Margin (%) | Assessment |
|------|--------|-----------|------------|------------|
| Offset | < 5 mV | 2.32 mV | 53.7% | Healthy |
| Delay | < 100 ns | 11.83 ns | 88.2% | Very large |

---

## Robustness & Limitations

### Strengths
- **Negligible systematic PVT offset** — longer latch L eliminates corner-dependent offset
- **Large delay margin** — design could operate at much higher clock frequencies
- **Moderate area** — 126 μm² total gate area
- **Zero static power** — StrongARM only consumes power during clock evaluation

### Limitations & Watch Items
- **Metastability at 0mV input:** At ss/175°C/1.2V with exactly zero differential, the latch may not resolve within the evaluation window. This is inherent to any regenerative comparator and acceptable for normal operation with finite input.
- **Kickback noise:** The large input pair (W=50μm) will inject significant charge onto the input nodes during CLK transitions. If driving from a high-impedance source, a sampling capacitor or input isolation switch is recommended.
- **Layout sensitivity:** The input pair must be laid out with careful common-centroid geometry to preserve the offset advantage. Asymmetric routing parasitics could degrade the offset beyond simulation predictions.
- **Buffer sizing:** The output buffers use fixed minimum-size devices (W=2u/1u, L=0.15u). For driving large loads, additional buffer stages may be needed.

---

## Optimization History

| Step | Method | Topology | Score | Specs Met | Notes |
|------|--------|----------|-------|-----------|-------|
| 1 | Design intuition + parametric sweep | StrongARM | 1.00 | 2/2 | Key insight: Llat=0.5μm eliminates PVT offset |

**Approach:** Rather than blind optimization, used analog design intuition to identify the critical design knobs:
1. Sized input pair (W×L=50μm²) based on analytical offset formula
2. Swept latch and tail parameters to understand sensitivity
3. Discovered that latch channel length is the critical knob for PVT offset
4. Verified with waveforms, swap test, and full validation

---

## How to Reproduce

```bash
# 1. Setup PDK models (run once)
bash setup.sh

# 2. Run validation on existing parameters
python evaluate.py

# 3. Run quick validation (fewer corners)
python evaluate.py --quick

# 4. Run optimization from scratch
python optimize.py
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
├── optimize.py          # Optimization script (DE + multi-corner cost)
├── setup.sh             # PDK setup script
├── best_parameters.csv  # Optimized parameter values
├── measurements.json    # Latest measurement results
├── results.tsv          # Experiment history log
├── README.md            # This file — design summary & results
└── plots/
    ├── pvt_corners.png         # PVT corner sweep results
    ├── monte_carlo.png         # Monte Carlo distributions
    ├── waveforms_nominal.png   # Nominal transient waveforms
    ├── waveforms_worst_delay.png # Worst-case delay waveforms
    └── progress.png            # Optimization progress
```
