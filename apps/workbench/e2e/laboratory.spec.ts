import { expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { test } from "./support/fixtures";

// The biomechanics laboratory against a real secured sidecar: the production route tree reads
// the packaged dataset over HTTP (JSON read models and Arrow frame streams), draws it with
// WebGL, and is driven the way a person drives it. Only the Tauri IPC bootstrap is substituted.

/** The nominal repetition's trajectory hash, as the Python squat qualification pins it. */
const NOMINAL_TRAJECTORY = "d3b4edafc090";
const ABLATION_TRAJECTORY = "6d34a139189a";

async function openLaboratory(page: Page): Promise<void> {
  await page.getByRole("link", { name: "Laboratory", exact: true }).click();
  await page.waitForURL(/\/laboratory$/);
  await expect(page.getByRole("heading", { name: "Biomechanics Laboratory", exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("stage-hud")).toBeVisible();
}

async function playbackTime(page: Page): Promise<number> {
  return Number(await page.getByTestId("playback-time").textContent());
}

test("the laboratory reads, plays, seeks, selects and turns its folios over the real API", async ({
  page,
  harness,
  network,
}) => {
  // A software WebGL renderer redraws slowly after each viewport change.
  test.setTimeout(180_000);
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(message.text());
  });
  const laboratoryRequests: { url: string; accept: string | undefined }[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/laboratory")) {
      laboratoryRequests.push({ url: new URL(request.url()).pathname, accept: request.headers().accept });
    }
  });

  await page.setViewportSize({ width: 1600, height: 1000 });
  await openLaboratory(page);

  // The dataset came over HTTP: JSON read models and three Arrow frame streams.
  await expect.poll(() => laboratoryRequests.length).toBeGreaterThanOrEqual(6);
  const paths = laboratoryRequests.map((request) => request.url);
  for (const expected of [
    "/api/v1/laboratory",
    "/api/v1/laboratory/model",
    "/api/v1/laboratory/recordings/repetition",
    "/api/v1/laboratory/recordings/repetition/frames/pose",
    "/api/v1/laboratory/recordings/repetition/frames/kinematics",
    "/api/v1/laboratory/recordings/repetition/frames/kinetics",
  ]) {
    expect(paths).toContain(expected);
  }
  expect(
    laboratoryRequests.filter((request) => request.url.includes("/frames/")).every(
      (request) => request.accept === "application/vnd.apache.arrow.stream",
    ),
  ).toBe(true);

  // Provenance: the recording on show is the qualified physics, and says what it is not.
  const provenance = page.getByLabel("Provenance", { exact: true });
  await expect(provenance).toContainText(NOMINAL_TRAJECTORY);
  await expect(provenance).toContainText(/not sealed DynamisBench evidence/i);

  // The stage is drawn with WebGL2 where the browser provides it (a drawn scene compresses far
  // worse than an empty canvas); a host without WebGL2 gets the stated fallback instead.
  const renderer = await page.locator("[data-webgl]").getAttribute("data-webgl");
  if (renderer === "webgl2") {
    await expect(page.locator('[data-webgl="webgl2"] canvas')).toBeVisible();
    const stagePixels = await page.locator('[data-webgl="webgl2"] canvas').screenshot();
    expect(stagePixels.byteLength).toBeGreaterThan(20_000);
    // The athlete is drawn as the anatomical figure derived from the model (a pinned asset read
    // over HTTP), and the model's own segment geometry is one click away.
    const stage = page.getByRole("region", { name: "Stage" });
    await expect(stage).toHaveAttribute("data-figure", "anatomical", { timeout: 30_000 });
    expect(laboratoryRequests.map((request) => request.url)).toContain("/api/v1/laboratory/figure");
    const figure = page.getByRole("group", { name: "Figure" });
    await figure.getByRole("button", { name: "Scientific" }).click();
    await expect(stage).toHaveAttribute("data-figure", "scientific");
    await figure.getByRole("button", { name: "Anatomical" }).click();
    await expect(stage).toHaveAttribute("data-figure", "anatomical");
  } else {
    await expect(page.getByText("Stage unavailable")).toBeVisible();
    test.info().annotations.push({ type: "webgl", description: "this browser provides no WebGL2" });
  }

  // One clock, from the keyboard.
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("playback-frame")).toHaveText("3");
  await page.keyboard.press("]");
  await expect(page.getByTestId("playback-time")).toHaveText("1.000");
  await expect(page.getByTestId("stage-hud")).toContainText(/descent/i);

  // Seek by clicking the kinematics plot at the bottom of the squat.
  const plot = page.getByRole("img", { name: /Kinematics — joint angles/ });
  const box = await plot.boundingBox();
  if (box === null) throw new Error("the kinematics plot has no box");
  const duration = 5.5;
  await plot.click({ position: { x: 40 + (2.7 / duration) * (box.width - 52), y: box.height / 2 } });
  await expect.poll(() => playbackTime(page)).toBeGreaterThan(2.6);
  expect(await playbackTime(page)).toBeLessThan(2.8);
  const inspector = page.getByLabel("Inspector");
  await expect(inspector.getByText("Knee · left")).toBeVisible();
  await expect(inspector.getByRole("img", { name: /degrees of flexion/ })).toHaveAttribute(
    "aria-label",
    /^1(1[5-9]|2[0-2])\.\d degrees of flexion/,
  );

  // At the bottom of the squat, seen obliquely at a laptop size, the stage's text never piles
  // up: the joint notes, the force labels, the ring graduations and the HUD are all disjoint.
  if (renderer === "webgl2") {
    const viewport = page.viewportSize();
    await page.setViewportSize({ width: 1366, height: 768 });
    await expect
      .poll(() =>
        page.evaluate(() => {
          const stage = document.querySelector('section[aria-label="Stage"]');
          if (stage === null) return ["no stage"];
          const boxes = [
            ...stage.querySelectorAll<HTMLElement>("[data-marginalia], [data-force], [data-degree], [data-testid='stage-hud']"),
          ]
            .filter((element) => !element.hidden && element.getBoundingClientRect().width > 0)
            .map((element) => ({
              name: element.dataset.marginalia ?? element.dataset.force ?? element.dataset.degree ?? "hud",
              box: element.getBoundingClientRect(),
            }));
          const clashes: string[] = [];
          for (let i = 0; i < boxes.length; i += 1) {
            for (let j = i + 1; j < boxes.length; j += 1) {
              const a = boxes[i]!.box;
              const b = boxes[j]!.box;
              if (a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1) {
                clashes.push(`${boxes[i]!.name} × ${boxes[j]!.name}`);
              }
            }
          }
          return clashes;
        }),
      )
      .toEqual([]);
    if (viewport !== null) await page.setViewportSize(viewport);
  }

  // Play advances the one clock; pause holds it.
  await page.getByRole("button", { name: "Play", exact: true }).click();
  const before = await playbackTime(page);
  await expect.poll(() => playbackTime(page), { timeout: 20_000 }).not.toBe(before);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const held = await playbackTime(page);
  await page.waitForTimeout(400);
  expect(await playbackTime(page)).toBe(held);

  // One selection: the model tree selects the joint the inspector and stage show.
  await page.getByRole("button", { name: /Thigh L/ }).click();
  await expect(inspector.getByText("Hip · left")).toBeVisible();
  await expect(page.getByLabel("Status")).toContainText("selection: hip_flexion_l");

  // The folios.
  const folios = page.getByRole("navigation", { name: "Folios" });
  await folios.getByRole("button", { name: /Model Atlas/ }).click();
  await expect(page.getByRole("heading", { name: "The athlete and the bar, in the standing keyframe" })).toBeVisible();
  await expect(page.getByText(/Total 95\.0000 kg/)).toBeVisible();
  await folios.getByRole("button", { name: /Analysis/ }).click();
  await expect(page.getByRole("heading", { name: "Ledger of work and energy" })).toBeVisible();
  await expect(page.getByText(/— balances/)).toBeVisible();
  await folios.getByRole("button", { name: /Evidence/ }).click();
  await expect(page.getByTestId("check-tally")).toContainText("22 pass · 0 fail");
  await expect(
    page.getByText(/The MuJoCo worker that generated them is not run by this read-only integration\./),
  ).toBeVisible();

  // An ablation: the register shows exactly what the checks reject.
  await page.getByRole("combobox", { name: "Recording" }).selectOption("dataset:ablation-no-internal-model");
  await expect(provenance).toContainText(ABLATION_TRAJECTORY, { timeout: 30_000 });
  await expect(page.getByTestId("check-tally")).toContainText("13 pass · 6 fail · 3 not evaluated");
  await expect(page.locator('tr[data-criterion="heel"]')).toHaveAttribute("data-status", "fail");
  await expect(page.locator('tr[data-criterion="momentum"]')).toHaveAttribute("data-status", "pass");

  // The ground changes everywhere, and the laboratory keeps working.
  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await expect(page.locator(".wb-shell")).toHaveAttribute("data-theme", "light");
  await folios.getByRole("button", { name: /Laboratory/ }).click();
  await expect(page.locator(`[data-webgl="${renderer}"]`)).toBeVisible();

  // The window is the instrument: nothing overflows horizontally at the supported sizes.
  // Every pinned plot draws inside its own cell, never over its neighbour.
  for (const size of [
    { width: 1366, height: 768 },
    { width: 1920, height: 1200 },
  ]) {
    await page.setViewportSize(size);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect
      .poll(() =>
        page.evaluate(() =>
          [...document.querySelectorAll(".lab-dock-plots figure.lab-plot")].every((figure) => {
            const box = figure.getBoundingClientRect();
            const drawing = figure.querySelector(".lab-plot-frame > svg")?.getBoundingClientRect();
            return drawing !== undefined && drawing.left >= box.left - 0.5 && drawing.right <= box.right + 0.5;
          }),
        ),
      )
      .toBe(true);
  }

  // The shell itself never scrolls: each folio scrolls inside its own box, and nothing placed
  // absolutely in a folio (the plots' hidden value tables) extends the document past the window.
  for (const name of ["Analysis", "Evidence", "Model Atlas", "Study & Runs", "Laboratory"]) {
    await folios.getByRole("button", { name: new RegExp(name) }).click();
    await expect
      .poll(() =>
        page.evaluate(() => {
          window.scrollTo(0, 10_000);
          const moved = window.scrollY;
          window.scrollTo(0, 0);
          return { height: document.documentElement.scrollHeight <= window.innerHeight, moved };
        }),
      )
      .toEqual({ height: true, moved: 0 });
  }

  expect(await page.content()).not.toContain(harness.sidecar.credential);
  expect(failures).toEqual([]);
  expect(network.offenses).toEqual([]);
});

// Opt-in screenshots of every folio in both grounds, captured from the running application.
// Pixels only: no trace or DOM dump, and the page is checked to hold no credential or root.
test("laboratory screenshots", async ({ page, harness }) => {
  test.setTimeout(300_000);
  const directory = process.env.DYNAMISBENCH_UX_SCREENSHOTS;
  test.skip(directory === undefined, "set DYNAMISBENCH_UX_SCREENSHOTS to a directory to capture");
  if (directory === undefined) return;
  await mkdir(directory, { recursive: true });
  await page.setViewportSize({ width: 1920, height: 1200 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(directory, "00-overview-studiolo.png") });
  await openLaboratory(page);
  expect(await page.content()).not.toContain(harness.sidecar.credential);

  const folios = page.getByRole("navigation", { name: "Folios" });
  const shoot = async (name: string) => {
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(directory, `${name}.png`) });
  };
  // Seek with one pointer press on the track (a software renderer draws each step slowly).
  const seek = async (seconds: number) => {
    const track = page.getByRole("slider", { name: "Playback position" });
    const box = await track.boundingBox();
    if (box === null) throw new Error("the track has no box");
    const duration = Number(await track.getAttribute("aria-valuemax"));
    await track.click({ position: { x: (seconds / duration) * box.width, y: box.height - 6 } });
    await page.locator("body").click({ position: { x: 5, y: 5 } });
  };

  for (const ground of ["studiolo", "vellum"] as const) {
    if (ground === "vellum") {
      await page.getByRole("button", { name: "Toggle color theme" }).click();
      await expect(page.locator(".wb-shell")).toHaveAttribute("data-theme", "light");
    }
    await folios.getByRole("button", { name: /Laboratory/ }).click();
    await seek(2.2);
    await shoot(`10-laboratory-${ground}`);
    await folios.getByRole("button", { name: /Model Atlas/ }).click();
    await shoot(`20-atlas-${ground}`);
    await folios.getByRole("button", { name: /Analysis/ }).click();
    await shoot(`30-analysis-${ground}`);
    await folios.getByRole("button", { name: /Evidence/ }).click();
    await shoot(`40-evidence-${ground}`);
  }

  await page.getByRole("button", { name: "Toggle color theme" }).click();
  await page.getByRole("combobox", { name: "Recording" }).selectOption("dataset:ablation-no-internal-model");
  await expect(page.getByLabel("Provenance", { exact: true })).toContainText(ABLATION_TRAJECTORY, { timeout: 30_000 });
  await shoot("50-evidence-ablation-studiolo");
  await folios.getByRole("button", { name: /Laboratory/ }).click();
  await seek(3.5);
  await shoot("51-laboratory-ablation-studiolo");

  await page.getByRole("combobox", { name: "Recording" }).selectOption("dataset:repetition");
  await expect(page.getByLabel("Provenance", { exact: true })).toContainText(NOMINAL_TRAJECTORY, { timeout: 30_000 });
  await page.getByRole("button", { name: "Sagittal" }).click();
  await page.getByRole("button", { name: "Balance" }).click();
  await page.getByRole("button", { name: "Contact" }).click();
  await seek(2.7);
  await shoot("60-laboratory-sagittal-bottom-studiolo");

  await page.getByRole("group", { name: "Figure" }).getByRole("button", { name: "Scientific" }).click();
  await shoot("61-laboratory-sagittal-bottom-scientific-studiolo");
  await page.getByRole("group", { name: "Figure" }).getByRole("button", { name: "Anatomical" }).click();

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.getByRole("button", { name: "Oblique" }).click();
  await shoot("70-laboratory-1366x768-studiolo");
});
