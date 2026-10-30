import type { ReactNode } from 'react';
import { LCMJ20, PENDULUM_RELEASE, REF, type SourceTag } from '../data/authority';
import { useModelEntities } from '../data/entities';
import { HUMAN_COORDS, type Prop } from '../data/models';
import { useMyoModel } from '../data/myosim';
import { idx, seriesById } from '../data/numerics';
import { draftDiff, STUDIES, useWB } from '../state';
import { fmt, Icon, KV, LifecycleChip, Src, Tag } from '../ui/kit';

function Header({ kind, title, tag, sub }: { kind: string; title: string; tag?: SourceTag; sub?: string }) {
  return (
    <div className="border-b border-line px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="sec-h">{kind}</span>
        {tag && <span className="ml-auto"><Tag tag={tag} /></span>}
      </div>
      <h2 className="m-0 mt-0.5 break-all text-[14px] font-semibold text-ink" data-testid="inspector-title">{title}</h2>
      {sub && <div className="mt-0.5 text-[11.5px] text-ink-3">{sub}</div>}
    </div>
  );
}

function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="border-b border-line px-3 py-2.5">
      <div className="mb-1.5 flex items-center"><h3 className="sec-h m-0">{title}</h3><span className="ml-auto">{right}</span></div>
      {children}
    </section>
  );
}

function PropTable({ props, owner }: { props: Prop[]; owner: SourceTag }) {
  const { s } = useWB();
  const i = idx(s.t);
  const nom = seriesById('series.rk4-1ms');
  const live = (p: Prop): string => {
    if (!p.live) return p.value;
    if (p.live === 'theta') return fmt(nom.theta[i], 6);
    if (p.live === 'omega') return fmt(nom.omega[i], 6);
    if (p.live === 'energy') return fmt(nom.energy[i], 6);
    if (p.live === 'bobx') return fmt(-Math.sin(nom.theta[i]), 6);
    if (p.live === 'bobz') return fmt(-Math.cos(nom.theta[i]), 6);
    if (p.live.startsWith('myo:')) return fmt(s.myoPose[p.live.slice(4)] ?? 0, 3);
    const c = p.live.slice(6);
    return fmt(s.pose[c] ?? NaN, 3);
  };
  return (
    <table className="w-full border-collapse text-[12px]">
      <tbody>
        {props.map((p) => (
          <tr key={p.name} className="border-b border-line-soft align-top last:border-0">
            <th scope="row" className="w-[44%] py-1 pr-2 text-left font-normal text-ink-3">{p.name}</th>
            <td className="py-1">
              <span className={`${p.live ? 'mono text-ink' : ''} ${p.value === 'not available' ? 'text-ink-3 italic' : ''} break-all`}>{live(p) || '—'}</span>
              {p.unit && <span className="ml-1 text-[11px] text-ink-3">{p.unit}</span>}
              {p.frame && <span className="ml-1 text-[11px] text-ink-3">· {p.frame}</span>}
              {p.live && s.study === 'pendulum-qual' && <span className="ml-1 text-[10.5px] text-calc">@ t={s.t.toFixed(3)} s</span>}
              {((p.tag !== owner && p.tag !== 'AUTHORITY' && p.tag !== 'NOT_IMPLEMENTED') || p.note) && (
                <div className="mt-0.5 flex flex-wrap items-center gap-1">
                  {p.tag !== owner && p.tag !== 'AUTHORITY' && p.tag !== 'NOT_IMPLEMENTED' && <Src tag={p.tag} />}
                  {p.note && <span className="text-[11px] text-ink-3">{p.note}</span>}
                </div>
              )}
            </td>
          </tr>
        ))}
      </tbody>
      {props.some((p) => p.value === 'not available') && (
        <tfoot><tr><td colSpan={2} className="pt-1.5 text-[11px] text-ink-3"><Src tag="NOT_IMPLEMENTED" label={false} /> “not available”: the realization asset <span className="mono">models/realization/subject.xml</span> carries a placeholder digest in the fixture and is not materialized (RES-555). No values are inferred.</td></tr></tfoot>
      )}
    </table>
  );
}

const Mono = ({ children }: { children: ReactNode }) => <span className="mono break-all">{children}</span>;

function ScenarioEditor() {
  const { s, d } = useWB();
  const diff = draftDiff(s.draft);
  const num = (k: 'theta0Deg' | 'duration' | 'seed', label: string, unit: string, step: number) => (
    <label className="grid grid-cols-[1fr_96px_42px] items-center gap-2 py-0.5">
      <span className="text-[12px] text-ink-2">{label}</span>
      <input type="number" className="field num w-full text-right" step={step} value={s.draft[k]} onChange={(e) => d({ type: 'draft', patch: { [k]: Number(e.target.value) } })} data-testid={`draft-${k}`} />
      <span className="text-[11px] text-ink-3">{unit}</span>
    </label>
  );
  return (
    <>
      <Section title="Scenario draft" right={<Tag tag="DESIGN_ONLY">Local draft</Tag>}>
        <p className="mb-2 mt-0 text-[11.5px] text-ink-3">Editing creates a local design draft only. It is not an accepted RunSpec and has no execution fingerprint.</p>
        {num('theta0Deg', 'Initial hinge angle', 'deg', 1)}
        <div className="grid grid-cols-[1fr_96px_42px] items-center gap-2 py-0.5">
          <span className="text-[12px] text-ink-2">Initial angular velocity</span>
          <input className="field num w-full text-right" value="0" disabled aria-label="Initial angular velocity (fixed)" />
          <span className="text-[11px] text-ink-3">rad/s</span>
        </div>
        {num('duration', 'Duration', 's', 0.5)}
        <label className="grid grid-cols-[1fr_96px_42px] items-center gap-2 py-0.5">
          <span className="text-[12px] text-ink-2">Timestep</span>
          <select className="field num w-full" value={s.draft.timestep} onChange={(e) => d({ type: 'draft', patch: { timestep: Number(e.target.value) } })} data-testid="draft-timestep">
            {[0.01, 0.005, 0.002, 0.001, 0.0005].map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
          <span className="text-[11px] text-ink-3">s</span>
        </label>
        <label className="grid grid-cols-[1fr_96px_42px] items-center gap-2 py-0.5">
          <span className="text-[12px] text-ink-2">Integrator</span>
          <select className="field w-full" value={s.draft.integrator} onChange={(e) => d({ type: 'draft', patch: { integrator: e.target.value } })}>
            {['RK4', 'Euler', 'implicit', 'implicitfast'].map((v) => <option key={v}>{v}</option>)}
          </select>
          <span />
        </label>
        {num('seed', 'Seed (recorded, not consumed)', '', 1)}
        <div className="mt-2 flex items-center gap-2">
          {diff.length === 0 ? <span className="text-[12px] text-ok">Draft equals the pinned reference scenario.</span> : <span className="text-[12px] text-warn" data-testid="draft-diff">{diff.length} change{diff.length > 1 ? 's' : ''} from reference</span>}
          <button className="btn ml-auto" onClick={() => d({ type: 'resetDraft' })} disabled={diff.length === 0}>Restore reference</button>
        </div>
      </Section>
      <Section title="Draft plan preview">
        <pre className="mono m-0 max-h-[210px] overflow-auto whitespace-pre-wrap rounded bg-sunk p-2 text-[11px] leading-[1.45] text-ink-2">{`benchmark   ${REF.benchmarkId} ${REF.benchmarkVersion}
scenario    ${REF.scenarioId} ${REF.scenarioVersion}${diff.length ? '  ← MODIFIED (draft)' : ''}
  initial   q.pendulum.hinge-angle = ${(s.draft.theta0Deg * Math.PI / 180).toPrecision(16)} [1]
            q.pendulum.hinge-angular-velocity = 0 [s^-1]
  duration  ${s.draft.duration} s
realization ${REF.realizationId} ${REF.realizationVersion}
  timestep  ${s.draft.timestep}   integrator ${s.draft.integrator}
sut         ${REF.sutId} ${REF.sutVersion}
seed        ${s.draft.seed}
fingerprint not compiled (no RunSpec compiler in browser)`}</pre>
      </Section>
    </>
  );
}

export function Inspector({ onCollapse }: { onCollapse?: () => void }) {
  const { s, d } = useWB();
  const sel = s.selection ?? 'model';
  const { entities } = useModelEntities();
  const { model: myo } = useMyoModel();
  const st = STUDIES[s.study];
  const isP = s.study === 'pendulum-qual';

  let body: ReactNode;
  const ent = entities.find((e) => e.id === sel) ?? null;
  if (ent) {
    const linked = ent.signals ?? [];
    body = (
      <>
        <Header kind={ent.kind} title={ent.label} tag={ent.tag} sub={ent.sub} />
        {ent.summary && <Section title="Description"><p className="m-0 text-[12.5px] text-ink-2">{ent.summary}</p></Section>}
        {ent.props && <Section title="Properties"><PropTable props={ent.props} owner={ent.tag} /></Section>}
        {ent.kind === 'joint' && !isP && !ent.id.startsWith('mjoint.') && (
          <Section title="Pose coordinate (design inspection)" right={<Tag tag="DESIGN_ONLY" />}>
            {HUMAN_COORDS.filter((c) => c.joint === ent.id).map((c) => (
              <label key={c.id} className="grid grid-cols-[1fr_70px] items-center gap-2">
                <input type="range" min={c.min} max={c.max} step={0.01} value={s.pose[c.id]} onChange={(e) => d({ type: 'pose', id: c.id, value: Number(e.target.value) })} aria-label={`${c.label} pose`} />
                <span className="mono text-right">{s.pose[c.id].toFixed(2)} {c.unit}</span>
              </label>
            ))}
            <p className="mb-0 mt-1.5 text-[11px] text-ink-3">Posing moves the schematic only. It is not a simulation state, not a measured posture and not a joint limit.</p>
          </Section>
        )}
        {ent.id.startsWith('mjoint.') && myo && (() => {
          const j = myo.joints.get(ent.id.slice(7));
          if (!j || /translation|rotation2|rotation3|beta/.test(j.name)) return null;
          const [lo, hi] = j.range ?? [-Math.PI, Math.PI];
          const v = s.myoPose[j.name] ?? 0;
          return (
            <Section title="Pose coordinate (design inspection)" right={<Tag tag="DESIGN_ONLY" />}>
              <label className="grid grid-cols-[1fr_76px] items-center gap-2">
                <input type="range" min={lo} max={hi} step="any" value={v} onChange={(e) => d({ type: 'myoPose', joint: j.name, value: Number(e.target.value) })} aria-label={`${j.name} pose`} data-testid={`inspector-pose-${j.name}`} />
                <span className="mono text-right">{v.toFixed(3)} {j.type === 'hinge' ? 'rad' : 'm'}</span>
              </label>
              <div className="mt-0.5 flex justify-between text-[10.5px] text-ink-3"><span>{lo.toFixed(3)}</span><span>model range</span><span>{hi.toFixed(3)}</span></div>
              <p className="mb-0 mt-1.5 text-[11px] text-ink-3">Moves the reference geometry within the model's declared range. Not a simulation state and not a measured posture.</p>
            </Section>
          );
        })()}
        {linked.length > 0 && (
          <Section title="Linked signals">
            <div className="flex flex-wrap gap-1.5">
              {linked.map((sig) => (
                <button key={sig} className="btn h-[22px] text-[11.5px]" onClick={() => d({ type: 'dock', tab: 'signals' })}>{sig}</button>
              ))}
            </div>
            {!isP && <p className="mb-0 mt-1.5 text-[11px] text-ink-3">No trajectory exists for this model; linked signal panels show the declared quantity with a not-produced state.</p>}
          </Section>
        )}
        <Section title="Source">
          <div className="text-[11.5px] text-ink-3">
            {ent.tag === 'AUTHORITY' && <Mono>{REF.modelAsset}</Mono>}
            {ent.tag === 'FIXTURE' && <Mono>{LCMJ20.src}</Mono>}
            {ent.tag === 'DESIGN_ONLY' && 'Prototype schematic (src/data/models.ts). No accepted definition.'}
            {ent.tag === 'EXTERNAL' && <>MyoHub/myo_sim @ 93b0ca8f (Apache-2.0) · public/assets/myosim/NOTICE</>}
            {ent.tag === 'NOT_IMPLEMENTED' && 'No definition exists.'}
          </div>
        </Section>
      </>
    );
  } else if (sel === 'ctx.scenario') {
    body = isP ? (
      <>
        <Header kind="scenario" title={`${REF.scenarioId} ${REF.scenarioVersion}`} tag="AUTHORITY" sub="Reference pendulum, 30 degrees, zero velocity" />
        <ScenarioEditor />
        <Section title="Pinned identity"><KV rows={[['Semantic digest', <Mono>{REF.digests.scenario}</Mono>], ['Required', 'forward_dynamics (essential)']]} /></Section>
      </>
    ) : (
      <>
        <Header kind="scenario" title={`${LCMJ20.scenario.id} 1.0.0`} tag="FIXTURE" sub={LCMJ20.scenario.label} />
        <Section title="Definition"><KV rows={[['Duration', '2.0 s'], ['Initial condition', 'q.foot.vertical_force = 0.0 N'], ['Event', `takeoff · expected ${LCMJ20.scenario.event.t} s ± ${LCMJ20.scenario.event.tol} s`], ['Required', 'forward_dynamics (essential)']]} /></Section>
        <Section title="Editing"><p className="m-0 text-[12px] text-ink-3">Read-only. No executable realization exists for this scenario, so a draft would have no admissible path.</p></Section>
      </>
    );
  } else if (sel.startsWith('ctx.')) {
    const k = sel.slice(4);
    const rows: [ReactNode, ReactNode][] = isP
      ? ({
          benchmark: [['Identity', `${REF.benchmarkId} ${REF.benchmarkVersion}`], ['Label', PENDULUM_RELEASE.label], ['Credibility', 'unit_problem'], ['Semantic digest', <Mono>{REF.digests.benchmark}</Mono>]],
          realization: [['Identity', `${REF.realizationId} ${REF.realizationVersion}`], ['Engine', `mujoco == ${REF.engineVersion}`], ['Capability', 'forward_dynamics — real MuJoCo forward dynamics for the fixed planar pendulum'], ['Limitations', 'One fixed model; no arbitrary model loading, controllers, contacts, interactive stepping, inverse dynamics or optimization.'], ['Semantic digest', <Mono>{REF.digests.realization}</Mono>]],
          sut: [['Identity', `${REF.sutId} ${REF.sutVersion}`], ['Semantic digest', <Mono>{REF.digests.sut}</Mono>]],
          environment: [['Identity', 'env.mujoco.reference.windows-x86-64 1.0.0'], ['Requirements', `mujoco == ${REF.engineVersion} (engine); python == ${REF.pythonVersion} (runtime)`], ['Qualified platforms', 'windows-x86-64, linux-x86-64 (distinct environments, ADR-023)'], ['Semantic digest', <Mono>{REF.digests['environment (windows-x86-64)']}</Mono>]],
        } as Record<string, [ReactNode, ReactNode][]>)[k]
      : ({
          benchmark: [['Identity', 'db.lcmj20 1.0.0'], ['Label', LCMJ20.label], ['Credibility', LCMJ20.credibility.join(' → ')], ['Status', 'schema test fixture; not a released benchmark']],
          realization: [['Identity', 'rl.mujoco.loaded-cmj 1.0.0'], ['Engine', `mujoco ${LCMJ20.realization.engineSpecifier}`], ['Capabilities', LCMJ20.realization.capabilities.join(', ')], ['Asset', `${LCMJ20.realization.asset.path} (placeholder digest)`]],
          sut: [['Identity', 'sut.baseline-0 1.0.0'], ['Definition', 'referenced by the fixture study; no SUT definition with this id exists in the corpus']],
          environment: [['Identity', 'env.mujoco.x86-64 1.0.0'], ['Status', 'fixture environment; not a qualified worker environment']],
        } as Record<string, [ReactNode, ReactNode][]>)[k];
    body = (
      <>
        <Header kind={k} title={rows[0][1] as string} tag={st.tag} />
        <Section title="Definition"><KV rows={rows} /></Section>
        <Section title="Source"><Mono>{isP ? PENDULUM_RELEASE.src : LCMJ20.src}</Mono></Section>
      </>
    );
  } else if (sel.startsWith('series:')) {
    const ser = seriesById(sel.slice(7));
    const i = idx(s.t);
    body = (
      <>
        <Header kind="synthetic series" title={ser.label} tag="RECOMPUTED" sub={ser.method} />
        <Section title="Identity">
          <KV rows={[['Series id', <Mono>{ser.id}</Mono>], ['Origin', 'computed in this browser from reference.py constants'], ['Output grid', '1 ms, 2001 samples, relative_to_start'], ['Is a run?', 'No — no RunSpec, no worker, no fingerprint'], ['Evidence', 'none (not native, not canonical)']]} />
        </Section>
        <Section title={`State at t = ${s.t.toFixed(3)} s`}>
          <KV rows={[['θ', `${fmt(ser.theta[i], 8)} rad`], ['ω', `${fmt(ser.omega[i], 8)} rad/s`], ['E', `${fmt(ser.energy[i], 8)} J`]]} />
        </Section>
        <Section title="Use"><button className="btn" onClick={() => { d({ type: 'compare', patch: { candidate: ser.id === 'series.rk4-1ms' ? 'series.rk4-10ms' : ser.id } }); d({ type: 'analysis', tab: 'compare' }); d({ type: 'mode', mode: 'analysis' }); }}>Compare against baseline</button></Section>
      </>
    );
  } else if (sel.startsWith('run:')) {
    const r = s.runs.find((x) => `run:${x.id}` === sel);
    body = r ? (
      <>
        <Header kind="execution record" title={r.id} tag="DESIGN_ONLY" sub="Design-demo lifecycle — no simulator invoked" />
        <Section title="Lifecycle"><KV rows={[['State', <LifecycleChip state={r.state} />], ['Refusal / stop code', r.refusal ? <Mono>{r.refusal}</Mono> : '—'], ['Injected outcome', r.outcome], ['Study', STUDIES[r.study].label]]} /></Section>
        <Section title="Evidence status">
          <KV rows={[['Process', r.state === 'completed' ? 'completed (process fact)' : r.state], ['Native evidence', <Tag tag="NOT_IMPLEMENTED">not produced</Tag>], ['Canonical', <Tag tag="NOT_IMPLEMENTED">not produced</Tag>], ['Assessment', <Tag tag="NOT_ASSESSED" />]]} />
        </Section>
        <Section title="Actions"><button className="btn" onClick={() => { d({ type: 'activeRun', id: r.id }); d({ type: 'dock', tab: 'log' }); d({ type: 'mode', mode: 'lab' }); }}>Open log in Laboratory</button></Section>
      </>
    ) : <Header kind="execution" title="No runs" />;
  } else if (sel.startsWith('ref:')) {
    body = isP ? (
      <>
        <Header kind="reference" title={PENDULUM_RELEASE.reference.id} tag="AUTHORITY" sub={PENDULUM_RELEASE.reference.label} />
        <Section title="Definition"><KV rows={[['Category', 'solution_verification'], ['Origin', 'synthetic'], ['License', 'CC0-1.0'], ['Is measured data?', 'No — an independent numerical solve of the pendulum equation']]} /></Section>
        <Section title="Use"><button className="btn" onClick={() => { d({ type: 'analysis', tab: 'verification' }); d({ type: 'mode', mode: 'analysis' }); }}>Open solution verification</button></Section>
      </>
    ) : (
      <>
        <Header kind="reference" title="r.baseline-0 1.0.0" tag="FIXTURE" sub="Baseline 0 reference" />
        <Section title="Definition"><KV rows={[['Category', 'model_validation'], ['Origin', 'experimental'], ['Citation', 'none'], ['Measured data', <Tag tag="NOT_IMPLEMENTED">not present</Tag>]]} /></Section>
        <Section title="Use"><button className="btn" onClick={() => { d({ type: 'analysis', tab: 'validation' }); d({ type: 'mode', mode: 'analysis' }); }}>Open validation workspace</button></Section>
      </>
    );
  } else {
    body = <Header kind="selection" title="Nothing selected" />;
  }

  return (
    <aside className="panel flex h-full min-h-0 flex-col" aria-label="Inspector">
      <header className="panel-h">
        <Icon name="panel" size={13} /> Inspector
        <span className="ml-auto mono truncate normal-case tracking-normal text-[10.5px] text-ink-3">{sel}</span>
        {onCollapse && <button className="btn btn-ghost btn-icon h-[22px] w-[22px]" onClick={onCollapse} aria-label="Collapse inspector" title="Collapse inspector (])"><Icon name="chev" size={11} /></button>}
      </header>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto" data-testid="inspector">{body}</div>
    </aside>
  );
}

