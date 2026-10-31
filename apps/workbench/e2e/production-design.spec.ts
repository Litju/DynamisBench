import { expect } from "@playwright/test";
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { test } from "./support/fixtures";

// Real secured sidecar + production UI; only the Tauri IPC bootstrap is substituted.
test("approved shell preserves selection, pane controls and latest source status", async ({
  page,
  harness,
  network,
}) => {
  await page.getByLabel("Source root").fill(harness.workspace.sourceRoot);
  await page.getByLabel("Evidence root").fill(harness.workspace.evidenceRoot);
  await page
    .getByRole("button", { name: "Open workspace", exact: true })
    .click();
  await page.waitForURL(/\/workspace\/[A-Za-z0-9_-]+$/);
  const source = page.getByRole("option", { name: /sc\.loaded-cmj/ });
  await source.click();
  await expect(page.getByTestId("artifact-content")).toContainText(
    "Loaded countermovement jump",
  );
  await expect(
    page.getByRole("button", { name: "Execute", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("No materialized scientific scene"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Analysis & VVUQ", exact: true })
    .click();
  await expect(page.getByText("Scientific analysis unavailable")).toBeVisible();
  await expect(source).toHaveAttribute("aria-selected", "true");
  await page
    .getByRole("button", { name: "Simulation Laboratory", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Collapse Inspector", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Inspector", exact: true }),
  ).toBeHidden();
  await page
    .getByRole("button", { name: "Expand Inspector", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Collapse Navigator", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Expand Navigator", exact: true })
    .click();
  await source.focus();
  await page.keyboard.press("End");
  await expect(
    page
      .getByRole("listbox", { name: "Workspace artifacts" })
      .getByRole("option")
      .last(),
  ).toBeFocused();
  await page.keyboard.press("Home");
  await expect(
    page
      .getByRole("listbox", { name: "Workspace artifacts" })
      .getByRole("option")
      .first(),
  ).toBeFocused();
  await expect(
    page.getByRole("option", { name: "Scene only", exact: true }),
  ).toHaveAttribute("disabled", "");
  await page.getByLabel("Laboratory layout").focus();
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("Laboratory layout")).not.toHaveValue("scene");
  await expect(
    page.getByRole("button", { name: "Re-read", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("artifact-content")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Collapse navigation" }),
  ).toHaveCount(0);
  for (const width of [1024, 1280, 1600]) {
    await page.setViewportSize({ width, height: 900 });
    for (const layout of ["bottom", "side"]) {
      await page.getByLabel("Laboratory layout").selectOption(layout);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
    }
  }
  await page.getByLabel("Laboratory layout").selectOption("bottom");
  await page.setViewportSize({ width: 1280, height: 900 });
  // The E2E entry has a different Vite root; ensure it includes production utility styles.
  expect(
    await page
      .locator("main > div")
      .evaluate((element) => getComputedStyle(element).display),
  ).toBe("flex");
  expect(
    await page
      .getByRole("heading", { name: "Workspace", exact: true })
      .evaluate((element) => getComputedStyle(element).position),
  ).toBe("absolute");
  // Opt-in screenshots contain no roots or credential; capture pixels only, no trace or DOM dump.
  if (process.env.DYNAMISBENCH_UX_SCREENSHOTS) {
    const directory = process.env.DYNAMISBENCH_UX_SCREENSHOTS;
    await mkdir(directory, { recursive: true });
    expect(await page.content()).not.toContain(harness.sidecar.credential);
    expect(await page.content()).not.toContain(harness.workspace.sourceRoot);
    await page.screenshot({
      path: path.join(directory, "production-lab-light.png"),
    });
    await page.getByRole("button", { name: "Toggle color theme" }).click();
    await expect(page.locator(".wb-shell")).toHaveAttribute(
      "data-theme",
      "dark",
    );
    await page.screenshot({
      path: path.join(directory, "production-lab-dark.png"),
    });
  }
  // Hold then fail a real inspection request; cached Explorer facts must be explicit.
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/artifacts/*", async (route) => { await gate; await route.abort("failed"); });
  await page.getByRole("button", { name: "Re-read", exact: true }).click();
  await expect(source.getByText("Revalidating", { exact: true })).toBeVisible();
  await expect(source.getByText("valid", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Last successful source reads", { exact: true })).toBeVisible();
  await expect(page.getByText(/Counts retain the last successful reads/)).toBeVisible();
  release();
  await expect(source.getByText("Unavailable", { exact: true })).toBeVisible();
  await expect(source.getByText("valid", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("artifact-content")).toHaveCount(0);
  await page.unroute("**/artifacts/*");
  await page.getByRole("button", { name: "Re-read", exact: true }).click();
  await expect(page.getByTestId("artifact-content")).toContainText("Loaded countermovement jump");
  await expect(source.getByText("valid", { exact: true })).toBeVisible();
  // Actual file mutation: the next inspection must supersede the discovery snapshot everywhere.
  await writeFile(
    path.join(harness.workspace.sourceRoot, harness.workspace.validReference),
    "{}",
    "utf8",
  );
  await page.getByRole("button", { name: "Re-read", exact: true }).click();
  await expect(
    page.getByText("No validated content is published for this artifact."),
  ).toBeVisible();
  await expect(page.getByText("2 invalid", { exact: true })).toBeVisible();
  await expect(page.getByText("0 valid", { exact: true })).toBeVisible();
  await expect(page.getByTestId("artifact-content")).toHaveCount(0);
  await expect(page.locator(".wb-context")).toContainText("invalid");
  expect(network.offenses).toEqual([]);
});
