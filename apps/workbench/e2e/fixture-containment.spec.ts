/**
 * Fail-closed qualification for Playwright fixture acquisition, the test body and teardown.
 * Every scenario uses the real sidecar/workspace lifecycle unless the named stage is injected.
 */

import { once } from "node:events";
import { existsSync } from "node:fs";
import { readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import {
  runHarness,
  type HarnessLifecycle,
} from "./support/fixtures";
import {
  apiIsServing,
  assertSidecarNotServing,
  createWorkspaceFixture,
  startSidecar,
  type SidecarSession,
  type WorkspaceFixture,
} from "./support/sidecar";

interface Capture {
  sidecar?: SidecarSession;
  workspace?: WorkspaceFixture;
  createdRoot?: string;
}

async function rejectionOf(promise: Promise<unknown>): Promise<Error> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    return error as Error;
  }
  throw new Error("the operation was expected to reject");
}

async function temporaryWorkspaces(): Promise<Set<string>> {
  return new Set(
    (await readdir(tmpdir())).filter((name) => name.startsWith("dynamisbench-e2e-")),
  );
}

function capturedLifecycle(capture: Capture): Partial<HarnessLifecycle> {
  return {
    startSidecar: async () => {
      const sidecar = await startSidecar();
      capture.sidecar = sidecar;
      return sidecar;
    },
    createWorkspace: async () => {
      const workspace = await createWorkspaceFixture();
      capture.workspace = workspace;
      return workspace;
    },
  };
}

function processExists(pid: number | undefined): boolean {
  if (pid === undefined) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function expectContained(
  page: Page,
  capture: Capture,
  before: Set<string>,
): Promise<void> {
  expect(page.isClosed()).toBe(true);
  const sidecar = capture.sidecar;
  expect(sidecar).toBeDefined();
  if (sidecar === undefined) {
    return;
  }
  expect(processExists(sidecar.process.pid)).toBe(false);
  expect(await apiIsServing(sidecar.port)).toBe(false);

  const workspace = capture.workspace;
  if (workspace !== undefined) {
    expect(existsSync(path.dirname(workspace.sourceRoot))).toBe(false);
  }
  if (capture.createdRoot !== undefined) {
    expect(existsSync(capture.createdRoot)).toBe(false);
  }
  const after = await temporaryWorkspaces();
  expect([...after].filter((name) => !before.has(name))).toEqual([]);
}

/** Last-resort test cleanup; the assertions must prove runHarness already contained everything. */
async function backupCleanup(page: Page, capture: Capture): Promise<void> {
  if (!page.isClosed()) {
    await page.context().close().catch(() => undefined);
  }
  if (capture.sidecar !== undefined) {
    await capture.sidecar.kill().catch(() => undefined);
  }
  if (capture.workspace !== undefined) {
    await capture.workspace.dispose().catch(() => undefined);
  }
  if (capture.createdRoot !== undefined) {
    await rm(capture.createdRoot, { recursive: true, force: true }).catch(() => undefined);
  }
}

test("harness: sidecar acquisition failure closes the page without a workspace", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    const error = await rejectionOf(
      runHarness(page, async () => undefined, {
        ...capturedLifecycle(capture),
        startSidecar: async () => { throw new Error("injected sidecar acquisition failure"); },
      }),
    );

    expect(error.message).toContain("injected sidecar acquisition failure");
    expect(page.isClosed()).toBe(true);
    expect(capture.sidecar).toBeUndefined();
    expect(capture.workspace).toBeUndefined();
    const after = await temporaryWorkspaces();
    expect([...after].filter((name) => !before.has(name))).toEqual([]);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: workspace setup failure after sidecar startup is contained", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    let bodyRan = false;
    const error = await rejectionOf(
      runHarness(
        page,
        async () => { bodyRan = true; },
        {
          ...capturedLifecycle(capture),
          createWorkspace: () => createWorkspaceFixture({
            afterRootCreated: (root) => {
              capture.createdRoot = root;
              expect(existsSync(root)).toBe(true);
              throw new Error("injected workspace setup failure");
            },
          }),
        },
      ),
    );

    expect(bodyRan).toBe(false);
    expect(error.message).toContain("injected workspace setup failure");
    expect(capture.createdRoot).toBeDefined();
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: browser bridge initialization failure releases every resource", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    const error = await rejectionOf(
      runHarness(page, async () => undefined, {
        ...capturedLifecycle(capture),
        installBridge: async () => { throw new Error("injected browser initialization failure"); },
      }),
    );

    expect(error.message).toContain("injected browser initialization failure");
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

for (const stage of ["navigation", "readiness"] as const) {
  test(`harness: initial ${stage} failure releases every resource`, async ({ page }) => {
    const capture: Capture = {};
    const before = await temporaryWorkspaces();
    try {
      const injected = stage === "navigation"
        ? { navigate: async () => { throw new Error("injected navigation failure"); } }
        : { awaitReady: async () => { throw new Error("injected readiness failure"); } };
      const error = await rejectionOf(
        runHarness(page, async () => undefined, {
          ...capturedLifecycle(capture),
          ...injected,
        }),
      );

      expect(error.message).toContain(`injected ${stage} failure`);
      await expectContained(page, capture, before);
    } finally {
      await backupCleanup(page, capture);
    }
  });
}

test("harness: test-body failure remains primary and its diagnostics are sanitized", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    const error = await rejectionOf(
      runHarness(
        page,
        async ({ sidecar, workspace }) => {
          throw new Error(
            `injected body failure ${sidecar.credential} ${path.dirname(workspace.sourceRoot)}`,
          );
        },
        capturedLifecycle(capture),
      ),
    );

    const sidecar = capture.sidecar;
    const workspace = capture.workspace;
    expect(sidecar).toBeDefined();
    expect(workspace).toBeDefined();
    expect(error.message).toContain("injected body failure");
    expect(sidecar === undefined || error.message.includes(sidecar.credential)).toBe(false);
    expect(
      workspace === undefined || error.message.includes(path.dirname(workspace.sourceRoot)),
    ).toBe(false);
    expect(error.message).not.toContain("containment also failed");
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: a page-close exception cannot prevent sidecar or workspace cleanup", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    const error = await rejectionOf(
      runHarness(page, async () => undefined, {
        ...capturedLifecycle(capture),
        closePage: async () => { throw new Error("injected page close failure"); },
      }),
    );

    expect(error.message).toContain("injected page close failure");
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: a stop exception falls back to forced containment and workspace cleanup", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    const error = await rejectionOf(
      runHarness(page, async () => undefined, {
        ...capturedLifecycle(capture),
        stopSidecar: async () => { throw new Error("injected sidecar stop failure"); },
      }),
    );

    expect(error.message).toContain("injected sidecar stop failure");
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: a listener verification failure forces containment and is verified again", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  let verifications = 0;
  let forcedKills = 0;
  try {
    const error = await rejectionOf(
      runHarness(page, async () => undefined, {
        ...capturedLifecycle(capture),
        killSidecar: async (sidecar) => {
          forcedKills += 1;
          await sidecar.kill();
        },
        verifySidecar: async (sidecar) => {
          verifications += 1;
          if (verifications === 1) {
            throw new Error("injected listener verification failure");
          }
          await assertSidecarNotServing(sidecar);
        },
      }),
    );

    expect(error.message).toContain("injected listener verification failure");
    expect(forcedKills).toBe(1);
    expect(verifications).toBe(2);
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: cleanup failure never replaces the original test-body failure", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    const error = await rejectionOf(
      runHarness(
        page,
        async () => { throw new Error("primary test-body failure"); },
        {
          ...capturedLifecycle(capture),
          closePage: async (current) => {
            await current.close();
            throw new Error("injected cleanup failure");
          },
        },
      ),
    );

    expect(error.message.startsWith("primary test-body failure")).toBe(true);
    expect(error.message).toContain("containment also failed: page close");
    expect(error.message).toContain("injected cleanup failure");
    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: repeated page, sidecar and workspace cleanup is idempotent", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    await runHarness(page, async () => undefined, capturedLifecycle(capture));
    const sidecar = capture.sidecar;
    const workspace = capture.workspace;
    expect(sidecar).toBeDefined();
    expect(workspace).toBeDefined();
    if (sidecar === undefined || workspace === undefined) {
      return;
    }

    await page.close();
    await page.close();
    await sidecar.stop();
    await sidecar.stop();
    await sidecar.kill();
    await sidecar.kill();
    await workspace.dispose();
    await workspace.dispose();

    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});

test("harness: unexpected child termination still releases the page and workspace", async ({ page }) => {
  const capture: Capture = {};
  const before = await temporaryWorkspaces();
  try {
    await runHarness(
      page,
      async ({ sidecar }) => {
        const exited = once(sidecar.process, "exit");
        sidecar.process.kill("SIGKILL");
        await exited;
      },
      capturedLifecycle(capture),
    );

    await expectContained(page, capture, before);
  } finally {
    await backupCleanup(page, capture);
  }
});
