/**
 * The bottom Activity panel: a bounded, session-volatile view of application events.
 *
 * The panel is status only. It is not an event store, not a second copy of workspace state,
 * and not an authority cache: the SSE client fills it while a ready session is mounted, and
 * changing that session clears it. Nothing here is persisted, replayed or exported.
 */

import { useSession } from "../session/provider";
import { Badge } from "../ui/badge";
import {
  MAX_ACTIVITY_ENTRIES,
  useActivityFeed,
  type ActivityStreamState,
} from "./activity-feed";

export function ActivityPanel() {
  const { client } = useSession();
  const feed = useActivityFeed(client);

  return (
    <section
      aria-labelledby="activity-heading"
      className="border-t border-slate-200 bg-white px-4 py-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="activity-heading" className="text-sm font-semibold text-slate-800">
          Activity
        </h2>
        <div className="flex items-center gap-2">
          <StreamBadge state={feed.streamState} />
          <span className="text-xs text-slate-500">
            Transient application events · last {MAX_ACTIVITY_ENTRIES}
          </span>
        </div>
      </div>

      <div className="mt-2 min-h-[3rem]" aria-live="polite">
        {feed.entries.length === 0 ? (
          <p className="text-sm text-slate-500">{emptyText(feed.streamState)}</p>
        ) : (
          <ol className="max-h-32 space-y-1 overflow-y-auto text-sm">
            {feed.entries.map((entry) => (
              <li key={entry.id} className="flex min-w-0 items-baseline gap-2">
                <span className="text-xs text-slate-400">·</span>
                <span className="min-w-0 break-words text-slate-700">{entry.text}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function StreamBadge({ state }: { state: ActivityStreamState }) {
  const tone =
    state === "live"
      ? "ready"
      : state === "connecting" || state === "reconnecting"
        ? "pending"
        : state === "refused" || state === "unavailable"
          ? "danger"
          : "neutral";

  return <Badge tone={tone}>Events: {state}</Badge>;
}

function emptyText(state: ActivityStreamState): string {
  switch (state) {
    case "idle":
      return "No ready API session. Activity is unavailable in this runtime.";
    case "connecting":
      return "Connecting to the application event stream…";
    case "reconnecting":
      return "Reconnecting to the application event stream…";
    case "refused":
      return "The application refused the event stream for this session.";
    case "unavailable":
      return "The event stream is unavailable; this session made no further attempts.";
    case "live":
      return "Connected. Activity describes application operations and is not persisted.";
  }
}
