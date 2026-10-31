/**
 * Gate 3: browser-grade end-to-end qualification over the production workbench.
 *
 * What is real here: the Chromium browser, the production React route tree, provider, typed
 * client, Query cache, controls and accessibility semantics, and a secured Python sidecar the
 * test started and stopped itself.
 *
 * What is simulated: only the desktop shell's two session IPC facts, through an explicitly
 * named browser-test transport installed before the application boots. That substitution is
 * visible in the test titles and in `documentElement.dataset.dynamisbenchHarness`. It is not
 * native WebView2 evidence, and the Gate 5 record says so separately.
 */

import { expect } from "@playwright/test";

import { browserOnlyTest, test } from "./support/fixtures";

test("gate3: the landing route reports readiness from the real secured API", async ({
  page,
  harness,
  network,
}) => {
  await expect(page.locator('[data-runtime-state="ready"]').first()).toBeVisible();
  await expect(page.getByText(/DynamisBench 0\.0\.0, API v1\./).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open workspace" })).toBeVisible();
  await expect(page.getByLabel("Source root")).toBeVisible();
  await expect(page.getByLabel("Evidence root")).toBeVisible();

  expect(
    await page.evaluate(() => document.documentElement.dataset.dynamisbenchHarness),
  ).toBe("playwright-test-bridge");
  expect(page.url()).not.toContain(harness.sidecar.credential);
  expect(await page.content()).not.toContain(harness.sidecar.credential);
  expect(await page.context().cookies()).toEqual([]);
  expect(
    await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } })),
  ).not.toContain(harness.sidecar.credential);

  expect(network.offenses).toEqual([]);
});

test("gate3: a real workspace is opened, discovered, selected, inspected and re-read", async ({
  page,
  harness,
  network,
}) => {
  await page.getByLabel("Source root").fill(harness.workspace.sourceRoot);
  await page.getByLabel("Evidence root").fill(harness.workspace.evidenceRoot);
  await page.getByRole("button", { name: "Open workspace" }).click();

  await page.waitForURL(/\/workspace\/[A-Za-z0-9_-]+$/);
  expect(page.url()).not.toContain(harness.workspace.sourceRoot);
  expect(page.url()).not.toContain(harness.workspace.evidenceRoot);

  await expect(page.getByRole("heading", { name: "Explorer" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Validated content" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Inspector" })).toBeVisible();
  await expect(page.getByRole("listbox", { name: "Workspace artifacts" }).getByRole("option")).toHaveCount(2);
  await expect(page.getByText("1 valid", { exact: true })).toBeVisible();
  await expect(page.getByText("1 invalid", { exact: true })).toBeVisible();

  // Activity is already mounted at the root, so the first operation — open — is observed.
  await expect(page.getByText("Workspace opened")).toBeVisible();
  await expect(page.getByText(/Discovery completed · 2 artifacts · 1 valid · 1 invalid/)).toBeVisible();
  await expect(page.getByText("Events: live")).toBeVisible();

  const valid = page.getByRole("option", { name: /sc\.loaded-cmj/ });
  await valid.focus();
  await expect(valid).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(valid).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("artifact-content")).toContainText("Loaded countermovement jump");
  await expect(page.getByText(harness.workspace.validDigest)).toBeVisible();
  await expect(page.getByText("sha256")).toBeVisible();
  await expect(page.getByText("Inspected scenario · valid").first()).toBeVisible();

  const invalid = page.getByRole("option", { name: /invalid_scenario\.json/ });
  await invalid.click();
  await expect(invalid).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("No validated content is published for this artifact.")).toBeVisible();
  const inspector = page.locator('section[aria-labelledby="inspector-heading"]');
  await expect(inspector.getByText("schema_validation")).toBeVisible();
  await expect(inspector.getByText("none published").first()).toBeVisible();

  // The re-read control asks the application again; it is not a cached value.
  await valid.click();
  await page.getByRole("button", { name: "Re-read" }).click();
  await expect(page.getByTestId("artifact-content")).toContainText("Loaded countermovement jump");
  await expect(page.getByText("Inspected scenario · valid").first()).toBeVisible();

  expect(network.offenses).toEqual([]);
});

test("gate3: the explicit form and Explorer are keyboard operable", async ({ page, harness }) => {
  const source = page.getByLabel("Source root");
  const evidence = page.getByLabel("Evidence root");

  await source.focus();
  await expect(source).toBeFocused();
  await source.fill(harness.workspace.sourceRoot);
  await page.keyboard.press("Tab");
  await expect(evidence).toBeFocused();
  await evidence.fill(harness.workspace.evidenceRoot);
  await page.keyboard.press("Tab");

  const open = page.getByRole("button", { name: "Open workspace" });
  await expect(open).toBeFocused();
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/workspace\/[A-Za-z0-9_-]+$/);

  const first = page.getByRole("listbox", { name: "Workspace artifacts" }).getByRole("option").first();
  await first.focus();
  await expect(first).toBeFocused();
  await page.keyboard.press("Space");
  await expect(first).toHaveAttribute("aria-selected", "true");

  const collapse = page.getByRole("button", { name: "Collapse navigation" });
  await expect(collapse).toHaveAttribute("aria-expanded", "true");
  await collapse.click();
  await expect(page.getByRole("button", { name: "Expand navigation" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("gate3: a failed open is bounded and the rejected roots are not echoed", async ({
  page,
  harness,
}) => {
  const missing = `${harness.workspace.sourceRoot}-missing`;
  await page.getByLabel("Source root").fill(missing);
  await page.getByLabel("Evidence root").fill(harness.workspace.evidenceRoot);
  await page.getByRole("button", { name: "Open workspace" }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText("The declared workspace roots could not be opened.");
  await expect(alert).not.toContainText(missing);
  await expect(page).toHaveURL(/\/$/);
});

browserOnlyTest(
  "gate3: a normal browser without the test bridge reports the production unavailable state",
  async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-runtime-state="browser_unavailable"]').first()).toBeVisible();
    await expect(
      page.getByText("A ready local API session is required to open a workspace."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Open workspace" })).toHaveCount(0);
    expect(
      await page.evaluate(() => document.documentElement.dataset.dynamisbenchHarness),
    ).toBe("production-browser-source");
  },
);
