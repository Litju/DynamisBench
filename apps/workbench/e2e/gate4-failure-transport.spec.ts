/**
 * Gate 4: failure, replacement, reconnection, stale-response exclusion and Arrow IPC.
 *
 * The sidecar losses in this suite are real: the child is stopped through its own control
 * channel, its port stops serving, and the browser's next request fails against a dead socket.
 * The lifecycle announcement that follows is the one the desktop shell would emit, delivered
 * through the same explicit browser-test transport Gate 3 uses. No restart command, WebSocket,
 * event store or Arrow HTTP endpoint is introduced.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect } from "@playwright/test";

import { decodeArrowIpcStream } from "../src/arrow/arrow";
import { emitSession, test } from "./support/fixtures";
import { e2eOrigin } from "./support/paths";
import {
  failedBootstrap,
  pythonArrowFixture,
  startSidecar,
  type SidecarSession,
} from "./support/sidecar";
import { repositoryRoot } from "./support/paths";

async function openWorkspace(page: import("@playwright/test").Page, source: string, evidence: string) {
  await page.getByLabel("Source root").fill(source);
  await page.getByLabel("Evidence root").fill(evidence);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await page.waitForURL(/\/workspace\/[A-Za-z0-9_-]+$/);
  await expect(page.getByRole("listbox", { name: "Workspace artifacts" }).getByRole("option")).toHaveCount(2);
  await expect(page.getByText("Events: live")).toBeVisible();
}

async function stopQuietly(session: SidecarSession): Promise<void> {
  try {
    await session.kill();
  } catch {
    // A session already proven dead by the test is not a second failure.
  }
}

test("gate4: a real sidecar loss is visible, and no credential or server state survives", async ({
  page,
  harness,
}) => {
  await openWorkspace(page, harness.workspace.sourceRoot, harness.workspace.evidenceRoot);
  await page.getByRole("option", { name: /sc\.loaded-cmj/ }).click();
  await expect(page.getByTestId("artifact-content")).toContainText("Loaded countermovement jump");

  const oldOrigin = harness.sidecar.origin;
  const oldCredential = harness.sidecar.credential;
  const staleRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith(oldOrigin) && request.headers()["authorization"] !== undefined) {
      staleRequests.push(request.url());
    }
  });

  // The process is really gone before the shell announces the loss.
  await harness.sidecar.kill();
  const dead = await fetch(`${oldOrigin}/api/v1/health`, {
    headers: { Authorization: `Bearer ${oldCredential}` },
  }).then(
    () => false,
    () => true,
  );
  expect(dead).toBe(true);

  await emitSession(page, failedBootstrap());

  await expect(page.locator('[data-runtime-state="failed"]').first()).toBeVisible();
  await expect(
    page.getByText(/the local API exited after readiness without being asked to stop/),
  ).toBeVisible();
  await expect(
    page.getByText("The local API session is not ready, so this workspace cannot be read."),
  ).toBeVisible();
  await expect(
    page.getByText("No ready API session. Activity is unavailable in this runtime."),
  ).toBeVisible();
  await expect(page.getByTestId("artifact-content")).toHaveCount(0);

  // Credentials and read models lived only in the session that ended: neither is rendered,
  // stored, or used to make another request.
  expect(await page.content()).not.toContain(oldCredential);
  expect(
    await page.evaluate(() =>
      JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
    ),
  ).not.toContain(oldCredential);
  await page.waitForTimeout(750);
  expect(staleRequests).toEqual([]);
});

test("gate4: a replacement session invalidates identifiers and reopen preserves the digest", async ({
  page,
  harness,
}) => {
  await openWorkspace(page, harness.workspace.sourceRoot, harness.workspace.evidenceRoot);
  await page.getByRole("option", { name: /sc\.loaded-cmj/ }).click();
  await expect(page.getByText(harness.workspace.validDigest)).toBeVisible();
  const staleWorkspaceUrl = page.url();
  const oldCredential = harness.sidecar.credential;

  await harness.sidecar.kill();
  const replacement = await startSidecar();
  try {
    await emitSession(page, replacement.bootstrap());
    await expect(page.locator('[data-runtime-state="ready"]').first()).toBeVisible();

    // The old identifier is still in the address bar, and the new session does not know it.
    await expect(page.getByText("This workspace is no longer registered")).toBeVisible();
    await expect(page.getByTestId("artifact-content")).toHaveCount(0);

    const oldBearer = await fetch(`${replacement.origin}/api/v1/health`, {
      headers: { Authorization: `Bearer ${oldCredential}` },
    });
    expect(oldBearer.status).toBe(401);
    const newBearer = await fetch(`${replacement.origin}/api/v1/health`, {
      headers: { Authorization: `Bearer ${replacement.credential}` },
    });
    expect(newBearer.status).toBe(200);

    await page.getByRole("link", { name: "Open a workspace again" }).click();
    await expect(page).toHaveURL(/#open-workspace$/);
    await openWorkspace(page, harness.workspace.sourceRoot, harness.workspace.evidenceRoot);
    expect(page.url()).not.toBe(staleWorkspaceUrl);

    await page.getByRole("option", { name: /sc\.loaded-cmj/ }).click();
    await expect(page.getByText(harness.workspace.validDigest)).toBeVisible();
    // The feed was cleared with the session: exactly one open, not a replay plus a new one.
    await expect(page.getByText("Workspace opened")).toHaveCount(1);
  } finally {
    await stopQuietly(replacement);
  }
});

test("gate4: the authenticated SSE stream fails, reconnects on a new session, and does not replay", async ({
  page,
  harness,
}) => {
  await expect(page.getByText("Events: live")).toBeVisible();

  await harness.sidecar.kill();
  // A reader that was mid-stream when the listener died observes an invalid stream, which the
  // client classifies as terminal rather than retrying it forever. That refusal is visible,
  // and the feed is not left claiming to be live.
  await expect(page.getByText("Events: refused")).toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByText("The application refused the event stream for this session."),
  ).toBeVisible();

  const replacement = await startSidecar();
  try {
    // A controlled transient failure: the first connection of the *new* session is reset at
    // the network layer, and the client's own bounded retry must establish the second. The
    // sidecar that answers that second attempt is the real one.
    let eventAttempts = 0;
    await page.route("**/api/v1/events", async (route) => {
      eventAttempts += 1;
      if (eventAttempts === 1) {
        await route.abort("connectionreset");
        return;
      }
      await route.continue();
    });

    const streamed = page.waitForResponse(
      (response) => response.url().endsWith("/api/v1/events") && response.status() === 200,
      { timeout: 20_000 },
    );
    await emitSession(page, replacement.bootstrap());
    const response = await streamed;
    expect(eventAttempts).toBeGreaterThanOrEqual(2);
    expect(response.status()).toBe(200);
    expect(response.request().headers()["origin"]).toBe(e2eOrigin());
    expect(response.request().headers()["authorization"]).toMatch(/^Bearer /);

    await expect(page.getByText("Events: live")).toBeVisible();
    await expect(page.getByText("Workspace opened")).toHaveCount(0);

    await openWorkspace(page, harness.workspace.sourceRoot, harness.workspace.evidenceRoot);
    await expect(page.getByText("Workspace opened")).toHaveCount(1);
    await expect(page.getByText(/Discovery completed · 2 artifacts/)).toBeVisible();
  } finally {
    await stopQuietly(replacement);
  }
});

test("gate4: a slow response for a previous selection cannot republish authority", async ({
  page,
  harness,
}) => {
  await openWorkspace(page, harness.workspace.sourceRoot, harness.workspace.evidenceRoot);

  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let delayed = false;
  await page.route("**/api/v1/workspaces/*/artifacts/*", async (route) => {
    if (!delayed && route.request().method() === "GET") {
      delayed = true;
      await held;
    }
    await route.continue();
  });

  const valid = page.getByRole("option", { name: /sc\.loaded-cmj/ });
  const invalid = page.getByRole("option", { name: /invalid_scenario\.json/ });

  await valid.click();
  await invalid.click();
  await expect(invalid).toHaveAttribute("aria-selected", "true");
  release();
  await page.waitForTimeout(1_000);

  // The valid answer arrived after the selection moved, so it has no path into the panes.
  await expect(invalid).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("No validated content is published for this artifact.")).toBeVisible();
  await expect(page.getByTestId("artifact-content")).toHaveCount(0);
});

test("gate4: the Arrow IPC fixture is the same 832 bytes in Python and JavaScript", async () => {
  const fixturePath = path.join(
    repositoryRoot(),
    "apps",
    "workbench",
    "src",
    "test",
    "fixtures",
    "qualification.arrow.b64",
  );
  const fixture = Buffer.from(readFileSync(fixturePath, "ascii").trim(), "base64");
  expect(fixture.byteLength).toBe(832);

  const python = pythonArrowFixture();
  expect(python.bytes.equals(fixture)).toBe(true);
  expect(python.sha256).toBe(createHash("sha256").update(fixture).digest("hex"));

  const table = await decodeArrowIpcStream(new Uint8Array(fixture));
  expect(table.numRows).toBe(4);
  expect(table.fields).toEqual([
    { name: "sample_index", type: "Int64", nullable: false },
    { name: "label", type: "Utf8", nullable: false },
    { name: "measurement", type: "Float64", nullable: true },
    { name: "note", type: "Utf8", nullable: true },
  ]);
  expect(table.rows).toEqual([
    { sample_index: 0n, label: "baseline", measurement: 1.5, note: null },
    { sample_index: 1n, label: "perturbed", measurement: 2.25, note: "first trial" },
    { sample_index: 2n, label: "baseline", measurement: null, note: "not measured" },
    { sample_index: 3n, label: "recovered", measurement: -0.5, note: null },
  ]);
});
