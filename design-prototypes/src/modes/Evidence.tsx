import type { ReactNode } from 'react';
import { CRITERIA, LCMJ20, PENDULUM_RELEASE, REF, type SourceTag } from '../data/authority';
import { draftDiff, useWB } from '../state';
import { LifecycleChip, Tag } from '../ui/kit';

type Stage = { id: string; layer: string; title: string; tag: SourceTag; tagText?: string; status: string; detail: ReactNode; dep?: string };

const Mono = ({ children }: { children: ReactNode }) => <span className="mono break-all">{children}</span>;

export function EvidenceMode() {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  const run = s.runs.find((r) => r.id === s.activeRun && r.study === s.study);
  const diff = draftDiff(s.draft);

  const stages: Stage[] = isP
    ? [
        { id: 'source', layer: 'Source authority', title: 'Benchmark · scenario · realization · SUT · environment', tag: 'AUTHORITY', status: 'implemented · digests pinned',
          detail: (
            <>
              <p className="mt-0">Engine-independent definitions in <Mono>{PENDULUM_RELEASE.src}</Mono>. Reviewed semantic digests are pinned in <Mono>{REF.src}</Mono> and recomputed by the test suite and <Mono>python/tools/mujoco_reference_authority.py</Mono>.</p>
              <table className="data wrap"><thead><tr><th>Definition</th><th style={{ textAlign: 'left' }}>Semantic SHA-256</th></tr></thead>
                <tbody>{Object.entries(REF.digests).map(([k, v]) => <tr key={k}><td>{k}</td><td style={{ textAlign: 'left' }} className="mono">{v}</td></tr>)}
                  <tr><td>model asset (raw bytes)</td><td style={{ textAlign: 'left' }} className="mono">{REF.modelSha256}</td></tr></tbody></table>
            </>
          ) },
        { id: 'runspec', layer: 'Plan', title: 'Compiled RunSpec + execution fingerprint', tag: 'NOT_ASSESSED', tagText: 'Not compiled here', status: diff.length ? 'draft modified · not compiled' : 'not compiled in prototype', dep: 'planning/runspec.py (implemented in core)',
          detail: <p className="m-0">The RunSpec compiler exists in the Python core, but this browser prototype does not call it. No fingerprint is displayed because none was produced — the prototype never manufactures digests. {diff.length > 0 && <>Current draft differs from the reference: {diff.join('; ')}.</>}</p> },
        { id: 'preflight', layer: 'Admission', title: 'Capability / identity preflight', tag: s.preflight ? 'DESIGN_ONLY' : 'NOT_ASSESSED', status: s.preflight ? `design demo · ${s.preflight.decision}` : 'not checked', dep: 'execution/preflight.py (RES-549, outside the app)',
          detail: <p className="m-0">Real preflight runs in the supervisor outside the app. The Laboratory shows a deterministic demonstration using the accepted RefusalCode vocabulary. Admission is a fact about starting, not a promise of success.</p> },
        { id: 'exec', layer: 'Execution', title: 'Isolated MuJoCo worker — fixed reference pendulum', tag: 'QUALIFIED', status: run ? `latest demo: ${run.state}` : 'no execution in this session', dep: 'RES-550; no production run API',
          detail: <><p className="mt-0">MuJoCo {REF.engineVersion} / Python {REF.pythonVersion}; qualified on windows-x86-64 and linux-x86-64. Only forward_dynamics for the one pinned experiment.</p>{run && <div className="flex items-center gap-2">Latest design-demo record <span className="mono">{run.id}</span> <LifecycleChip state={run.state} /></div>}<p className="mb-0 mt-2 text-ink-3">Process <b>completed</b> is a worker fact. It is not evidence, not a verified solution and not a scientific result.</p></> },
        { id: 'diag', layer: 'Native (bounded)', title: 'Adapter diagnostic on stderr', tag: 'AUTHORITY', status: 'schema defined · not evidence', dep: 'diagnostics.py',
          detail: <p className="m-0">Schema <Mono>{'dynamisbench.mujoco.reference-diagnostic/1'}</Mono>: initial/final/checkpoint states, energy drift, trajectory SHA-256. Retained as a bounded log. Explicitly <b>not NativeEvidence</b>: not written to native/, not sealed, not canonical, not assessed.</p> },
        { id: 'receipt', layer: 'Qualification', title: 'Numerical qualification receipts (Windows, Linux) + comparison', tag: 'QUALIFIED', status: 'CI artifacts · not in repo', dep: 'mujoco_qualification_receipt.py',
          detail: <p className="m-0">Receipts are CI qualification artifacts, not native/, canonical/ or assessment layers. Their observed values are not present locally, so the workbench links the procedure and criteria but shows no receipt numbers.</p> },
        { id: 'native', layer: 'Native evidence', title: 'Content-addressed inputs + sealed native evidence', tag: 'NOT_IMPLEMENTED', status: 'not produced', dep: 'RES-555 / RES-561 authority repair',
          detail: <p className="m-0">No accepted channel, artifact schema, validation record or seal policy exists for native simulator outputs. Nothing in this workbench is sealed.</p> },
        { id: 'canonical', layer: 'Canonical', title: 'Native → canonical quantity, frame, unit and time mapping', tag: 'NOT_IMPLEMENTED', status: 'planned M4', dep: 'RES-569',
          detail: <p className="m-0">Realization mappings exist (hinge-angle → q.pendulum.hinge-angle); the normalization/query layer is planned. Cross-run comparisons in Analysis therefore use synthetic series, not canonical queries.</p> },
        { id: 'verif', layer: 'Assessment', title: 'Numerical solution verification', tag: 'QUALIFIED', status: 'fixed reference only', dep: 'qualification_criteria.py',
          detail: <p className="m-0">{CRITERIA.claimLimit}</p> },
        { id: 'valid', layer: 'Assessment', title: 'Measured-model validation', tag: 'NOT_ASSESSED', status: 'no measured reference', detail: <p className="m-0">Reference is synthetic. Validation does not apply; this is not a failed validation.</p> },
        { id: 'uq', layer: 'Assessment', title: 'Uncertainty and sensitivity', tag: 'NOT_ASSESSED', status: 'not assessed', detail: <p className="m-0">{PENDULUM_RELEASE.uncertainty[0]}</p> },
        { id: 'claim', layer: 'Claim', title: 'Credible scientific claim', tag: 'AUTHORITY', status: 'bounded by claim ceiling', detail: <p className="m-0"><b>Claim ceiling:</b> {PENDULUM_RELEASE.claimCeiling}<br /><b>Intended non-use:</b> {PENDULUM_RELEASE.intendedNonUse}</p> },
      ]
    : [
        { id: 'source', layer: 'Source authority', title: 'LCMJ20 definitions', tag: 'FIXTURE', status: 'schema test fixtures', detail: <p className="m-0"><Mono>{LCMJ20.src}</Mono> and sibling fixtures validate the domain schema. They are not a released benchmark; the subject asset digest is an all-zero placeholder and the reference has no citation.</p> },
        { id: 'runspec', layer: 'Plan', title: 'Compiled RunSpec + execution fingerprint', tag: 'NOT_IMPLEMENTED', status: 'not compiled', detail: <p className="m-0">No fingerprint shown; none produced.</p> },
        { id: 'preflight', layer: 'Admission', title: 'Capability / identity preflight', tag: s.preflight ? 'DESIGN_ONLY' : 'NOT_ASSESSED', status: s.preflight ? 'design demo · refused' : 'not checked', detail: <p className="m-0">Would refuse: unsupported_capability (state_snapshot), adapter_engine_mismatch (== 3.3.0 vs 3.17.0), unstaged_asset (subject-model).</p> },
        { id: 'exec', layer: 'Execution', title: 'Worker execution', tag: 'NOT_IMPLEMENTED', status: 'no qualified realization', detail: <p className="m-0">No human-movement adapter or model exists.</p> },
        { id: 'native', layer: 'Native evidence', title: 'Sealed native evidence', tag: 'NOT_IMPLEMENTED', status: 'not produced', dep: 'RES-555', detail: <p className="m-0">—</p> },
        { id: 'canonical', layer: 'Canonical', title: 'q.foot.vertical_force, q.jump.height', tag: 'NOT_IMPLEMENTED', status: 'planned M4', dep: 'RES-569', detail: <p className="m-0">Quantity definitions exist as fixtures; no values.</p> },
        { id: 'verif', layer: 'Assessment', title: 'Multibody / contact verification', tag: 'NOT_IMPLEMENTED', status: 'planned M5', dep: 'RES-570', detail: <p className="m-0">—</p> },
        { id: 'valid', layer: 'Assessment', title: 'Empirical validation vs r.baseline-0', tag: 'NOT_IMPLEMENTED', status: 'no measured data', dep: 'RES-570', detail: <p className="m-0">Metric m.jump_height.rmse &lt; 0.01 m declared; not evaluated.</p> },
        { id: 'uq', layer: 'Assessment', title: 'Contact-stiffness sensitivity', tag: 'NOT_ASSESSED', status: 'not assessed', detail: <p className="m-0">Factor U(0.8, 1.2) declared; no ensemble.</p> },
        { id: 'claim', layer: 'Claim', title: 'Credible scientific claim', tag: 'NOT_ASSESSED', status: 'none', detail: <p className="m-0">Fixture claim ceiling text: “{LCMJ20.claimCeiling}” No claim is supported.</p> },
      ];

  const focus = stages.find((x) => x.id === s.evidenceFocus) ?? stages[0];
  const distinctions: [string, string, string][] = isP
    ? [
        ['Schema-valid definition', 'yes — validated domain models', 'Physically valid model'],
        ['Process completed', run?.state === 'completed' ? 'yes (demo record)' : 'not in this session', 'Evidence sealed — no'],
        ['Artifact integrity (digests)', 'model + definitions pinned', 'Numerical verification — separate'],
        ['Numerical verification', 'qualified, fixed reference', 'Experimental validation — not applicable'],
        ['Simulation output', 'synthetic series only here', 'Measured observation — none'],
        ['3D playback time', 'cursor over recorded samples', 'Solver step — never'],
        ['Parametric draft', diff.length ? 'modified' : 'equals reference', 'Accepted RunSpec fingerprint — not compiled'],
        ['No evidence', 'shown as not assessed', 'Failed validation — never implied'],
      ]
    : [
        ['Schema-valid fixture', 'yes — test corpus', 'Released benchmark — no'],
        ['Schematic geometry', 'design only', 'Human model — none'],
        ['Declared reference', 'r.baseline-0 (experimental)', 'Measured data — absent'],
        ['No evidence', 'not assessed', 'Failed validation — never implied'],
      ];

  return (
    <div className="grid h-full min-h-0 gap-3 overflow-hidden lg:grid-cols-[minmax(380px,1fr)_minmax(320px,0.9fr)]" data-testid="evidence">
      <section className="flex min-h-0 flex-col rounded-md border border-line bg-panel" aria-label="Provenance ledger">
        <header className="panel-h">Provenance ledger <span className="ml-auto normal-case tracking-normal font-normal text-ink-3">source → plan → admission → execution → native → canonical → assessment → claim</span></header>
        <ol className="scroll-thin m-0 min-h-0 flex-1 list-none overflow-auto p-2" role="listbox" aria-label="Evidence stages">
          {stages.map((st, i) => {
            const on = focus.id === st.id;
            return (
              <li key={st.id} className="relative pl-6">
                <span className="absolute left-[9px] top-0 h-full w-px bg-line" aria-hidden />
                <span className={`absolute left-[4px] top-[13px] h-[11px] w-[11px] rounded-full border-2 ${st.tag === 'QUALIFIED' || st.tag === 'AUTHORITY' ? 'border-ok bg-ok-soft' : st.tag === 'NOT_IMPLEMENTED' ? 'border-line-2 bg-panel' : st.tag === 'NOT_ASSESSED' ? 'border-dashed border-ink-3 bg-panel' : 'border-design bg-design-soft'}`} aria-hidden />
                <button role="option" aria-selected={on} className={`mb-1 w-full rounded border px-2.5 py-1.5 text-left ${on ? 'border-sel bg-accent-soft' : 'border-transparent hover:border-line hover:bg-panel-2'}`} onClick={() => d({ type: 'evidenceFocus', id: st.id })} data-testid={`stage-${st.id}`}>
                  <div className="flex items-center gap-2"><span className="sec-h">{i + 1}. {st.layer}</span><span className="ml-auto"><Tag tag={st.tag}>{st.tagText}</Tag></span></div>
                  <div className="text-[12.5px] font-medium text-ink">{st.title}</div>
                  <div className="text-[11.5px] text-ink-3">{st.status}{st.dep ? ` · ${st.dep}` : ''}</div>
                </button>
              </li>
            );
          })}
        </ol>
      </section>
      <div className="scroll-thin grid min-h-0 content-start gap-3 overflow-auto">
        <section className="rounded-md border border-line bg-panel" aria-label="Stage detail">
          <header className="panel-h">{focus.layer} <span className="ml-auto"><Tag tag={focus.tag}>{focus.tagText}</Tag></span></header>
          <div className="p-3 text-[12.5px] text-ink-2" data-testid="stage-detail">
            <h3 className="m-0 mb-1.5 text-[14px] font-semibold text-ink">{focus.title}</h3>
            {focus.detail}
          </div>
        </section>
        <section className="rounded-md border border-line bg-panel" aria-label="Distinctions kept separate">
          <header className="panel-h">Distinctions kept separate</header>
          <table className="data wrap left">
            <thead><tr><th>This</th><th style={{ textAlign: 'left' }}>Current state</th><th style={{ textAlign: 'left' }}>…is never read as</th></tr></thead>
            <tbody>{distinctions.map(([a, b, c]) => <tr key={a}><td style={{ whiteSpace: 'normal' }}>{a}</td><td style={{ textAlign: 'left', whiteSpace: 'normal' }}>{b}</td><td style={{ textAlign: 'left', whiteSpace: 'normal' }} className="text-ink-3">{c}</td></tr>)}</tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
