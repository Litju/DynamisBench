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
  assertSidecarNotServing,
  containedError,
  createWorkspaceFixture,
  diagnosticMessage,
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

/** Test-only failure-injection seam around the same ordered lifecycle the fixture uses. */
export interface HarnessLifecycle {
  readonly startSidecar: () => Promise<SidecarSession>;
  readonly createWorkspace: () => Promise<WorkspaceFixture>;
  readonly installBridge: (
    page: Page,
    initial: PlaywrightBootstrap | null,
  ) => Promise<void>;
  readonly navigate: (page: Page) => Promise<void>;
  readonly awaitReady: (page: Page) => Promise<void>;
  readonly closePage: (page: Page) => Promise<void>;
  readonly stopSidecar: (sidecar: SidecarSession) => Promise<void>;
  readonly killSidecar: (sidecar: SidecarSession) => Promise<void>;
  readonly verifySidecar: (sidecar: SidecarSession) => Promise<void>;
  readonly disposeWorkspace: (workspace: WorkspaceFixture) => Promise<void>;
}

const NO_PRIMARY_FAILURE = Symbol("no primary failure");

/** Run acquisition, the test body and independent cleanup with one fail-closed outcome. */
export async function runHarness(
  page: Page,
  use: (harness: Harness) => Promise<void>,
  overrides: Partial<HarnessLifecycle> = {},
): Promise<void> {
  const lifecycle: HarnessLifecycle = {
    startSidecar,
    createWorkspace: createWorkspaceFixture,
    installBridge,
    navigate: async (current) => {
      await current.goto("/");
    },
    awaitReady: async (current) => {
      await expect(current.locator('[data-runtime-state="ready"]').first()).toBeVisible();
    },
    closePage: async (current) => {
      if (!current.isClosed()) {
        await current.close();
      }
    },
    stopSidecar: async (sidecar) => {
      await sidecar.stop();
    },
    killSidecar: async (sidecar) => {
      await sidecar.kill();
    },
    verifySidecar: assertSidecarNotServing,
    disposeWorkspace: async (workspace) => {
      await workspace.dispose();
    },
    ...overrides,
  };

  let sidecar: SidecarSession | undefined;
  let workspace: WorkspaceFixture | undefined;
  let primary: unknown = NO_PRIMARY_FAILURE;
  const cleanupFailures: Error[] = [];
  const credentials = () => (sidecar === undefined ? [] : [sidecar.credential]);
  const attempt = async (stage: string, operation: () => Promise<void>) => {
    try {
      await operation();
    } catch (error) {
      cleanupFailures.push(
        new Error(`${stage}: ${diagnosticMessage(error, credentials())}`),
      );
    }
  };

  try {
    sidecar = await lifecycle.startSidecar();
    workspace = await lifecycle.createWorkspace();
    await lifecycle.installBridge(page, sidecar.bootstrap());
    await lifecycle.navigate(page);
    await lifecycle.awaitReady(page);
    await use({ sidecar, workspace });
  } catch (error) {
    primary = error;
  } finally {
    let closeFailed = false;
    await attempt("page close", async () => {
      try {
        await lifecycle.closePage(page);
      } catch (error) {
        closeFailed = true;
        throw error;
      }
    });
    if (closeFailed && !page.isClosed()) {
      await attempt("browser context close", () => page.context().close());
    }

    if (sidecar !== undefined) {
      const session = sidecar;
      let stopFailed = false;
      await attempt("sidecar stop", async () => {
        try {
          await lifecycle.stopSidecar(session);
        } catch (error) {
          stopFailed = true;
          throw error;
        }
      });
      if (stopFailed) {
        await attempt("forced sidecar containment", () => lifecycle.killSidecar(session));
      }
      await attempt("sidecar listener verification", () => lifecycle.verifySidecar(session));
    }

    if (workspace !== undefined) {
      const roots = workspace;
      await attempt("workspace cleanup", () => lifecycle.disposeWorkspace(roots));
    }
  }

  if (primary !== NO_PRIMARY_FAILURE) {
    throw containedError(primary, cleanupFailures, credentials());
  }
  if (cleanupFailures.length > 0) {
    const [first, ...remaining] = cleanupFailures;
    throw containedError(first, remaining, credentials());
  }
}

export const test = base.extend<{ harness: Harness; network: { readonly offenses: readonly string[] } }>({
  harness: async ({ page, network }, use) => {
    void network;
    await runHarness(page, use);
  },

  network: async ({ page }, use) => {
    const guard = await confineNetwork(page);
    await use(guard);
  },
});

/** A page with no test bridge: the production browser source must report unavailable. */
export const browserOnlyTest = base;
