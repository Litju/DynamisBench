import type { ReactNode } from 'react';
import { LCMJ20, PENDULUM_RELEASE, REF, STATUS_MAP, type SourceTag } from '../data/authority';
import { STUDIES, useWB } from '../state';
import { Tag } from '../ui/kit';

function Card({ title, children, tag, className = '' }: { title: string; children: ReactNode; tag?: SourceTag; className?: string }) {
  return (
    <section className={`rounded-md border border-line bg-panel ${className}`} aria-label={title}>
      <header className="flex items-center gap-2 border-b border-line px-3 py-1.5"><h3 className="sec-h m-0">{title}</h3>{tag && <span className="ml-auto"><Tag tag={tag} /></span>}</header>
      <div className="px-3 py-2">{children}</div>
    </section>
  );
}

const LEVELS = ['unit_problem', 'benchmark_reference_case', 'subsystem_case', 'complete_system'];
const CAPS = ['forward_dynamics', 'state_snapshot', 'inverse_dynamics', 'interactive_dynamics', 'trajectory_optimization', 'analysis'];

export function StudyMode() {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  const st = STUDIES[s.study];
  const rel = isP ? PENDULUM_RELEASE : LCMJ20;
  const tag: SourceTag = isP ? 'AUTHORITY' : 'FIXTURE';
  const required = isP ? ['forward_dynamics'] : LCMJ20.study.requires;
  const realized = isP ? REF.capabilities : LCMJ20.realization.capabilities;
  const go = (id: string) => { d({ type: 'select', id }); };
  const list = (xs: string[]) => <ul className="m-0 list-disc pl-4 text-[12.5px] text-ink-2">{xs.map((x) => <li key={x}>{x}</li>)}</ul>;

  return (
    <div className="scroll-thin h-full overflow-auto" data-testid="study">
      <div className="mx-auto grid max-w-[1180px] gap-3 p-1">
        <section className="rounded-md border border-line bg-panel px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="sec-h">Research study</span><Tag tag={tag} />
            {!isP && <span className="text-[11.5px] text-ink-3">Schema test fixture — illustrates the target human-movement study; not a released benchmark and not data.</span>}
            <button className="btn btn-primary ml-auto" onClick={() => d({ type: 'mode', mode: 'lab' })} data-testid="open-lab">Open in Simulation Laboratory</button>
          </div>
          <h1 className="m-0 mt-1 text-[18px] font-semibold text-ink">{st.label}</h1>
          <p className="m-0 mt-1 max-w-[860px] text-[13px] text-ink-2">
            <span className="text-ink-3">Research question · </span>{isP && <><Tag tag="DESIGN_ONLY">paraphrase</Tag>{' '}</>}
            {isP ? 'Does the first real MuJoCo adapter reproduce an independent nonlinear pendulum solution within predeclared numerical tolerances on both qualified platforms?' : LCMJ20.study.question}
          </p>
          {!isP && <p className="m-0 mt-1 text-[12.5px] text-ink-3">Analysis plan · {LCMJ20.study.plan}</p>}
          {isP && <p className="m-0 mt-1 text-[12.5px] text-ink-3">Implied by RES-550 qualification; there is no StudyDefinition for the reference case in authority.</p>}
        </section>

        <div className="grid gap-3 lg:grid-cols-[1.25fr_1fr]">
          <Card title="Intended use and claim limits" tag={tag}>
            <dl className="kv">
              <dt>Intended use</dt><dd>{rel.intendedUse}</dd>
              <dt>Intended non-use</dt><dd>{rel.intendedNonUse}</dd>
              <dt>Conceptual model</dt><dd>{rel.conceptualModel}</dd>
              <dt>Claim ceiling</dt><dd className="font-medium">{rel.claimCeiling}</dd>
            </dl>
          </Card>
          <Card title="Credibility hierarchy" tag={tag}>
            <ol className="m-0 grid list-none gap-1 p-0">
              {LEVELS.map((l, i) => {
                const on = rel.credibility.includes(l);
                return (
                  <li key={l} className={`flex items-center gap-2 rounded border px-2 py-1 text-[12.5px] ${on ? 'border-sel bg-accent-soft text-accent-2' : 'border-line text-ink-3'}`}>
                    <span className="mono w-4 text-right">{i + 1}</span><span className="mono">{l}</span>
                    <span className="ml-auto text-[11px]">{on ? 'declared by benchmark' : 'not declared'}</span>
                  </li>
                );
              })}
            </ol>
            <p className="mb-0 mt-2 text-[11.5px] text-ink-3">Declared levels are a release property, not an achieved assessment.</p>
          </Card>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Card title="Assumptions" tag={tag}>{list(rel.assumptions)}</Card>
          <Card title="Applicability domain" tag={tag}>{list(rel.applicability)}</Card>
          <Card title="Known discrepancies" tag={tag}>{list(rel.discrepancies)}</Card>
          <Card title="Uncertainty expectations" tag={tag}>{list(rel.uncertainty)}</Card>
        </div>

        <Card title="Study composition — resolved references" tag={tag}>
          <div className="grid gap-2 md:grid-cols-5">
            {([['Benchmark', 'ctx.benchmark', st.benchmark], ['Scenario', 'ctx.scenario', st.scenario], ['Realization', 'ctx.realization', st.realization], ['System under test', 'ctx.sut', st.sut], ['Environment', 'ctx.environment', st.env]] as const).map(([k, id, v]) => (
              <button key={id} className={`rounded border px-2 py-1.5 text-left hover:border-sel ${s.selection === id ? 'border-sel bg-accent-soft' : 'border-line bg-panel-2'}`} onClick={() => go(id)}>
                <div className="sec-h">{k}</div>
                <div className="mono mt-0.5 break-all text-[11.5px] text-ink">{v}</div>
              </button>
            ))}
          </div>
          {isP && <p className="mb-0 mt-2 text-[11.5px] text-ink-3">Each identity is bound by a reviewed semantic digest pinned in reference.py; a same-name definition with different meaning is refused.</p>}
        </Card>

        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="Capability coverage" tag={tag}>
            <table className="data wrap left">
              <thead><tr><th>Capability</th><th>Required</th><th>Realization</th><th>Qualified adapter</th></tr></thead>
              <tbody>
                {CAPS.map((c) => {
                  const req = required.includes(c), rl = realized.includes(c), q = REF.capabilities.includes(c);
                  return (
                    <tr key={c}>
                      <td className="mono">{c}</td>
                      <td>{req ? 'required' : '—'}</td>
                      <td>{rl ? 'declared' : '—'}</td>
                      <td className={req && !q ? 'font-semibold text-err' : q ? 'text-ok' : 'text-ink-3'}>{q ? 'forward_dynamics only' : req ? 'missing → refusal' : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
          <Card title={isP ? 'Parameters and factors' : 'Study factors and design'} tag={tag}>
            {isP ? (
              <table className="data wrap left">
                <thead><tr><th>Parameter</th><th>Value</th><th>Unit</th><th>Role</th></tr></thead>
                <tbody>
                  <tr><td>initial hinge angle</td><td className="mono">0.5235987756</td><td>rad</td><td>scenario initial condition</td></tr>
                  <tr><td>initial angular velocity</td><td className="mono">0</td><td>rad·s⁻¹</td><td>scenario initial condition</td></tr>
                  <tr><td>gravity (f.reference.gravity)</td><td className="mono">9.80665</td><td>m·s⁻²</td><td>declared factor id; point value</td></tr>
                  <tr><td>seed</td><td className="mono">0</td><td>—</td><td>recorded, not consumed</td></tr>
                </tbody>
              </table>
            ) : (
              <>
                <table className="data wrap left">
                  <thead><tr><th>Factor</th><th>Role</th><th>Distribution</th><th>Target</th></tr></thead>
                  <tbody>
                    {LCMJ20.study.factors.map((f) => (
                      <tr key={f.id}><td className="mono">{f.id}</td><td>{f.role}</td><td className="mono">{f.dist === 'uniform' ? `U(${f.lower}, ${f.upper})` : `point ${f.value}`} {f.unit}</td><td className="mono">{f.target}</td></tr>
                    ))}
                  </tbody>
                </table>
                <p className="mb-0 mt-2 text-[12px] text-ink-2">Replicates {LCMJ20.study.replicates} · seeds {LCMJ20.study.seeds.join(', ')} · outcome q.jump.height</p>
              </>
            )}
          </Card>
        </div>

        <Card title="Planned comparisons">
          <table className="data wrap left">
            <thead><tr><th>Comparison</th><th>Kind</th><th>Status</th><th>Dependency</th></tr></thead>
            <tbody>
              <tr><td>Windows vs Linux MuJoCo receipts</td><td>cross-platform numerical agreement</td><td><Tag tag="QUALIFIED">receipt comparison job (non-gate)</Tag></td><td className="mono">RES-550</td></tr>
              <tr><td>Nominal vs refinement timesteps</td><td>solution verification (convergence)</td><td><Tag tag="QUALIFIED" /></td><td className="mono">RES-550</td></tr>
              <tr><td>MuJoCo vs OpenSim / Moco</td><td>cross-engine quantity comparison</td><td><Tag tag="NOT_IMPLEMENTED">planned M7</Tag></td><td className="mono">RES-571</td></tr>
              <tr><td>LCMJ20 model vs measured jump</td><td>empirical validation</td><td><Tag tag="NOT_IMPLEMENTED">planned M5</Tag></td><td className="mono">RES-570</td></tr>
              <tr><td>Contact-stiffness sensitivity</td><td>uncertainty / sensitivity</td><td><Tag tag="NOT_IMPLEMENTED" /></td><td className="mono">no executable realization</td></tr>
            </tbody>
          </table>
        </Card>

        <Card title="DynamisBench capability status (source-to-UI map)">
          <table className="data wrap left">
            <thead><tr><th>Area</th><th>Status</th><th>Dependency</th></tr></thead>
            <tbody>
              {STATUS_MAP.map((r) => (
                <tr key={r.area}><td>{r.area}</td><td className={`mono ${r.status === 'NOT_IMPLEMENTED' ? 'text-err' : r.status === 'PLANNED' ? 'text-warn' : 'text-ok'}`}>{r.status}</td><td className="mono text-ink-3">{r.dep}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
