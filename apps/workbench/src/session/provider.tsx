/**
 * The React binding for the session boundary: one subscription, one context.
 *
 * The provider owns the *application's* session for the lifetime of the runtime. It
 * constructs the source (or accepts one, so tests can drive the lifecycle without a Tauri
 * runtime), subscribes once, and publishes the refined state. Components read it with
 * [`useSession`] and never touch IPC.
 *
 * The credential lives exactly here: inside a `ReadyApiSession` held in React state, in
 * memory, for as long as the session that owns it is ready. It is not in this provider's
 * public surface as anything but a field of a ready session, and nothing in this module
 * writes it anywhere.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { defaultSessionSource, type SessionSource } from "./source";
import {
  sessionsMatch,
  type ReadyApiSession,
  type WorkbenchSession,
} from "./types";

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
  source,
  children,
}: {
  /** The session source. Omitted for the runtime's own choice of desktop or browser. */
  source?: SessionSource;
  children: ReactNode;
}) {
  const resolvedSource = useMemo(() => source ?? defaultSessionSource(), [source]);
  const [session, setSession] = useState<WorkbenchSession>(() => initialSession(resolvedSource));

  useEffect(() => {
    const stop = resolvedSource.start((next) => {
      setSession((previous) => (sessionsMatch(previous, next) ? previous : next));
    });
    return stop;
  }, [resolvedSource]);

  const value = useMemo<SessionContextValue>(
    () => ({
      session,
      ready: session.phase === "ready" ? session.api : null,
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
