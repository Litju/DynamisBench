/**
 * The React binding for the session boundary, the typed client, and the query cache.
 *
 * The provider owns the *application's* session for the lifetime of the runtime. It
 * constructs the source (or accepts one, so tests can drive the lifecycle without a Tauri
 * runtime) and subscribes once. From that state it derives the two things the rest of the
 * tree needs: a ready session, and — only while ready — a typed API client.
 *
 * ## Why the cache is discarded here
 *
 * Cache ownership and session ownership are the same fact stated twice: data read from one
 * sidecar session must not survive into the next one, and data read through a credential
 * that no longer exists must not be presented as current. So the subscription compares the
 * incoming state with the one it is replacing, and every change other than "the same session
 * re-read" discards the whole cache *before* React renders the new session. A component
 * therefore cannot observe the previous session's data as if it belonged to the new one,
 * which an effect running after paint could not promise.
 *
 * ## The credential
 *
 * The credential lives exactly here: inside a `ReadyApiSession` in React state, and inside
 * the client built from it, in memory, for as long as the session that owns it is ready. It
 * is not written anywhere, not included in a query key, not rendered, and not part of this
 * provider's public surface except as a field of a ready session.
 */

import type { QueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { createApiClient, type ApiClient } from "../api/client";
import { discardServerState } from "../api/queries";
import { defaultSessionSource, type SessionSource } from "./source";
import { sessionsMatch, type ReadyApiSession, type WorkbenchSession } from "./types";

/**
 * What components can read about the session.
 *
 * `ready` and `session` say the same thing two ways on purpose: most components branch on
 * "is there an API to call", and the ones that render the lifecycle need the state that has
 * no API behind it.
 */
export type SessionContextValue = {
  readonly session: WorkbenchSession;
  readonly ready: ReadyApiSession | null;
  readonly client: ApiClient | null;
  readonly source: SessionSource["kind"];
};

const SessionContext = createContext<SessionContextValue | null>(null);

/** The state to render before the source has published anything. */
function initialSession(source: SessionSource): WorkbenchSession {
  return source.kind === "tauri"
    ? { phase: "starting" }
    : // A browser has no session to wait for. Starting from `unavailable` means the safe
      // state is also the first one rendered, not a transition into it.
      { phase: "unavailable" };
}

export function SessionProvider({
  queryClient,
  source,
  children,
}: {
  /** The runtime's one QueryClient, whose cache follows the session's lifetime. */
  queryClient: QueryClient;
  /** The session source. Omitted for the runtime's own choice of desktop or browser. */
  source?: SessionSource;
  children: ReactNode;
}) {
  const resolvedSource = useMemo(() => source ?? defaultSessionSource(), [source]);
  const [session, setSession] = useState<WorkbenchSession>(() => initialSession(resolvedSource));

  // The state the last publication left behind. A ref rather than the state value, because
  // the decision to discard the cache has to be taken at the moment the session changes —
  // before React renders the new one — and a state updater is not a place for a side effect.
  const current = useRef(session);

  useEffect(() => {
    const stop = resolvedSource.start((next) => {
      const previous = current.current;
      if (sessionsMatch(previous, next)) {
        return;
      }

      current.current = next;
      discardServerState(queryClient);
      setSession(next);
    });

    return stop;
  }, [resolvedSource, queryClient]);

  const value = useMemo<SessionContextValue>(
    () => ({
      session,
      ready: session.phase === "ready" ? session.api : null,
      client: session.phase === "ready" ? createApiClient(session.api) : null,
      source: resolvedSource.kind,
    }),
    [session, resolvedSource.kind],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/**
 * The current session.
 *
 * Throws outside a provider: a component that renders runtime state without one has no
 * session to render, and silently reporting `unavailable` would be a lie about a desktop
 * whose session exists.
 */
export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession must be used inside a SessionProvider.");
  }
  return value;
}

/**
 * The typed API client for the current ready session, or `null`.
 *
 * The shape most components want: they call an API method or they render the state that says
 * there is no API to call.
 */
export function useApiClient(): ApiClient | null {
  return useSession().client;
}
