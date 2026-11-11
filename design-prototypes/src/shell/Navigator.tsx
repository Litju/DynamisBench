import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { PENDULUM_RELEASE, LCMJ20, type SourceTag } from '../data/authority';
import { useModelEntities } from '../data/entities';
import { type Entity } from '../data/models';
import { SERIES_IDS, seriesById } from '../data/numerics';
import { STUDIES, useWB, type StudyId } from '../state';
import { Icon, LifecycleChip, Src, Tag } from '../ui/kit';

type Node = { id: string; label: string; sub?: string; icon: Parameters<typeof Icon>[0]['name']; tag?: SourceTag; parent?: string; muted?: boolean; extra?: React.ReactNode };

const KIND_ICON: Record<Entity['kind'], Node['icon']> = {
  model: 'model', group: 'chev', frame: 'frame', body: 'body', joint: 'joint', coordinate: 'dot', site: 'site', contact: 'contact', actuator: 'joint', sensor: 'sensor', solver: 'solver', quantity: 'q', empty: 'empty',
};

const SHORT: Partial<Record<SourceTag, string>> = { RECOMPUTED: 'calc', FIXTURE: 'fixture', DESIGN_ONLY: 'design', QUALIFIED: 'qualified', NOT_IMPLEMENTED: 'n/a', NOT_ASSESSED: 'n/a' };

export function Navigator({ onCollapse }: { onCollapse?: () => void }) {
  const { s, d } = useWB();
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ 'g.quant': true, 'g.hquant': true, 'g.sites': false, 'mbody.patella_r': true, 'mbody.patella_l': true });
  const isP = s.study === 'pendulum-qual';
  const st = STUDIES[s.study];
  const { entities, loading } = useModelEntities();

  const nodes: Node[] = useMemo(() => {
    const out: Node[] = [
      { id: 'grp.context', label: 'Study context', icon: 'study' },
      { id: 'ctx.benchmark', label: 'Benchmark', sub: st.benchmark, icon: 'ref', parent: 'grp.context', tag: st.tag },
      { id: 'ctx.scenario', label: 'Scenario', sub: st.scenario, icon: 'ref', parent: 'grp.context', tag: st.tag },
      { id: 'ctx.realization', label: 'Realization', sub: st.realization, icon: 'ref', parent: 'grp.context', tag: st.tag },
      { id: 'ctx.sut', label: 'System under test', sub: st.sut, icon: 'ref', parent: 'grp.context', tag: st.tag },
      { id: 'ctx.environment', label: 'Environment', sub: st.env, icon: 'ref', parent: 'grp.context', tag: st.tag },
    ];
    for (const e of entities) {
      out.push({ id: e.id, label: e.label, sub: e.sub, icon: KIND_ICON[e.kind], tag: e.kind === 'model' ? e.tag : undefined, parent: e.parent, muted: e.kind === 'empty' });
    }
    out.push({ id: 'grp.runs', label: 'Runs & series', icon: 'run' });
    if (isP) {
      for (const id of SERIES_IDS) {
        const ser = seriesById(id);
        out.push({ id: `series:${id}`, label: ser.label, icon: 'q', parent: 'grp.runs', tag: 'RECOMPUTED' });
      }
    }
    for (const r of s.runs.filter((r) => r.study === s.study)) {
      out.push({ id: `run:${r.id}`, label: r.id, icon: 'run', parent: 'grp.runs', extra: <LifecycleChip state={r.state} demo={false} /> });
    }
    if (!isP) out.push({ id: 'run:none', label: 'No trajectories', sub: 'no realization can execute', icon: 'empty', parent: 'grp.runs', muted: true });
    out.push({ id: 'grp.refs', label: 'References', icon: 'ref' });
    if (isP) out.push({ id: 'ref:r.reference.pendulum', label: PENDULUM_RELEASE.reference.label, sub: 'solution_verification · synthetic', icon: 'ref', parent: 'grp.refs', tag: 'AUTHORITY' });
    else out.push({ id: 'ref:r.baseline-0', label: 'r.baseline-0', sub: 'model_validation · experimental · no data', icon: 'ref', parent: 'grp.refs', tag: 'FIXTURE' });
    return out;
  }, [st, isP, s.runs, s.study, entities]);

  const childrenOf = useMemo(() => {
    const m = new Map<string | undefined, Node[]>();
    nodes.forEach((n) => m.set(n.parent, [...(m.get(n.parent) ?? []), n]));
    return m;
  }, [nodes]);

  const q = query.trim().toLowerCase();
  const matches = (n: Node): boolean => !q || n.label.toLowerCase().includes(q) || (n.sub ?? '').toLowerCase().includes(q) || (childrenOf.get(n.id) ?? []).some(matches);

  const visible: { n: Node; level: number; hasKids: boolean }[] = [];
  const walk = (parent: string | undefined, level: number) => {
    for (const n of childrenOf.get(parent) ?? []) {
      if (!matches(n)) continue;
      const kids = (childrenOf.get(n.id) ?? []).length > 0;
      visible.push({ n, level, hasKids: kids });
      if (kids && (q || !collapsed[n.id])) walk(n.id, level + 1);
    }
  };
  walk(undefined, 1);

  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const focusRow = (i: number) => { const v = visible[Math.max(0, Math.min(visible.length - 1, i))]; rowRefs.current[v.n.id]?.focus(); };
  const activate = (n: Node) => { if (!n.id.startsWith('grp.') && n.id !== 'run:none') d({ type: 'select', id: n.id }); };
  const onKey = (e: KeyboardEvent, i: number) => {
    const { n, hasKids } = visible[i];
    if (e.key === 'ArrowDown') { focusRow(i + 1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { focusRow(i - 1); e.preventDefault(); }
    else if (e.key === 'ArrowRight' && hasKids) { setCollapsed((c) => ({ ...c, [n.id]: false })); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { if (hasKids && !collapsed[n.id]) setCollapsed((c) => ({ ...c, [n.id]: true })); else if (n.parent) rowRefs.current[n.parent]?.focus(); e.preventDefault(); }
    else if (e.key === 'Enter' || e.key === ' ') { activate(n); e.preventDefault(); }
  };
  const selIndex = Math.max(0, visible.findIndex((v) => v.n.id === s.selection));

  return (
    <nav className="panel flex min-h-0 flex-col" aria-label="Scientific navigator">
      <header className="panel-h">Navigator{onCollapse && <button className="btn btn-ghost btn-icon ml-auto h-[22px] w-[22px]" onClick={onCollapse} aria-label="Collapse navigator" title="Collapse navigator ([)"><span style={{ transform: 'rotate(180deg)', display: 'inline-flex' }}><Icon name="chev" size={11} /></span></button>}</header>
      <div className="flex-none border-b border-line p-2">
        <label className="sec-h mb-1 block" htmlFor="study-select">Study</label>
        <select id="study-select" className="field w-full" value={s.study} onChange={(e) => d({ type: 'study', study: e.target.value as StudyId })}>
          {Object.entries(STUDIES).map(([id, v]) => <option key={id} value={id}>{v.label}</option>)}
        </select>
        <div className="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-ink-3">
          <Tag tag={st.tag} />
          <span className="truncate">{isP ? 'Qualified fixed reference (RES-550)' : `Fixture: ${LCMJ20.study.id}`}</span>
        </div>
        <div className="relative mt-2">
          <span className="pointer-events-none absolute left-2 top-[6px] text-ink-3"><Icon name="search" size={13} /></span>
          <input className="field w-full pl-7" placeholder="Filter bodies, joints, quantities…" aria-label="Filter model tree" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto px-1 py-1" role="tree" aria-label="Study and model tree">
        {visible.map(({ n, level, hasKids }, i) => {
          const selected = s.selection === n.id;
          const isGroup = n.id.startsWith('grp.') || n.id.startsWith('g.');
          return (
            <div
              key={n.id}
              ref={(el) => { rowRefs.current[n.id] = el; }}
              role="treeitem"
              aria-level={level}
              aria-selected={selected}
              aria-expanded={hasKids ? !collapsed[n.id] || !!q : undefined}
              tabIndex={i === selIndex ? 0 : -1}
              data-node={n.id}
              className={`tree-row ${s.hover === n.id ? 'is-hover' : ''} ${n.muted ? 'text-ink-3' : ''}`}
              style={{ paddingLeft: 4 + (level - 1) * 13 }}
              onClick={() => { activate(n); if (isGroup && hasKids) setCollapsed((c) => ({ ...c, [n.id]: !c[n.id] })); }}
              onMouseEnter={() => d({ type: 'hover', id: n.id })}
              onMouseLeave={() => d({ type: 'hover', id: null })}
              onKeyDown={(e) => onKey(e, i)}
            >
              <span
                className="flex w-3.5 justify-center text-ink-3"
                onClick={(e) => { if (hasKids) { e.stopPropagation(); setCollapsed((c) => ({ ...c, [n.id]: !c[n.id] })); } }}
              >
                {hasKids ? <Icon name={collapsed[n.id] && !q ? 'chev' : 'chev-d'} size={11} /> : null}
              </span>
              {!(isGroup && hasKids) && <span className={selected ? 'text-accent' : 'text-ink-3'}><Icon name={n.icon} size={13} /></span>}
              <span className={`${n.id.startsWith('ctx.') ? 'flex-none' : 'min-w-0 truncate'} ${isGroup ? 'sec-h text-ink-2' : 'text-[12.5px]'}`}>{n.label}</span>
              {n.sub && <span className="min-w-0 truncate text-[11px] text-ink-3">{n.sub}</span>}
              <span className="ml-auto flex items-center gap-1 pl-1">{n.extra}{n.tag && n.tag !== 'AUTHORITY' && !(n.id.startsWith('ctx.') && n.tag === 'FIXTURE') && <Src tag={n.tag} label={SHORT[n.tag]} />}</span>
            </div>
          );
        })}
        {loading && <div className="p-2 text-[11.5px] text-ink-3" role="status">Loading MyoSim reference model…</div>}
        {visible.length === 0 && <div className="p-3 text-[12px] text-ink-3" role="status">No model entity matches “{query}”.</div>}
      </div>
    </nav>
  );
}
