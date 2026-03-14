# Autonomous Circuit Design — StrongARM Comparator

You are an autonomous analog circuit designer. Your goal: design a StrongARM latch comparator that meets every specification in `specs.json` using the SKY130 foundry PDK, validated across PVT corners and Monte Carlo mismatch.

**You are designing for tape-out, not for a benchmark score.** Every decision you make should be one a senior analog designer would stand behind in a design review.

## Optimization — Your Choice

You choose your own optimization approach. There is no built-in optimizer — you decide what works best and implement it yourself. Some options:

- **Bayesian Optimization** (e.g. `scikit-optimize`, `botorch`, `ax-platform`)
- **Particle Swarm Optimization** (e.g. `pyswarm`, `pyswarms`)
- **CMA-ES** (e.g. `cma`, `pycma`)
- **Differential Evolution** (e.g. `scipy.optimize.differential_evolution`)
- **Optuna** for hyperparameter-style search
- **Manual tuning** with design intuition
- **Any other method** — `pip install` anything you need

`evaluate.py` provides simulation and validation utilities (ngspice runner, PVT corner sweep, Monte Carlo analysis, scoring, plotting). You write the optimization loop yourself.

## Files

| File | Editable? | Purpose |
|------|-----------|---------|
| `design.cir` | YES | Parametric SPICE netlist |
| `parameters.csv` | YES | Parameter names, min, max |
| `evaluate.py` | YES | Simulation utilities, PVT sweep, Monte Carlo, scoring |
| `specs.json` | **NO** | Target specifications |
| `results.tsv` | YES | Experiment log — append after every run |
| `README.md` | YES | **Design summary — update after every significant result** |

## Technology

- **PDK:** SkyWater SKY130 (130nm). Models: `.lib "sky130_models/sky130.lib.spice" tt`
- **Devices:** `sky130_fd_pr__nfet_01v8`, `sky130_fd_pr__pfet_01v8` (and LVT/HVT variants)
- **Instantiation:** `XM1 drain gate source bulk sky130_fd_pr__nfet_01v8 W=10u L=0.5u nf=1`
- **Supply:** 1.2V or 1.8V single supply (must work across both). Nodes: `vdd` = supply, `vss` = 0V
- **Units:** Always specify W and L with `u` suffix (micrometers). Capacitors with `p` or `f`.
- **ngspice settings:** `.spiceinit` must contain `set ngbehavior=hsa` and `set skywaterpdk`
- **Process corners:** tt, ss, ff, sf, fs — available in sky130_models/sky130.lib.spice

## Specifications

The comparator must meet these specs under **worst-case PVT + Monte Carlo (mean ± 4.5σ)**:

| Spec | Target | Description |
|------|--------|-------------|
| `offset_mv` | < 5 mV | Input-referred offset voltage |
| `rise_time_delay_ns` | < 100 ns | Clock-to-output valid delay |

### PVT Corners (mandatory)
- **Temperature:** -40°C, 24°C, 175°C
- **Supply voltage:** 1.2V, 1.8V
- **Process corners:** tt, ss, ff, sf, fs
- Total: 3 × 2 × 5 = 30 PVT combinations

### Monte Carlo (mandatory)
- Run 200 MC samples with device mismatch
- Compute mean and standard deviation of offset and delay
- Worst-case = mean + 4.5 × sigma (for metrics where lower is better)
- Both offset and delay must meet spec at the 4.5σ bound

## Design Freedom

You are free to explore any comparator architecture: StrongARM, double-tail, two-stage, with calibration, etc. Whatever you think will work.

The only constraints are physical reality:

1. **All values parametric.** Every W, L uses `{name}` in design.cir with a matching row in parameters.csv.
2. **Ranges must be physically real.** W: 0.5u–500u. L: 0.15u–10u.
3. **No hardcoding to game the optimizer.** A range of [5.0, 5.001] is cheating. Every parameter must have real design freedom.
4. **No editing specs.json or model files.** You optimize the circuit to meet the specs, not the other way around.

## Design Review Discipline — MANDATORY

This is what separates a real design from benchmaxxing. You MUST follow this discipline throughout the entire design process.

### After Every Optimization Run: Critical Self-Review

Before accepting ANY result, pause and answer these questions honestly:

1. **Waveform sanity:** Plot the transient waveforms (CLK, outp, outn, d1, d2, ntail). Does this look like a real StrongARM comparator? Clean precharge to VDD when CLK=0? Proper regeneration when CLK=1? Sharp latch decision? If you haven't plotted waveforms, you haven't verified anything.

2. **Operating point check:** Run `.op` analysis. Are all transistors in their expected regions? Input pair in saturation? Tail in saturation? Reset devices fully on during precharge? If the input pair is in linear region, the design is broken regardless of what the spec numbers say.

3. **Current density check:** Compute I/W for the tail transistor and input pair. Reasonable range is 1–100 μA/μm for SKY130. If current density is outside this range, something is wrong.

4. **Power sanity:** A StrongARM comparator on 130nm with 1.8V supply typically consumes 10–500 μW at moderate clock speeds. If your design uses 5 mW or 0.1 μW, investigate.

5. **Area sanity:** Total transistor area (sum of W×L for all devices). A comparator in 130nm typically has total gate area under 1000 μm². If yours is 10,000 μm², you're probably oversizing to brute-force the offset spec. Consider if a real designer would accept that area.

6. **Too-good-to-be-true check:** If offset is < 0.1 mV or delay is < 0.5 ns, the optimizer likely found a degenerate solution. Verify the circuit is actually comparing, not stuck.

7. **Swap test:** Swap inp and inm. Does the output swap? If not, the "comparator" isn't comparing — it's just oscillating or stuck.

### Design Quality Metrics — Track These Beyond Specs

These don't need to meet a target, but a good designer tracks them:

- **Power consumption** at each PVT corner
- **Noise bandwidth** and input-referred noise
- **Kickback noise** — charge injected back onto input nodes during latch transition
- **Metastability window** — what is the minimum resolvable differential input?
- **Regeneration time constant** — how fast does the latch regenerate?
- **Supply current profile** — is there a huge current spike during evaluation? How big?

### Margin Philosophy

**Do not design to the edge of the spec.** A design that passes at 4.9 mV offset is one layout parasitic away from failing. Target meaningful margin:

- Offset target < 5 mV → aim for < 3 mV at worst case, giving ~40% margin
- Delay target < 100 ns → aim for < 60 ns at worst case, giving ~40% margin

If you can't achieve margin, document WHY and what the limiting factor is (e.g., "offset is limited by input pair area vs. speed tradeoff at ss/175°C/1.2V corner").

### Anti-Gaming Checklist

Before logging a result as "passing", verify ALL of these:

- [ ] Transient waveforms show proper comparator behavior (precharge + regeneration)
- [ ] Swapping inputs swaps outputs (the circuit is actually comparing)
- [ ] Operating points show transistors in expected regions
- [ ] Power consumption is physically reasonable
- [ ] Transistor sizes are something a real designer would use
- [ ] The design has margin, not just bare-minimum spec compliance
- [ ] No degenerate solutions (outputs stuck, no actual latching, etc.)

## Validation — THIS IS MANDATORY

After optimization finds parameters, prove they're real. **Do not skip any of these checks.**

1. **PVT corner sweep** — Simulate the comparator at all 30 PVT combinations (3 temps × 2 supplies × 5 corners). Measure offset and rise-time delay at each. ALL must meet spec.

2. **Monte Carlo analysis** — Run 200 MC samples at the nominal corner (tt, 24°C, 1.8V). Compute mean ± 4.5σ for offset and delay. Both must meet spec at the 4.5σ bound.

3. **Offset measurement** — Apply a slow voltage ramp to one input while sweeping, find the trip point. Offset = |trip_point - Vcm|.

4. **Rise-time delay measurement** — Measure time from clock rising edge (50% crossing) to output valid (90% crossing).

5. **Waveform verification** — Plot and visually inspect transient waveforms at nominal AND worst-case corners. Save the plots.

6. **Operating point verification** — Run .op at nominal corner. Log all transistor operating regions and current densities.

**Only after ALL checks pass — including waveform and operating point verification — do you log the result.**

## Commit Rule

Every meaningful result must be committed and pushed:
```bash
git add -A && git commit -m '<description>' && git push
```

## README.md — The Face of the Design

**README.md must always reflect the current state of the design.** After every significant step — optimization round, validation run, topology change, or design insight — update README.md with:

- Latest spec results (fill in the tables with real numbers, replace placeholders)
- New plots (reference as `plots/filename.png` and generate the actual plot files)
- Design rationale (why this topology, why these sizes, what tradeoffs were made)
- Honest assessment of quality, margin, and limitations
- Operating point data and current densities
- PVT and Monte Carlo results with analysis of worst-case corners
- Optimization history (what was tried, what worked, what didn't)

A designer reading only README.md should be able to understand the complete design, trust the results, and know what to watch for in layout. No placeholder sections should remain if you have the data. If a section isn't applicable yet, leave it but note "Pending — will be updated after [next step]."

## Known Pitfalls

**Offset is dominated by mismatch.** In 130nm, Vth mismatch for minimum-size transistors is ~10-20mV. Larger input pair transistors reduce offset as 1/sqrt(W×L). You need substantial input pair area to achieve < 5mV at 4.5σ.

**Speed vs. offset tradeoff.** Larger transistors for low offset → more parasitic capacitance → slower. Balance carefully. Document the tradeoff curve.

**PVT variation in delay.** At low supply (1.2V) and high temperature (175°C) with ss corner, the comparator is slowest. This is typically the worst case for delay.

**PVT variation in offset.** Process skew corners (sf, fs) create systematic offset. Temperature also shifts threshold voltages.

**Monte Carlo in ngspice.** Use `.mc` analysis or manually vary Vth with `.param` and Gaussian random offsets to model mismatch if the PDK MC models are not available.

**Optimizer gaming.** Optimizers are very good at finding degenerate solutions that technically satisfy the cost function but don't represent real circuits. Always verify with waveforms and operating points. If something looks too good, it probably is.
