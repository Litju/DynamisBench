/**
 * Prototype numerical recomputation (tag RECOMPUTED).
 *
 * Re-solves the planar pendulum equation I·θ'' + m·g·L·sin θ = 0 from the reviewed RES-550
 * constants, mirroring the structure of python/tools/mujoco_qualification_receipt.py. This is
 * not MuJoCo output, not a receipt and not evidence: it exists so the workbench can show real
 * numbers with honest provenance instead of decorative curves.
 */
import { REF } from './authority';

export type Series = {
  id: string;
  label: string;
  method: string;
  dt: number;
  t: Float64Array;
  theta: Float64Array;
  omega: Float64Array;
  energy: Float64Array;
};

const K = (REF.massKg * REF.gravity * REF.comDistanceM) / REF.hingeInertiaKgM2;

export function energyOf(theta: number, omega: number) {
  return 0.5 * REF.hingeInertiaKgM2 * omega * omega + REF.massKg * REF.gravity * REF.comDistanceM * (1 - Math.cos(theta));
}

type Stepper = (th: number, om: number, h: number) => [number, number];

const rk4: Stepper = (th, om, h) => {
  const k1t = om, k1o = -K * Math.sin(th);
  const k2t = om + 0.5 * h * k1o, k2o = -K * Math.sin(th + 0.5 * h * k1t);
  const k3t = om + 0.5 * h * k2o, k3o = -K * Math.sin(th + 0.5 * h * k2t);
  const k4t = om + h * k3o, k4o = -K * Math.sin(th + h * k3t);
  return [th + (h / 6) * (k1t + 2 * k2t + 2 * k3t + k4t), om + (h / 6) * (k1o + 2 * k2o + 2 * k3o + k4o)];
};

const semiImplicitEuler: Stepper = (th, om, h) => {
  const o = om - h * K * Math.sin(th);
  return [th + h * o, o];
};

/** Integrate with `dt`, recording on a fixed 1 ms output grid (exact multiples). */
function integrate(id: string, label: string, method: string, step: Stepper, dt: number, theta0 = REF.theta0, duration = REF.duration): Series {
  const out = Math.round(duration / 0.001) + 1;
  const t = new Float64Array(out), theta = new Float64Array(out), omega = new Float64Array(out), energy = new Float64Array(out);
  let th = theta0, om = REF.omega0;
  const sub = Math.max(1, Math.round(0.001 / dt));
  const stride = Math.max(1, Math.round(dt / 0.001));
  const h = dt;
  let k = 0;
  const record = (i: number) => {
    t[i] = i * 0.001; theta[i] = th; omega[i] = om; energy[i] = energyOf(th, om);
  };
  record(0);
  const total = Math.round(duration / dt);
  for (let n = 1; n <= total; n++) {
    [th, om] = step(th, om, h);
    if (dt < 0.001) {
      if (n % sub === 0) record(++k);
    } else {
      // coarse step: hold-free linear fill of the output grid between steps
      const i1 = n * stride, i0 = i1 - stride;
      const th0 = theta[i0], om0 = omega[i0];
      for (let j = 1; j <= stride && i0 + j < out; j++) {
        const a = j / stride;
        const thj = th0 + a * (th - th0), omj = om0 + a * (om - om0);
        t[i0 + j] = (i0 + j) * 0.001; theta[i0 + j] = thj; omega[i0 + j] = omj; energy[i0 + j] = energyOf(thj, omj);
      }
      k = i1;
    }
  }
  return { id, label, method, dt, t, theta, omega, energy };
}

/** Complete elliptic integral of the first kind K(m), m = k², by the AGM. */
export function ellipK(m: number) {
  let a = 1, b = Math.sqrt(1 - m);
  for (let i = 0; i < 30; i++) { const an = (a + b) / 2; b = Math.sqrt(a * b); a = an; }
  return Math.PI / (2 * a);
}

export const analyticalPeriod = () => 4 * Math.sqrt(1 / K) * ellipK(Math.sin(REF.theta0 / 2) ** 2);

/** First downward zero crossing of θ, linearly interpolated (receipt uses first_zero_crossing_s × 4). */
export function firstZeroCrossing(s: Series) {
  for (let i = 1; i < s.t.length; i++) {
    if (s.theta[i - 1] > 0 && s.theta[i] <= 0) {
      const a = s.theta[i - 1] / (s.theta[i - 1] - s.theta[i]);
      return s.t[i - 1] + a * (s.t[i] - s.t[i - 1]);
    }
  }
  return null;
}

let cache: ReturnType<typeof build> | null = null;
function build() {
  const reference = integrate('ref.independent', 'Independent reference solve', 'RK4, Δt = 10 µs (stands in for DOP853 rtol 1e-12)', rk4, 1e-5);
  const nominal = integrate('series.rk4-1ms', 'Nominal RK4, Δt = 1 ms', 'RK4, Δt = 1 ms (reviewed integrator & step)', rk4, 0.001);
  const coarse = integrate('series.rk4-10ms', 'RK4, Δt = 10 ms', 'RK4, Δt = 10 ms (linear fill to 1 ms grid)', rk4, 0.01);
  const symplectic = integrate('series.sie-1ms', 'Semi-implicit Euler, Δt = 1 ms', 'Semi-implicit (symplectic) Euler, Δt = 1 ms', semiImplicitEuler, 0.001);
  const n = nominal.t.length;
  const w = Math.sqrt(K);
  const lt = new Float64Array(n), lth = new Float64Array(n), lom = new Float64Array(n), le = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    lt[i] = i * 0.001; lth[i] = REF.theta0 * Math.cos(w * lt[i]); lom[i] = -REF.theta0 * w * Math.sin(w * lt[i]); le[i] = energyOf(lth[i], lom[i]);
  }
  const linear: Series = { id: 'series.small-angle', label: 'Small-angle linear model', method: 'Analytical θ₀·cos(√(mgL/I)·t) — different model, not a discretisation', dt: 0.001, t: lt, theta: lth, omega: lom, energy: le };
  const thetaEnd = reference.theta[reference.theta.length - 1];
  const refinement = CRIT_STEPS.map((dt) => {
    const steps = Math.round(REF.duration / dt);
    let th = REF.theta0, om = REF.omega0, maxDrift = 0;
    const e0 = energyOf(th, om);
    for (let n = 0; n < steps; n++) {
      [th, om] = rk4(th, om, dt);
      maxDrift = Math.max(maxDrift, Math.abs(energyOf(th, om) - e0) / e0);
    }
    return { dt, steps, finalTheta: th, error: Math.abs(th - thetaEnd), maxDrift };
  });
  return { reference, nominal, coarse, symplectic, linear, refinement };
}
const CRIT_STEPS = [0.01, 0.005, 0.0025, 0.00125];

export function computed() {
  if (!cache) cache = build();
  return cache;
}

export function seriesById(id: string): Series {
  const c = computed();
  return ([c.reference, c.nominal, c.coarse, c.symplectic, c.linear].find((s) => s.id === id) ?? c.nominal);
}

export const SERIES_IDS = ['series.rk4-1ms', 'series.rk4-10ms', 'series.sie-1ms', 'series.small-angle'];

/** Sample index on the shared 1 ms grid for time t. */
export const idx = (t: number) => Math.max(0, Math.min(2000, Math.round(t / 0.001)));

export function verificationSummary() {
  const c = computed();
  const ref = c.reference, nom = c.nominal;
  let maxA = 0, maxW = 0, maxDrift = 0, maxVC = 0;
  const e0 = nom.energy[0];
  for (let i = 0; i < nom.t.length; i++) {
    maxA = Math.max(maxA, Math.abs(nom.theta[i] - ref.theta[i]));
    maxW = Math.max(maxW, Math.abs(nom.omega[i] - ref.omega[i]));
    maxDrift = Math.max(maxDrift, Math.abs(nom.energy[i] - e0) / e0);
  }
  for (let i = 3; i < nom.t.length - 3; i++) {
    const g = (nom.theta[i + 1] - nom.theta[i - 1]) / 0.002;
    maxVC = Math.max(maxVC, Math.abs(g - nom.omega[i]));
  }
  const crossing = firstZeroCrossing(nom);
  const observedPeriod = crossing === null ? null : 4 * crossing;
  const analytic = analyticalPeriod();
  const ratios = c.refinement.slice(0, -1).map((r, i) => r.error / c.refinement[i + 1].error);
  return { maxA, maxW, maxDrift, maxVC, observedPeriod, analytic, periodError: observedPeriod === null ? null : Math.abs(observedPeriod - analytic), refinement: c.refinement, ratios, finalTime: nom.t[nom.t.length - 1] };
}
