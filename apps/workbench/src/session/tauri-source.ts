/**
 * The Tauri session adapter — the only frontend module that imports `@tauri-apps/api`.
 *
 * Two IPC facts cross this boundary, and they are asymmetric on purpose:
 *
 * * the **command** `get_api_session` returns one atomic bootstrap: the current lifecycle
 *   snapshot with the credential beside it, captured together by the shell so a torn answer
 *   is not representable;
 * * the **event** `dynamisbench-api-status` announces lifecycle changes and carries no
 *   credential at all — its payload type has no such field.
 *
 * That asymmetry is why a `ready` event is not a session. It is a signal to re-invoke the
 * command, which is the only way a credential ever arrives, and which arrives as one value.
 *
 * ## Ordering
 *
 * Three properties the frontend must hold, and how they are held:
 *
 * 1. **The listener is registered before the first bootstrap read.** A transition between a
 *    read and a registration would be one the workbench never hears about, so `listen`
 *    resolves first and the initial `refresh` starts after it. Events that arrive during the
 *    registration window cannot be missed either: registration happens before any read whose
 *    answer they could invalidate.
 * 2. **A non-ready event drops the previous credential immediately.** The event's own state
 *    is published synchronously — so a dead sidecar's session stops existing at that moment —
 *    and only then is the bridge asked to reconcile.
 * 3. **A bootstrap read whose answer was invalidated by a later event is never published.**
 *    Reads are serialized (one invoke in flight, later requests coalesced into one re-read)
 *    and every read records the event generation it began at; if the generation moved before
 *    the answer arrived, the answer describes a state the workbench already knows is
 *    superseded, so it is discarded and the read is repeated. Without that check, the answer
 *    to an in-flight read could land after a newer non-ready event and republish a session
 *    that had already ended — a stale credential, presented as current.
 *
 * Cleanup is one function: it detaches the listener (or hands the still-registering listener
 * to a continuation that will detach it), and stops any later publication.
 */

import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import type { SessionListener, SessionSource } from "./source";
import { refineDesktopSession, refineDesktopSnapshot, type WorkbenchSession } from "./types";

/** The one lifecycle event the desktop shell emits. */
export const API_STATUS_EVENT = "dynamisbench-api-status";

/** The one command the desktop shell exposes. */
export const API_SESSION_COMMAND = "get_api_session";

export { isTauri };

/** A desktop failure this adapter reports when the bridge itself answered nothing. */
const BRIDGE_FAILURE: WorkbenchSession = {
  phase: "failed",
  failure: null,
  restartRequired: false,
};

/**
 * The Tauri-backed source.
 *
 * Constructed only when `isTauri()` says a runtime is present; the browser source sits
 * beside it in `source.ts` and shares nothing with it.
 */
export function tauriSessionSource(): SessionSource {
  return {
    kind: "tauri",

    start(listener: SessionListener): () => void {
      let disposed = false;
      let unlisten: (() => void) | null = null;

      /** How many lifecycle events have arrived; a read is only current if this is still. */
      let eventGeneration = 0;
      let reading = false;
      let rereadRequested = false;

      const publish = (session: WorkbenchSession) => {
        if (!disposed) {
          listener(session);
        }
      };

      /**
       * One bootstrap read, serialized against every other.
       *
       * Overlapping calls coalesce into a single re-read rather than a second in-flight
       * invoke, and a read whose generation was invalidated is discarded and repeated, so
       * the only answers ever published are answers read after the last known event.
       */
      const refresh = async (): Promise<void> => {
        if (disposed) {
          return;
        }

        if (reading) {
          rereadRequested = true;
          return;
        }

        reading = true;
        try {
          do {
            rereadRequested = false;
            const generation = eventGeneration;

            let response: unknown;
            try {
              response = await invoke(API_SESSION_COMMAND);
            } catch {
              // The bridge answered nothing. There is no session to report, and no
              // credential can be inferred, so the failure is reported as one.
              publish(BRIDGE_FAILURE);
              return;
            }

            if (generation !== eventGeneration) {
              // A lifecycle event arrived while this read was in flight, so this answer
              // describes a state the workbench already knows has moved on. Reading it out
              // loud could republish a session that has since ended.
              rereadRequested = true;
              continue;
            }

            publish(refineDesktopSession(response));
          } while (rereadRequested && !disposed);
        } finally {
          reading = false;
        }
      };

      const onLifecycleEvent = (payload: unknown) => {
        eventGeneration += 1;

        // A non-ready transition is published from the event itself, before the bridge is
        // asked anything: whatever credential the previous session held is dropped here, at
        // this instant, rather than after a round trip. A ready event publishes nothing —
        // it carries no credential — and reconciliation is the read below.
        const announced = refineDesktopSnapshot(payload);
        if (announced !== null) {
          publish(announced);
        }

        void refresh();
      };

      const subscribe = async (): Promise<void> => {
        let stop: () => void;
        try {
          stop = await listen(API_STATUS_EVENT, (event) => {
            onLifecycleEvent(event.payload);
          });
        } catch {
          publish(BRIDGE_FAILURE);
          return;
        }

        if (disposed) {
          stop();
          return;
        }

        unlisten = stop;
        await refresh();
      };

      void subscribe();

      return () => {
        disposed = true;
        const stop = unlisten;
        unlisten = null;
        if (stop !== null) {
          stop();
        }
      };
    },
  };
}
