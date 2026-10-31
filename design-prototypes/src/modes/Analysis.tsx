import { useMemo, type ReactNode } from 'react';
import { CRITERIA, LCMJ20, PENDULUM_RELEASE } from '../data/authority';
import { computed, SERIES_IDS, seriesById, verificationSummary } from '../data/numerics';
import { useWB, type AnalysisTab } from '../state';
import { Empty, Tag } from '../ui/kit';
import { Plot } from '../ui/Plot';

function Box({ title, children, right, className = '' }: { title: string; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-md border border-line bg-panel ${className}`} aria-label={title}>
      <header className="flex items-center gap-2 border-b border-line px-3 py-1.5"><h3 className="sec-h m-0">{title}</h3><span className="ml-auto flex items-center gap-1.5">{right}</span></header>
      <div className="p-2.5">{children}</div>
    </section>
  );
}

function ClaimLimit({ text }: { text: string }) {
  return (
    <div className="rounded border border-design-line bg-design-soft px-3 py-2 text-[12px] text-ink-2" role="note">
      <b className="text-design">Claim limit · </b>{text}
    </div>
  );
}

/* ---------------- solution verification ---------------- */

function RefinementChart({ rows, ratios }: { rows: { dt: number; error: number }[]; ratios: number[] }) {
  const W = 360, H = 200, P = { l: 52, r: 14, t: 10, b: 30 };
  const xs = rows.map((r) => Math.log10(r.dt)), ys = rows.map((r) => Math.log10(Math.max(r.error, 1e-18)));
  const x0 = Math.min(...xs) - 0.15, x1 = Math.max(...xs) + 0.15, y0 = Math.min(...ys) - 0.5, y1 = Math.max(...ys) + 0.5;
  const sx = (v: number) => P.l + ((v - x0) / (x1 - x0)) * (W - P.l - P.r);
  const sy = (v: number) => P.t + (1 - (v - y0) / (y1 - y0)) * (H - P.t - P.b);
  const guide = [xs[0], xs[xs.length - 1]].map((x) => [sx(x), sy(ys[0] + 4 * (x - xs[0]))]);
  const yt: number[] = []; for (let v = Math.ceil(y0); v <= y1; v++) yt.push(v);
  return (
    <figure className="m-0">
      <svg width={W} height={H} role="img" aria-label={`Refinement study: final-angle error versus timestep on log axes. Observed ratios ${ratios.map((r) => r.toFixed(1)).join(', ')}`}>
        {yt.map((v) => <g key={v}><line x1={P.l} x2={W - P.r} y1={sy(v)} y2={sy(v)} style={{ stroke: 'var(--color-grid)' }} /><text x={P.l - 6} y={sy(v) + 3.5} fontSize="10.5" textAnchor="end" style={{ fill: 'var(--color-ink-3)' }}>1e{v}</text></g>)}
        {rows.map((r) => <text key={r.dt} x={sx(Math.log10(r.dt))} y={H - 12} fontSize="10.5" textAnchor="middle" style={{ fill: 'var(--color-ink-3)' }}>{r.dt}</text>)}
        <text x={(W + P.l) / 2} y={H - 1} fontSize="10.5" textAnchor="middle" style={{ fill: 'var(--color-ink-3)' }}>timestep Δt [s] (log)</text>
        <line x1={guide[0][0]} y1={guide[0][1]} x2={guide[1][0]} y2={guide[1][1]} style={{ stroke: 'var(--color-ink-4)' }} strokeDasharray="4 3" />
        <text x={guide[1][0] + 4} y={guide[1][1] + 12} fontSize="10" style={{ fill: 'var(--color-ink-3)' }}>slope 4</text>
        <polyline points={rows.map((r, i) => `${sx(xs[i])},${sy(ys[i])}`).join(' ')} fill="none" style={{ stroke: 'var(--color-s1)' }} strokeWidth="1.5" />
        {rows.map((r, i) => <circle key={r.dt} cx={sx(xs[i])} cy={sy(ys[i])} r={3.5} style={{ fill: 'var(--color-panel)', stroke: 'var(--color-s1)' }} strokeWidth="1.5" />)}
        <rect x={P.l} y={P.t} width={W - P.l - P.r} height={H - P.t - P.b} fill="none" style={{ stroke: 'var(--color-line-2)' }} />
      </svg>
      <figcaption className="text-[11px] text-ink-3">|θ(2 s) − θ_ref(2 s)| for RK4 at the four qualification timesteps (prototype recomputation).</figcaption>
    </figure>
  );
}

function Verification() {
  const { s, d } = useWB();
  const v = useMemo(() => verificationSummary(), []);
  const c = computed();
  const errT = useMemo(() => c.nominal.theta.map((x, i) => x - c.reference.theta[i]), [c]);
  const rows: { name: string; crit: string; obs: number | null; ok: boolean | null; unit: string }[] = [
    { name: 'Max |θ − θ_ref| over trajectory', crit: `≤ ${CRITERIA.angle_rad}`, obs: v.maxA, ok: v.maxA <= CRITERIA.angle_rad, unit: 'rad' },
    { name: 'Max |ω − ω_ref| over trajectory', crit: `≤ ${CRITERIA.angular_velocity_rad_s}`, obs: v.maxW, ok: v.maxW <= CRITERIA.angular_velocity_rad_s, unit: 'rad·s⁻¹' },
    { name: 'Max relative energy drift', crit: `≤ ${CRITERIA.energy_relative}`, obs: v.maxDrift, ok: v.maxDrift <= CRITERIA.energy_relative, unit: '1' },
    { name: 'Velocity consistency |dθ/dt − ω|', crit: `≤ ${CRITERIA.velocity_consistency_rad_s}`, obs: v.maxVC, ok: v.maxVC <= CRITERIA.velocity_consistency_rad_s, unit: 'rad·s⁻¹' },
    { name: 'Finite-amplitude period |T_obs − T_K|', crit: `≤ ${CRITERIA.period_s}`, obs: v.periodError, ok: v.periodError !== null && v.periodError <= CRITERIA.period_s, unit: 's' },
    { name: 'Final time |t_end − 2 s|', crit: `≤ ${CRITERIA.final_time_s}`, obs: Math.abs(v.finalTime - 2), ok: Math.abs(v.finalTime - 2) <= CRITERIA.final_time_s, unit: 's' },
    { name: 'Refinement ratio (min of successive)', crit: `≥ ${CRITERIA.refinement_min_ratio}`, obs: Math.min(...v.ratios), ok: Math.min(...v.ratios) >= CRITERIA.refinement_min_ratio, unit: '1' },
    { name: 'Refinement final-angle error (finest)', crit: `≤ ${CRITERIA.refinement_final_angle_rad}`, obs: v.refinement[v.refinement.length - 1].error, ok: v.refinement[v.refinement.length - 1].error <= CRITERIA.refinement_final_angle_rad, unit: 'rad' },
    { name: 'Energy reconstruction vs diagnostic', crit: `≤ ${CRITERIA.energy_reconstruction_j}`, obs: null, ok: null, unit: 'J' },
  ];
  return (
    <div className="grid gap-3" data-testid="verification">
      <ClaimLimit text={CRITERIA.claimLimit} />
        <Box title="Predeclared criteria vs observation" right={<Tag tag="AUTHORITY">criteria</Tag>}>
          <table className="data">
            <thead><tr><th>Check</th><th>Criterion</th><th>Prototype recomputation</th><th>Unit</th><th style={{ textAlign: 'left' }}>Within?</th><th style={{ textAlign: 'left' }}>Qualified receipt</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name}>
                  <td style={{ whiteSpace: 'normal', minWidth: 230 }}>{r.name}</td>
                  <td className="mono">{r.crit}</td>
                  <td className="mono">{r.obs === null ? '—' : r.obs.toExponential(3)}</td>
                  <td className="text-ink-3">{r.unit}</td>
                  <td style={{ textAlign: 'left' }} className={r.ok === null ? 'text-ink-3' : r.ok ? 'text-ok' : 'text-err'}>{r.ok === null ? 'not computable here' : r.ok ? 'within criterion' : 'outside criterion'}</td>
                  <td style={{ textAlign: 'left' }} className="text-ink-3">CI artifact</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 grid gap-1 text-[11.5px] text-ink-3">
            <div><Tag tag="RECOMPUTED" /> Observed column: browser RK4 at Δt = 1 ms against a browser RK4 at Δt = 10 µs, standing in for MuJoCo and for the receipt's DOP853 (rtol 1e-12) solve. It demonstrates the procedure; it is not the qualified observation.</div>
            <div><Tag tag="QUALIFIED" /> RES-550 receipts for windows-x86-64 and linux-x86-64 hold the real observed values; they are CI artifacts and are not present in this repository, so no receipt number is shown.</div>
            <div>T_K = 4·√(I/(m·g·L))·K(sin²(θ₀/2)) = <span className="mono">{v.analytic.toFixed(9)} s</span>; T_obs = 4 × first zero crossing = <span className="mono">{v.observedPeriod?.toFixed(9)} s</span>.</div>
          </div>
        </Box>
      <div className="grid gap-3 lg:grid-cols-[400px_minmax(0,1fr)]">
        <Box title="Timestep refinement" right={<Tag tag="RECOMPUTED" />} className="min-w-0">
          <RefinementChart rows={v.refinement} ratios={v.ratios} />
          <table className="data mt-2">
            <thead><tr><th>Δt [s]</th><th>steps</th><th>|e(2 s)| [rad]</th><th>ratio</th><th>max rel. ΔE</th></tr></thead>
            <tbody>
              {v.refinement.map((r, i) => (
                <tr key={r.dt}><td className="mono">{r.dt}</td><td className="mono">{r.steps}</td><td className="mono">{r.error.toExponential(3)}</td><td className="mono">{i < v.ratios.length ? v.ratios[i].toFixed(2) : '—'}</td><td className="mono">{r.maxDrift.toExponential(2)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="mb-0 mt-1.5 text-[11px] text-ink-3">Timesteps from qualification.py; RK4 theory predicts ratio ≈ 16 per halving.</p>
        </Box>
        <Box title="Solution error over time (linked to the shared time cursor)" right={<Tag tag="RECOMPUTED" />}>
        <Plot title="θ − θ_ref" unit="rad" traces={[{ id: 'e', label: 'error', color: 'var(--color-s1)', t: c.nominal.t, v: errT }]} t={s.t} onTime={(t) => d({ type: 'time', t })} height={260} symmetric footer="Nominal RK4 Δt 1 ms minus independent reference · same 1 ms relative_to_start grid · no interpolation" />
        </Box>
      </div>
    </div>
  );
}

/* ---------------- run / signal comparison (SDI-style) ---------------- */

const SIG = {
  theta: { label: 'Hinge angle θ', unit: 'rad', q: 'q.pendulum.hinge-angle', crit: CRITERIA.angle_rad },
  omega: { label: 'Hinge angular velocity ω', unit: 'rad·s⁻¹', q: 'q.pendulum.hinge-angular-velocity', crit: CRITERIA.angular_velocity_rad_s },
  energy: { label: 'Mechanical energy E', unit: 'J', q: 'derived (prototype)', crit: 1e-8 },
} as const;

function Compare() {
  const { s, d } = useWB();
  const cmp = s.compare;
  const base = seriesById(cmp.baseline), cand = seriesById(cmp.candidate);
  const key = cmp.signal;
  const bv = base[key], cv = cand[key];
  const { diff, lo, hi, stats } = useMemo(() => {
    const n = bv.length;
    const diff = new Float64Array(n), lo = new Float64Array(n), hi = new Float64Array(n);
    let maxAbs = 0, tMax = 0, ss = 0, within = 0, firstOut: number | null = null;
    for (let i = 0; i < n; i++) {
      const tol = Math.max(cmp.absTol, cmp.relTol * Math.abs(bv[i]));
      diff[i] = cv[i] - bv[i]; lo[i] = -tol; hi[i] = tol;
      const a = Math.abs(diff[i]);
      if (a > maxAbs) { maxAbs = a; tMax = base.t[i]; }
      ss += a * a;
      if (a <= tol) within++; else if (firstOut === null) firstOut = base.t[i];
    }
    return { diff, lo, hi, stats: { maxAbs, tMax, rms: Math.sqrt(ss / n), within: within / n, firstOut } };
  }, [bv, cv, cmp.absTol, cmp.relTol, base.t]);
  const band = useMemo(() => {
    const l = new Float64Array(bv.length), h = new Float64Array(bv.length);
    for (let i = 0; i < bv.length; i++) { const tol = Math.max(cmp.absTol, cmp.relTol * Math.abs(bv[i])); l[i] = bv[i] - tol; h[i] = bv[i] + tol; }
    return { lo: l, hi: h, t: base.t, label: 'tolerance' };
  }, [bv, cmp.absTol, cmp.relTol, base.t]);
  const same = cmp.baseline === cmp.candidate;
  const series = [...SERIES_IDS.map((id) => seriesById(id)), computed().reference];
  return (
    <div className="grid gap-3 lg:grid-cols-[290px_minmax(0,1fr)]" data-testid="compare">
      <div className="grid content-start gap-3">
        <Box title="Signal catalog" right={<Tag tag="RECOMPUTED" />}>
          <table className="data">
            <thead><tr><th>Series</th><th>Base</th><th>Cand.</th></tr></thead>
            <tbody>
              {series.map((x) => (
                <tr key={x.id}>
                  <td style={{ whiteSpace: 'normal', textAlign: 'left' }}><div className="text-[12px]">{x.label}</div><div className="text-[10.5px] text-ink-3">{x.method}</div></td>
                  <td><input type="radio" name="baseline" checked={cmp.baseline === x.id} onChange={() => d({ type: 'compare', patch: { baseline: x.id } })} aria-label={`Baseline ${x.label}`} /></td>
                  <td><input type="radio" name="candidate" checked={cmp.candidate === x.id} onChange={() => d({ type: 'compare', patch: { candidate: x.id } })} aria-label={`Candidate ${x.label}`} data-testid={`cand-${x.id}`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mb-0 mt-1.5 text-[11px] text-ink-3">Synthetic numerical series, not runs. Real cross-run queries need canonical quantities (M4, RES-569).</p>
        </Box>
        <Box title="Alignment and tolerance">
          <label className="mb-1.5 grid grid-cols-[90px_1fr] items-center gap-2 text-[12px]">Signal
            <select className="field" value={key} onChange={(e) => { const k = e.target.value as keyof typeof SIG; d({ type: 'compare', patch: { signal: k, absTol: SIG[k].crit } }); }} data-testid="cmp-signal">
              {Object.entries(SIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
          <label className="mb-1.5 grid grid-cols-[90px_1fr_44px] items-center gap-2 text-[12px]">Abs. tol.
            <input className="field num text-right" type="number" step="any" value={cmp.absTol} onChange={(e) => d({ type: 'compare', patch: { absTol: Math.max(0, Number(e.target.value)) } })} data-testid="cmp-abstol" />
            <span className="text-[11px] text-ink-3">{SIG[key].unit}</span>
          </label>
          <label className="mb-1.5 grid grid-cols-[90px_1fr_44px] items-center gap-2 text-[12px]">Rel. tol.
            <input className="field num text-right" type="number" step="any" value={cmp.relTol} onChange={(e) => d({ type: 'compare', patch: { relTol: Math.max(0, Number(e.target.value)) } })} />
            <span className="text-[11px] text-ink-3">1</span>
          </label>
          <dl className="kv mt-2 text-[12px]">
            <dt>Quantity</dt><dd className="mono">{SIG[key].q}</dd>
            <dt>Units</dt><dd>{SIG[key].unit} (both)</dd>
            <dt>Frame</dt><dd>hinge (both)</dd>
            <dt>Time basis</dt><dd>relative_to_start, 1 ms grid</dd>
            <dt>Resampling</dt><dd>{cand.dt > 0.001 ? `candidate Δt ${cand.dt} s linearly interpolated to 1 ms` : 'none (native 1 ms samples)'}</dd>
            <dt>Tolerance rule</dt><dd>max(abs, rel·|baseline|)</dd>
          </dl>
          <p className="mb-0 mt-2 text-[11px] text-ink-3">Default absolute tolerance is the predeclared {key === 'energy' ? 'display value (no energy-trace criterion exists)' : 'qualification criterion for this quantity'}.</p>
        </Box>
      </div>
      <div className="grid content-start gap-3">
        {same ? <Empty title="Baseline and candidate are the same series" tag="NOT_ASSESSED">Choose a different candidate to compare.</Empty> : (
          <>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5" data-testid="cmp-stats">
              {[
                ['Max |Δ|', `${stats.maxAbs.toExponential(3)} ${SIG[key].unit}`],
                ['at t', `${stats.tMax.toFixed(3)} s`],
                ['RMS Δ', `${stats.rms.toExponential(3)}`],
                ['Samples within tol.', `${(stats.within * 100).toFixed(1)} %`],
                ['First exceedance', stats.firstOut === null ? 'none' : `${stats.firstOut.toFixed(3)} s`],
              ].map(([k, v]) => (
                <div key={k} className="rounded border border-line bg-panel px-2.5 py-1.5"><div className="text-[11px] text-ink-3">{k}</div><div className="mono text-[13px] text-ink">{v}</div></div>
              ))}
            </div>
            <div className={`rounded border px-3 py-1.5 text-[12.5px] ${stats.firstOut === null ? 'border-ok-line bg-ok-soft text-ok' : 'border-err-line bg-err-soft text-err'}`} role="status" data-testid="cmp-verdict">
              {stats.firstOut === null ? 'All aligned samples are within the stated tolerance.' : `Difference exceeds the stated tolerance from t = ${stats.firstOut.toFixed(3)} s.`}
              <span className="ml-1 text-ink-2">This is a numerical comparison only — not a scientific PASS/FAIL and not validation.</span>
            </div>
            <Plot title={`${SIG[key].label} — overlay`} unit={SIG[key].unit} t={s.t} onTime={(t) => d({ type: 'time', t })} height={190} symmetric={key !== 'energy'} band={band}
              traces={[{ id: 'b', label: `baseline · ${base.label}`, color: 'var(--color-s1)', t: base.t, v: bv }, { id: 'c', label: `candidate · ${cand.label}`, color: 'var(--color-cand)', t: cand.t, v: cv, dash: '5 3' }]} />
            <Plot testId="plot-diff" title="Difference (candidate − baseline)" unit={SIG[key].unit} t={s.t} onTime={(t) => d({ type: 'time', t })} height={170} symmetric
              band={{ lo, hi, t: base.t, label: 'tol' }} traces={[{ id: 'd', label: 'Δ', color: 'var(--color-s5)', t: base.t, v: diff }]} footer="Shaded band: ± tolerance. Wheel to zoom, drag to move the shared time cursor; the 3D context shows the candidate as a ghost." />
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- validation ---------------- */

function Validation() {
  const { s } = useWB();
  const isP = s.study === 'pendulum-qual';
  return (
    <div className="grid gap-3" data-testid="validation">
      {isP ? (
        <Empty title="No experimental reference available" tag="NOT_ASSESSED">
          The only reference for this benchmark, <span className="mono">{PENDULUM_RELEASE.reference.id}</span>, is <b>synthetic</b> with category <span className="mono">solution_verification</span>. Agreement with it is numerical verification. Measured-model validation does not apply and has not been attempted; this is not a failed validation.
        </Empty>
      ) : (
        <Empty title="Measured reference declared, but no measured data is present" tag="NOT_IMPLEMENTED">
          Fixture reference <span className="mono">r.baseline-0</span> declares origin <span className="mono">experimental</span>, category <span className="mono">model_validation</span>, citation <i>none</i>. No dataset, subject record or acquisition metadata exists in the repository. Empirical validation is planned for M5 (RES-570).
        </Empty>
      )}
      <Box title="Validation workspace (designed interface — inactive until a measured reference exists)" right={<Tag tag="DESIGN_ONLY" />}>
        <div className="grid gap-3 opacity-80 lg:grid-cols-3" aria-disabled="true">
          <div>
            <div className="sec-h mb-1">1 · Measured source</div>
            <select className="field w-full" disabled><option>No measured dataset available</option></select>
            <div className="mt-2 flex flex-wrap gap-2 text-[11.5px]">
              <span className="inline-flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-s1" /> simulated (run output)</span>
              <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full border border-s4" /> measured (markers / force plate)</span>
            </div>
            <p className="mb-0 mt-1 text-[11px] text-ink-3">Simulated and measured data keep distinct origin, marks and provenance; they are never merged into one trace.</p>
          </div>
          <div>
            <div className="sec-h mb-1">2 · Alignment</div>
            <dl className="kv text-[12px]">
              <dt>Temporal basis</dt><dd>{isP ? '—' : 'event: takeoff, expected 0.300 s ± 0.005 s (fixture)'}</dd>
              <dt>Frames</dt><dd>{isP ? '—' : 'world, +z up (both)'}</dd>
              <dt>Resampling</dt><dd>declared per quantity</dd>
              <dt>Body inclusion</dt><dd>{isP ? '—' : 'foot / com (fixture)'}</dd>
            </dl>
          </div>
          <div>
            <div className="sec-h mb-1">3 · Metric and criterion</div>
            <dl className="kv text-[12px]">
              <dt>Metric</dt><dd className="mono">{isP ? PENDULUM_RELEASE.metric.id : LCMJ20.metric.id}</dd>
              <dt>Criterion</dt><dd>{isP ? 'none declared (placeholder statistic)' : `${LCMJ20.metric.criterion} over ${LCMJ20.metric.window}`}</dd>
              <dt>Result</dt><dd><Tag tag="NOT_ASSESSED" /></dd>
              <dt>Uncertainty</dt><dd>{isP ? 'numerical only' : 'marker placement variability (expected)'}</dd>
            </dl>
          </div>
        </div>
      </Box>
    </div>
  );
}

/* ---------------- uncertainty & sensitivity ---------------- */

function UQ() {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  const lo = s.uq.factorLower, hi = s.uq.factorUpper, n = s.uq.samples;
  const pts = Array.from({ length: n }, (_, i) => (n === 1 ? (lo + hi) / 2 : lo + ((hi - lo) * i) / (n - 1)));
  return (
    <div className="grid gap-3" data-testid="uq">
      <div className="rounded border border-line bg-panel px-3 py-2 text-[12.5px] text-ink-2" role="status">
        <Tag tag="NOT_ASSESSED" /> <b>Uncertainty and sensitivity: not assessed.</b> No ensemble has executed, no output distribution exists and no sensitivity index has been computed. Production UQ is not implemented.
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <Box title="Input factors" right={<Tag tag={isP ? 'AUTHORITY' : 'FIXTURE'} />}>
          {isP ? (
            <>
              <table className="data">
                <thead><tr><th>Factor</th><th>Role</th><th>Distribution</th><th>Unit</th></tr></thead>
                <tbody><tr><td className="mono">f.reference.gravity</td><td>declared factor id</td><td className="mono">point 9.80665</td><td>m·s⁻²</td></tr></tbody>
              </table>
              <p className="mb-0 mt-2 text-[12px] text-ink-3">{PENDULUM_RELEASE.uncertainty[0]} The fixed adapter accepts only the pinned scenario, so any perturbed input would be refused before physics.</p>
            </>
          ) : (
            <table className="data">
              <thead><tr><th>Factor</th><th>Role</th><th>Distribution</th><th>Target</th></tr></thead>
              <tbody>{LCMJ20.study.factors.map((f) => <tr key={f.id}><td className="mono">{f.id}</td><td>{f.role}</td><td className="mono">{f.dist === 'uniform' ? `U(${f.lower}, ${f.upper})` : `point ${f.value}`}</td><td className="mono">{f.target}</td></tr>)}</tbody>
            </table>
          )}
        </Box>
        <Box title="Sampling design draft" right={<Tag tag="DESIGN_ONLY" />}>
          <div className="grid grid-cols-3 gap-2 text-[12px]">
            <label className="grid gap-0.5">Lower<input className="field num" type="number" step="0.05" value={lo} disabled={isP} onChange={(e) => d({ type: 'uq', patch: { factorLower: Number(e.target.value) } })} /></label>
            <label className="grid gap-0.5">Upper<input className="field num" type="number" step="0.05" value={hi} disabled={isP} onChange={(e) => d({ type: 'uq', patch: { factorUpper: Number(e.target.value) } })} /></label>
            <label className="grid gap-0.5">Levels<input className="field num" type="number" min={1} max={9} value={n} disabled={isP} onChange={(e) => d({ type: 'uq', patch: { samples: Math.max(1, Math.min(9, Number(e.target.value))) } })} data-testid="uq-levels" /></label>
          </div>
          {!isP && (
            <>
              <div className="mt-2 text-[12px] text-ink-2">Planned matrix: {n} stiffness levels × {LCMJ20.study.seeds.length} seeds = <b>{n * LCMJ20.study.seeds.length}</b> planned runs (illustrative; real expansion is planning/plan.py).</div>
              <div className="scroll-thin mt-1.5 max-h-[160px] overflow-auto rounded border border-line">
                <table className="data">
                  <thead><tr><th>#</th><th>contact-stiffness scale</th><th>seed</th><th>gravity</th><th style={{ textAlign: 'left' }}>Status</th></tr></thead>
                  <tbody>
                    {pts.flatMap((p, i) => LCMJ20.study.seeds.map((sd, j) => (
                      <tr key={`${i}-${j}`}><td>{i * LCMJ20.study.seeds.length + j + 1}</td><td className="mono">{p.toFixed(3)}</td><td className="mono">{sd}</td><td className="mono">9.80665</td><td style={{ textAlign: 'left' }} className="text-err">not executable</td></tr>
                    )))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Box>
      </div>
      <Box title="Outputs" right={<Tag tag="NOT_ASSESSED" />}>
        <div className="grid gap-3 md:grid-cols-3">
          {['Output distribution of q.jump.height', 'Sensitivity (∂ outcome / ∂ factor)', 'Mean and half-range across seeds'].map((t) => (
            <div key={t} className="flex h-[110px] items-center justify-center rounded border border-dashed border-line-2 bg-panel-2 p-3 text-center text-[12px] text-ink-3"><span><b className="text-ink-2">{t}</b><br />not assessed — no ensemble results</span></div>
          ))}
        </div>
      </Box>
    </div>
  );
}

export function AnalysisMode() {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  const tabs: { id: AnalysisTab; label: string; sub: string }[] = [
    { id: 'verification', label: 'Solution verification', sub: isP ? 'numerical reference' : 'unavailable' },
    { id: 'compare', label: 'Compare series', sub: isP ? 'baseline vs candidate' : 'no runs' },
    { id: 'validation', label: 'Empirical validation', sub: 'measured reference' },
    { id: 'uq', label: 'Uncertainty & sensitivity', sub: 'factors · ensembles' },
  ];
  let body: ReactNode;
  if (!isP && (s.analysis === 'verification' || s.analysis === 'compare')) {
    body = <Empty title={s.analysis === 'verification' ? 'No numerical reference solution for this model' : 'No runs or series to compare'} tag="NOT_IMPLEMENTED">The LCMJ20 subject has no executable realization, so no trajectory, solution verification or run comparison exists. Multibody/contact verification is planned for M5 (RES-570). Switch the study to the reference pendulum to inspect the qualified verification workflow.</Empty>;
  } else body = s.analysis === 'verification' ? <Verification /> : s.analysis === 'compare' ? <Compare /> : s.analysis === 'validation' ? <Validation /> : <UQ />;
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-line bg-panel-2" data-testid="analysis">
      <div className="flex flex-none items-end gap-0 border-b border-line bg-panel px-1" role="tablist" aria-label="Analysis and VVUQ">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={s.analysis === t.id} className="dock-tab h-[40px] whitespace-nowrap text-left" onClick={() => d({ type: 'analysis', tab: t.id })} data-testid={`tab-${t.id}`}>
            <div>{t.label}</div><div className="text-[10.5px] font-normal text-ink-3">{t.sub}</div>
          </button>
        ))}
        <span className="mb-2 ml-auto pr-2 text-[11px] text-ink-3">Verification ≠ validation ≠ uncertainty — each is reported separately.</span>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto p-3" role="tabpanel">{body}</div>
    </div>
  );
}


