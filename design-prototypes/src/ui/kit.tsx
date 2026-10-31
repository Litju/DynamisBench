import type { ReactNode } from 'react';
import { TAG_INFO, type Lifecycle, type SourceTag } from '../data/authority';

export function Tag({ tag, children }: { tag: SourceTag; children?: ReactNode }) {
  const info = TAG_INFO[tag];
  return (
    <span className={`tag tag-${info.tone}`} title={info.text} data-tag={tag}>
      {children ?? info.label}
    </span>
  );
}

/** Compact provenance glyph: shape + colour + accessible name. Use inside dense rows; full Tag in headers. */
export function Src({ tag, label }: { tag: SourceTag; label?: string | false }) {
  const info = TAG_INFO[tag];
  return (
    <span className={`src src-${info.tone}`} title={`${info.label} — ${info.text}`} data-tag={tag}>
      <span className="src-g" aria-hidden />
      {label === false ? <span className="sr-only">{info.label}</span> : <span>{label ?? info.label}</span>}
    </span>
  );
}

export function SourceLegend() {
  return (
    <ul className="m-0 grid list-none gap-1.5 p-0">
      {(Object.keys(TAG_INFO) as SourceTag[]).map((k) => (
        <li key={k} className="grid grid-cols-[150px_1fr] items-start gap-2 text-[12px]">
          <Src tag={k} />
          <span className="text-ink-2">{TAG_INFO[k].text}</span>
        </li>
      ))}
    </ul>
  );
}

export function Panel({ title, right, children, className = '', bodyClass = '', id, label }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; id?: string; label?: string }) {
  return (
    <section className={`panel flex flex-col ${className}`} aria-label={label ?? (typeof title === 'string' ? title : undefined)} id={id}>
      {title !== undefined && (
        <header className="panel-h">
          <span className="truncate">{title}</span>
          <span className="ml-auto flex items-center gap-1.5 normal-case tracking-normal font-normal">{right}</span>
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Empty({ title, children, tag = 'NOT_IMPLEMENTED' as SourceTag, action }: { title: string; children?: ReactNode; tag?: SourceTag; action?: ReactNode }) {
  return (
    <div className="flex h-full min-h-[120px] items-center justify-center p-6" role="status">
      <div className="max-w-[460px] rounded-md border border-dashed border-line-2 bg-panel-2 px-5 py-4">
        <div className="mb-1.5 flex items-center gap-2">
          <Tag tag={tag} />
          <span className="font-semibold text-ink">{title}</span>
        </div>
        <div className="text-[12.5px] text-ink-2">{children}</div>
        {action && <div className="mt-3">{action}</div>}
      </div>
    </div>
  );
}

const LC: Record<Lifecycle, { color: string; label: string }> = {
  draft: { color: 'var(--color-ink-4)', label: 'Draft' },
  preflight_ready: { color: 'var(--color-accent)', label: 'Preflight ready' },
  refused: { color: 'var(--color-err)', label: 'Refused' },
  starting: { color: 'var(--color-accent)', label: 'Starting' },
  running: { color: 'var(--color-accent)', label: 'Running' },
  canceling: { color: 'var(--color-warn)', label: 'Canceling' },
  canceled: { color: 'var(--color-warn)', label: 'Canceled' },
  timed_out: { color: 'var(--color-err)', label: 'Timed out' },
  failed: { color: 'var(--color-err)', label: 'Failed' },
  completed: { color: 'var(--color-ok)', label: 'Process completed' },
};

export function LifecycleChip({ state, demo = true }: { state: Lifecycle; demo?: boolean }) {
  const c = LC[state];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px]" data-lifecycle={state}>
      <span className="state-dot" style={{ background: c.color, boxShadow: state === 'running' || state === 'starting' ? `0 0 0 3px color-mix(in srgb, ${c.color} 22%, transparent)` : undefined }} />
      <span style={{ color: c.color }} className="font-semibold">{c.label}</span>
      {demo && <span className="text-ink-3">(design demo)</span>}
    </span>
  );
}

export function Unit({ children }: { children: ReactNode }) {
  return <span className="ml-1 text-[11px] text-ink-3">{children}</span>;
}

export function fmt(v: number, digits = 4) {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(2);
  return v.toFixed(digits);
}

export function Icon({ name, size = 14 }: { name: 'play' | 'pause' | 'step-b' | 'step-f' | 'start' | 'end' | 'reset' | 'search' | 'chev' | 'chev-d' | 'dot' | 'body' | 'joint' | 'frame' | 'site' | 'solver' | 'q' | 'contact' | 'sensor' | 'empty' | 'model' | 'run' | 'ref' | 'study' | 'stop' | 'loop' | 'panel'; size?: number }) {
  const p: Record<string, ReactNode> = {
    play: <path d="M4 3l9 5-9 5z" fill="currentColor" />,
    pause: <path d="M4 3h3v10H4zM9 3h3v10H9z" fill="currentColor" />,
    'step-b': <path d="M4 3h1.5v10H4zM13 3v10L6 8z" fill="currentColor" />,
    'step-f': <path d="M10.5 3H12v10h-1.5zM3 3v10l7-5z" fill="currentColor" />,
    start: <path d="M3 3h1.5v10H3zM9 3v10L4.5 8zM14 3v10L9.5 8z" fill="currentColor" />,
    end: <path d="M11.5 3H13v10h-1.5zM2 3v10l4.5-5zM7 3v10l4.5-5z" fill="currentColor" />,
    reset: <path d="M8 3a5 5 0 1 1-4.6 3M3 2v4h4" fill="none" stroke="currentColor" strokeWidth="1.5" />,
    search: <path d="M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9zM10.5 10.5L14 14" fill="none" stroke="currentColor" strokeWidth="1.5" />,
    chev: <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" />,
    'chev-d': <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />,
    dot: <circle cx="8" cy="8" r="2" fill="currentColor" />,
    body: <rect x="3.5" y="3.5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />,
    joint: <g fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="2.5" /><path d="M8 1.5v4M8 10.5v4" /></g>,
    frame: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M3 13V3M3 13h10" /><path d="M3 13l5-5" strokeDasharray="1.5 1.5" /></g>,
    site: <g fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="4" /><circle cx="8" cy="8" r="1" fill="currentColor" /></g>,
    solver: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2 12c2-6 4-8 6-4s4 2 6-4" /></g>,
    q: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2 12h12M4 12V7M8 12V4M12 12V9" /></g>,
    contact: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2 12h12" /><circle cx="8" cy="8" r="3" /></g>,
    sensor: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M8 3v10M4 7l4-4 4 4" /></g>,
    empty: <circle cx="8" cy="8" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2 2" />,
    model: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M8 2l5.5 3v6L8 14l-5.5-3V5z" /><path d="M8 8l5.5-3M8 8v6M8 8L2.5 5" /></g>,
    run: <g fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="8" cy="8" r="5.5" /><path d="M7 5.5l3 2.5-3 2.5z" fill="currentColor" /></g>,
    ref: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M4 2.5h6l2.5 2.5v8.5H4z" /><path d="M6 8h4M6 10.5h4" /></g>,
    study: <g fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2.5 4h4l1.5 1.5h5.5v7h-11z" /></g>,
    stop: <rect x="4" y="4" width="8" height="8" fill="currentColor" />,
    loop: <path d="M4 6h7l-2-2M12 10H5l2 2" fill="none" stroke="currentColor" strokeWidth="1.5" />,
    panel: <g fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="2" y="3" width="12" height="10" rx="1" /><path d="M2 9.5h12" /></g>,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="flex-none">
      {p[name]}
    </svg>
  );
}
