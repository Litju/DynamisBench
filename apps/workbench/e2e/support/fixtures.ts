/**
 * Playwright fixtures: one real sidecar, one real workspace, and the browser-test transport.
 *
 * The fixture does four things before a test body runs, in this order:
 *
 * 1. starts the locked Python sidecar and waits for its readiness record;
 * 2. creates two real temporary roots with valid and invalid authority;
 * 3. installs the explicitly named browser-test bridge with a ready bootstrap;
 * 4. navigates the production route tree at `/`.
 *
 * Teardown always stops the sidecar and removes the roots, so a failed assertion cannot leave
 * a listener or a temporary workspace behind. Tests that need a second session start and stop
 * their own sidecar; this fixture never pretends a restart happened.
 */

import { expect, test as base, type Page } from "@playwright/test";

import type { PlaywrightBootstrap } from "../app/bridge";
import {
  createWorkspaceFixture,
  startSidecar,
  type SidecarSession,
  type WorkspaceFixture,
} from "./sidecar";

export const E2E_BRIDGE_KIND = "dynamisbench.playwright-test-bridge";

export interface Harness {
  readonly sidecar: SidecarSession;
  readonly workspace: WorkspaceFixture;
}

/** Install the browser-test bridge before any application module runs. */
export async function installBridge(
  page: Page,
  initial: PlaywrightBootstrap | null,
): Promise<void> {
  await page.addInitScript(
    ({ bridgeKind, payload }) => {
      const bridge = {
        kind: bridgeKind,
        initial: payload,
        emissions: [] as unknown[],
        listeners: [] as Array<(next: unknown) => void>,
        emit(next: unknown) {
          this.emissions.push(next);
          for (const listener of this.listeners) {
            listener(next);
          }
        },
      };
      (window as unknown as Record<string, unknown>).__dynamisbenchPlaywrightBridge = bridge;
    },
    { bridgeKind: E2E_BRIDGE_KIND, payload: initial },
  );
}

/** Publish one full bootstrap response, as a new desktop session generation. */
export async function emitSession(
  page: Page,
  bootstrap: PlaywrightBootstrap,
): Promise<void> {
  await page.evaluate((payload) => {
    const bridge = (
      window as unknown as {
        __dynamisbenchPlaywrightBridge?: { emit(next: unknown): void };
      }
    ).__dynamisbenchPlaywrightBridge;
    if (bridge === undefined) {
      throw new Error("the Playwright test bridge is not installed");
    }
    bridge.emit(payload);
  }, bootstrap);
}

/** Refuse every request whose host is not this machine, and collect the attempt. */
async function confineNetwork(page: Page): Promise<{ readonly offenses: readonly string[] }> {
  const offenses: string[] = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const local = url.hostname === "127.0.0.1" || url.hostname === "localhost";
    if (url.protocol.startsWith("http") && !local) {
      offenses.push(url.origin);
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  return { offenses };
}

export const test = base.extend<{ harness: Harness; network: { readonly offenses: readonly string[] } }>({
  harness: async ({ page, network }, use) => {
    void network;
    const sidecar = await startSidecar();
    const workspace = await createWorkspaceFixture();
    await installBridge(page, sidecar.bootstrap());
    await page.goto("/");
    await expect(page.locator('[data-runtime-state="ready"]').first()).toBeVisible();
    await use({ sidecar, workspace });
    // Closing the page aborts the browser's authenticated event stream, which is what lets
    // Uvicorn complete its own graceful shutdown instead of waiting on a live connection.
    await page.close();
    await sidecar.stop();
    await workspace.dispose();
  },

  network: async ({ page }, use) => {
    const guard = await confineNetwork(page);
    await use(guard);
  },
});

/** A page with no test bridge: the production browser source must report unavailable. */
export const browserOnlyTest = base;
