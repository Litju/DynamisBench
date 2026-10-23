/**
 * The test-only session transport for Playwright.
 *
 * This module exists to let a Chromium browser drive the *production* route tree, typed
 * client, Query cache and session provider against a **real secured Python sidecar**. Tauri's
 * WebView2 cannot be attached to Playwright, so the one thing that is simulated is the two
 * IPC facts the desktop shell would supply: a lifecycle bootstrap (`get_api_session`) and
 * later lifecycle announcements.
 *
 * It is deliberately not reachable from `index.html`, `main.tsx`, `source.ts` or any module a
 * production build imports. The harness page is served only by `vite.e2e.config.ts`, which is
 * never used by `pnpm run build`, and the source below is selected only when a page has
 * installed an object whose `kind` is the marker this file reads. A normal browser therefore
 * still reaches the production `browserSessionSource` and reports `unavailable`; there is no
 * ready-session fallback anywhere in the production runtime.
 *
 * The emissions are *bootstrap responses*, not event payloads. The Tauri adapter's event →
 * re-read handshake is covered by its own unit suite; a browser test that also reproduced that
 * indirection would be testing a mock of the boundary under test rather than the boundary.
 */

import type { SessionListener, SessionSource } from "../../src/session/source";
import { refineDesktopSession, type WorkbenchSession } from "../../src/session/types";

/** The marker a Playwright `addInitScript` installs before the application boots. */
export const E2E_BRIDGE_KIND = "dynamisbench.playwright-test-bridge";

/** One full `get_api_session` response, as the desktop shell would publish it. */
export interface PlaywrightBootstrap {
  readonly status: "starting" | "ready" | "failed" | "stopped";
  readonly origin: string | null;
  readonly api_version: string | null;
  readonly protocol_version: number | null;
  readonly credential: string | null;
  readonly restart_required: boolean;
  readonly failure: string | null;
}

export interface PlaywrightBridge {
  readonly kind: typeof E2E_BRIDGE_KIND;
  readonly initial: PlaywrightBootstrap | null;
  /** Every emitted bootstrap, in order. Diagnostics for the harness, never authority. */
  readonly emissions: PlaywrightBootstrap[];
  listeners: Array<(payload: PlaywrightBootstrap) => void>;
  emit(payload: PlaywrightBootstrap): void;
}

declare global {
  interface Window {
    __dynamisbenchPlaywrightBridge?: PlaywrightBridge;
  }
}

/** Whether this page has installed the explicitly named browser-test transport. */
export function hasPlaywrightBridge(): boolean {
  return window.__dynamisbenchPlaywrightBridge?.kind === E2E_BRIDGE_KIND;
}

/** The initial session state the bridge supplies, or `starting` when it published none. */
function initialSession(bridge: PlaywrightBridge): WorkbenchSession {
  return bridge.initial === null
    ? { phase: "starting" }
    : refineDesktopSession(bridge.initial);
}

/**
 * A `SessionSource` over the injected bootstrap transport.
 *
 * It publishes the initial bootstrap synchronously, then one refined state per emission. This
 * is the same refinement the real Tauri adapter uses, so a malformed or non-ready record takes
 * the production path rather than a test-specific one.
 */
export function playwrightSessionSource(bridge: PlaywrightBridge): SessionSource {
  return {
    kind: "tauri",

    start(listener: SessionListener): () => void {
      const publish = (payload: PlaywrightBootstrap) => {
        listener(refineDesktopSession(payload));
      };
      bridge.listeners.push(publish);
      listener(initialSession(bridge));

      return () => {
        bridge.listeners = bridge.listeners.filter((entry) => entry !== publish);
      };
    },
  };
}
