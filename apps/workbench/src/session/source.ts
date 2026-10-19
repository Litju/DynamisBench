/**
 * The session boundary: where the workbench's session state comes from, as an abstraction.
 *
 * Components never call Tauri. They consume [`SessionSource`] through the provider in
 * `provider.tsx`, and the two sources behind that abstraction are a browser that has no
 * desktop shell at all and the Tauri adapter that does. Keeping the interface here — rather
 * than letting React components reach for `invoke` — is what makes the workbench's own tests
 * browser-only and what keeps desktop IPC session plumbing instead of a second, parallel way
 * to read the application.
 *
 * This module does not import `@tauri-apps/api`. The one module that does is
 * `tauri-source.ts`, and the structural gate in `src/test/boundaries.test.ts` fails if a
 * second one appears.
 */

import { isTauri, tauriSessionSource } from "./tauri-source";
import type { WorkbenchSession } from "./types";

/** Receives every session state the source publishes, in the order the source decided. */
export type SessionListener = (session: WorkbenchSession) => void;

/**
 * A source of session state: one subscription, and the disposal that ends it.
 *
 * `start` returns the cleanup rather than requiring a separate `stop`, so a caller that
 * mounts and unmounts cannot forget half of the pair. The published state is the refined
 * vocabulary, never a raw bridge response.
 */
export interface SessionSource {
  /** Which execution this source describes. `browser` means no desktop shell is present. */
  readonly kind: "browser" | "tauri";

  /**
   * Begin publishing session state to `listener`.
   *
   * The listener may be called synchronously during `start` and is called again on every
   * later transition. The returned function detaches the listener and releases whatever the
   * source acquired to produce it.
   */
  start(listener: SessionListener): () => void;
}

/**
 * The source for a browser with no desktop shell: one state, and nothing to do.
 *
 * A normal browser must render the workbench safely, so this source publishes exactly the
 * state that says so and acquires nothing: no IPC, no listener, no credential, no failure
 * to report.
 */
export function browserSessionSource(): SessionSource {
  return {
    kind: "browser",
    start(listener) {
      listener({ phase: "unavailable" });
      return () => {};
    },
  };
}

/**
 * The source this runtime should use: the desktop adapter inside the Tauri shell, the
 * browser source anywhere else.
 *
 * `isTauri()` is asked once, here, when the application's source is constructed — not inside
 * components and not per render — so exactly one decision selects the source and the rest of
 * the tree only ever sees session state.
 */
export function defaultSessionSource(): SessionSource {
  return isTauri() ? tauriSessionSource() : browserSessionSource();
}
