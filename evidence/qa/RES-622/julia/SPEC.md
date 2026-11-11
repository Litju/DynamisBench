# RES-622 Gate B — Oracle specification (frozen before any real-data residual was computed)

Status: experimental, nonblocking research/QA tool. Not scientific authority, not a required
CI gate, not part of the application, installer or MuJoCo worker. Julia is a test-only tool.

## 1. Invariant

Vertical impulse–momentum of the athlete + barbell system (Newton's second law integrated
over a time window). For a window `[ta, tb]` of the recorded repetition:

    M · ( v(tb) − v(ta) )  =  ∫ta..tb ( Fz(t) − M·g ) dt                       (1)

Residual:  `R = M·(v(tb) − v(ta)) − ∫ ( Fz − M g ) dt`  [N·s].

## 2. Assumptions (all stated, none inferred from the code under test)

* The only external vertical forces on the system are gravity and the ground reaction on the
  feet (no other body contacts the floor; no air drag; no external pushes in the repetition).
* The system is the 75 kg athlete plus the 20 kg barbell: `M = 95.000 kg`
  (declared masses of the task statement; not read from the model).
* Standard gravity `g = 9.80665 m/s²` (ISO 80000-3), acting along −z.
* World frame, z up. Ground reaction positive upward (a force exerted by the ground on the
  athlete). `v` is the vertical velocity of the system centre of mass.
* The recorded series are instantaneous values at the sample instants (not interval means).
* Time grid is uniform with step `h` (recorded: 0.01 s).

## 3. Observable quantities, units, frame, sign

| CSV column (`repetition_timeseries.csv`) | Symbol | Unit | Meaning |
| --- | --- | --- | --- |
| `t_s` | t | s | sample time |
| `grf_left_z_n`, `grf_right_z_n` | Fz = left + right | N | vertical ground reaction, up positive |
| `com_vz_m_s` | v | m/s | vertical velocity of the system CoM, up positive |
| `phase` | — | label | movement phase (used only to define sub-windows) |

## 4. Numerical method

* Integral: composite trapezoid rule on the recorded grid, compensated (Neumaier) summation.
* Quadrature uncertainty: Richardson-style two-grid estimate
  `u_q = | I_h − I_2h |` where `I_2h` is the trapezoid rule on every second sample. If the
  window has an odd number of intervals, `I_2h` is computed on the largest even prefix and
  `u_q` is scaled by `n / n_even`. (For a trapezoid error ∝ h² the true error of `I_h` is
  ≈ `u_q / 3`; using `u_q` itself is a 3× safety factor.)
* Windows: (W0) the whole record; (Wk) each maximal run of consecutive identical `phase`
  labels, end points inclusive.

## 5. Tolerance (independent of any candidate discrepancy)

    τ = min(u_q, ε_q · M · g · (tb − ta))  +  ε_rel · M · g · (tb − ta)  +  ε_abs
    ε_rel = 1.0e-3   (0.1 % of the window's weight impulse)
    ε_q   = 5.0e-3   (cap on the quadrature allowance, erratum 2)
    ε_abs = 1.0e-9 N·s

* `u_q` is the numerical-method budget (data-derived but blind to the model).
* `ε_rel` is an engineering acceptance level: 0.1 % of body-plus-bar weight, the order of a
  laboratory force platform's typical amplitude accuracy. It is a convention, not an empirical
  validation. Reports include `|R|/τ`, so sensitivity to this choice is visible.
* `ε_abs` absorbs double-precision/CSV round-off only.
* PASS iff `|R| ≤ τ` for the window. Process exit code 0 iff every window passes.

## 6. Independent reference values (used to qualify the oracle itself, not the model)

Closed-form signals with exact antiderivatives, evaluated at sample times:

| Case | Fz(t) | v(t) | Expected R |
| --- | --- | --- | --- |
| rest | M g | 0 | 0 (≤ 1e-9) |
| constant push | M g + F0 | F0 t / M | 0 (trapezoid exact) |
| free flight | 0 | −g t | 0 |
| sinusoid | M g + A sin(ωt) | (A/(Mω))(1 − cos ωt) | Euler–Maclaurin: `R = −(h²/12)(F'(tb) − F'(ta))` = `−(h²/12) A ω (cos ωtb − cos ωta)`, |ΔR| ≤ 5 % of that + 1e-9 |

Adversarial / perturbed cases (must be flagged, expected verdict in brackets): mass error
+1 % [FAIL], gravity 9.9 [FAIL], gravity 9.81 (+0.0034 %) [PASS — below the detection floor,
documented], GRF sign inversion [FAIL], one-sample velocity time shift on a moving window
[FAIL], single-sample GRF spike worth > τ [FAIL], slow velocity drift [FAIL], non-finite
value / non-monotone or non-uniform time / missing column / fewer than 3 samples [exit 2,
input rejected], oversized input [exit 2].

## 7. Input/output contract

* Command: `julia --project=<this dir> src/impulse_oracle.jl --input <csv> [--output <json>]`
  (`--mass-kg`, `--gravity` optional overrides exist only to run the adversarial cases;
  defaults are the frozen constants above).
* Input: one UTF-8 CSV with a header row, ≤ 1 000 000 data rows and ≤ 256 MiB, read-only.
  No network, no environment dependence, no files written except the optional `--output`.
* Output: one JSON object (schema `dynamisbench.qa.impulse-oracle/1`) with the constants, the
  window results (`R`, `u_q`, `τ`, `|R|/τ`, pass), the input SHA-256, Julia and tool versions.
* Exit codes: 0 all windows pass, 1 at least one window fails, 2 input rejected.

## 8. Independence statement

Shared with the code under test: the physical constants (declared in the task, restated here),
the engine that produced both series (so the oracle checks the *internal consistency of two
engine outputs against Newton's law*, not the engine's truth), and the CSV exporter. Not
shared: the Python verification code and tests (`max_momentum_residual_n_s`), any Python
numerics, any MuJoCo binding. An independent numerical method does not prove empirical
biomechanical validity.

## Erratum (recorded before any real-data residual was computed)

The first draft of the sinusoid row gave the Euler–Maclaurin term with the wrong sign. `R` is defined as exact
minus trapezoid, so it is the *negative* of the trapezoid's truncation error `+(h²/12)(F'(tb)−F'(ta))`. The oracle
was right and the draft reference was wrong; the table above is the corrected one. Found by running the oracle's
own closed-form tests, not by looking at squat data.

### Erratum 2 (also recorded before any real-data residual was computed)

The closed-form adversarial tests showed the Richardson allowance masks its own cause: a single large GRF spike
enlarges `u_q` by about the spike's impulse, so `τ` grew with the anomaly and the spike passed. `u_q` is therefore
capped at `ε_q = 0.5 %` of the window's weight impulse; a window whose `u_q` exceeds the cap is reported with
`quadrature_limited = true` (the grid cannot resolve the signal) and is judged against the capped `τ`. The same
tests showed that a slow velocity drift of 0.008 m/s over 4 s is below the 0.1 % detection floor by design, so the
test drift was enlarged rather than the floor changed.
