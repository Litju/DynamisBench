/**
 * The bottom Activity panel: a bounded, session-volatile place for application events.
 *
 * The panel is status only. It is not an event store, not a second copy of workspace state,
 * and not an authority cache: the transport that fills it arrives with the SSE client, and
 * this component owns the presentation and the empty state. Nothing here is persisted.
 */

export function ActivityPanel({ children }: { children?: React.ReactNode }) {
  return (
    <section
      aria-labelledby="activity-heading"
      className="border-t border-slate-200 bg-white px-4 py-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id="activity-heading" className="text-sm font-semibold text-slate-800">
          Activity
        </h2>
        <span className="text-xs text-slate-500">Transient application events</span>
      </div>
      <div className="mt-2 min-h-[3rem]" aria-live="polite">
        {children ?? (
          <p className="text-sm text-slate-500">
            No events yet. Activity describes application operations and is not persisted.
          </p>
        )}
      </div>
    </section>
  );
}
