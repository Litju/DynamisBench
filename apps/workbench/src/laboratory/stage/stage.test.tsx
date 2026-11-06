/**
 * The stage's failure states, with the WebGL scene replaced by a controllable stand-in (jsdom has
 * no WebGL): a renderer that cannot be built, one that throws while drawing, and a context the
 * browser takes away and gives back. In every case the stage says what happened, in bounded
 * words, and every other pane keeps working.
 */

import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { APPLICATION_INFO } from "../../test/api-fixtures";
import { controlledSource } from "../../test/controlled-source";
import { errorResponse, stubFetch, unavailableEvents } from "../../test/fetch-stub";
import { figureStreamFor } from "../../test/figure-fixtures";
import { jsonResponse } from "../../test/http-fixtures";
import { LABORATORY_MODEL, binaryResponse, laboratoryAnswer } from "../../test/laboratory-fixtures";
import { decodeLaboratoryModelResponse } from "../../api/laboratory-decode";
import type { LaboratoryModelResponse } from "../../api/laboratory-types";
import userEvent from "@testing-library/user-event";
import { renderApplication } from "../../test/render-app";
import { readyApiSession } from "../../test/session-fixtures";
import { resetLaboratoryStore, useLaboratoryStore } from "../store";

const behaviour = vi.hoisted(() => ({
  construct: "ok" as "ok" | "throw",
  render: "ok" as "ok" | "throw",
  built: 0,
  figures: [] as unknown[],
  modes: [] as string[],
}));

vi.mock("./scene", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./scene")>();
  class FakeScene {
    constructor() {
      behaviour.built += 1;
      if (behaviour.construct === "throw") {
        throw new Error("Error creating WebGL context at /home/someone/.cache/gpu\nstack line");
      }
    }
    setFrames() {}
    setFrame() {}
    setFigure(figure: unknown) {
      behaviour.figures.push(figure);
    }
    setFigureMode(mode: string) {
      behaviour.modes.push(mode);
    }
    setLayers() {}
    setSelection() {}
    setPalette() {}
    setOrbit() {}
    resize() {}
    dispose() {}
    pick() {
      return null;
    }
    centreOfMass() {
      return { x: 0, y: 0, z: 1 };
    }
    jointPosition() {
      return null;
    }
    footForce() {
      return null;
    }
    balancePoint() {
      return [0, 0];
    }
    project() {
      return { x: 0, y: 0, visible: false };
    }
    worldAxes() {
      return { x: [1, 0], y: [0, 1], z: [0, -1] };
    }
    pixelsPerMetre() {
      return 100;
    }
    render() {
      if (behaviour.render === "throw") {
        throw new Error("WebGL: INVALID_OPERATION: drawElements");
      }
    }
  }
  return { ...actual, webglAvailable: () => true, LaboratoryScene: FakeScene };
});

beforeEach(() => {
  behaviour.construct = "ok";
  behaviour.render = "ok";
  behaviour.built = 0;
  behaviour.figures = [];
  behaviour.modes = [];
});

afterEach(() => resetLaboratoryStore());

async function renderLaboratory(figure: Uint8Array | null = null) {
  stubFetch(({ url }) => {
    if (url.endsWith("/laboratory/figure")) {
      return figure === null ? errorResponse(500, "internal_error", "no figure") : binaryResponse(figure, "application/vnd.dynamisbench.figure");
    }
    const answer = laboratoryAnswer(url);
    if (answer !== null) return answer;
    if (url.endsWith("/info")) return jsonResponse(APPLICATION_INFO);
    return unavailableEvents();
  });
  const controlled = controlledSource();
  renderApplication("/laboratory", { source: controlled.source });
  await waitFor(() => expect(controlled.listening).toBe(true));
  act(() => controlled.publish({ phase: "ready", api: readyApiSession() }));
  await screen.findByTestId("stage-hud", {}, { timeout: 10_000 });
  return screen.getByRole("region", { name: "Stage" });
}

describe("the stage when WebGL fails", () => {
  it("says the renderer could not be built, in one bounded, path-free line, and keeps the panes", async () => {
    behaviour.construct = "throw";
    const stage = await renderLaboratory();

    await waitFor(() => expect(stage).toHaveAttribute("data-webgl", "failed"));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The stage could not draw");
    expect(alert).toHaveTextContent("Error creating WebGL context");
    expect(alert).not.toHaveTextContent("/home/someone");
    expect(alert).not.toHaveTextContent("stack line");
    expect(useLaboratoryStore.getState().renderer?.kind).toBe("failed");
    expect(screen.getByRole("region", { name: "Plots" })).toBeInTheDocument();
    expect(screen.getByTestId("stage-hud")).toBeInTheDocument();
  });

  it("stops drawing after a draw error instead of retrying in a loop", async () => {
    behaviour.render = "throw";
    const stage = await renderLaboratory();

    await waitFor(() => expect(stage).toHaveAttribute("data-webgl", "failed"));
    expect(screen.getByRole("alert")).toHaveTextContent("INVALID_OPERATION");
    expect(stage.querySelector("canvas")).not.toBeVisible();
    const built = behaviour.built;
    act(() => useLaboratoryStore.getState().seekFrame(200));
    expect(behaviour.built).toBe(built);
  });

  it("follows a lost context and rebuilds the scene when the browser restores it", async () => {
    const stage = await renderLaboratory();
    await waitFor(() => expect(stage).toHaveAttribute("data-webgl", "webgl2"));
    const canvas = stage.querySelector("canvas") as HTMLCanvasElement;
    const built = behaviour.built;

    const lost = new Event("webglcontextlost", { cancelable: true });
    act(() => {
      canvas.dispatchEvent(lost);
    });
    expect(lost.defaultPrevented).toBe(true);
    await waitFor(() => expect(stage).toHaveAttribute("data-webgl", "lost"));
    const fallback = screen.getByText("Graphics context lost").closest("[data-stage-status]");
    expect(fallback).toHaveAttribute("role", "status");
    expect(fallback).toHaveAttribute("data-stage-status", "lost");
    // The canvas stays mounted so the browser can give the context back.
    expect(stage.querySelector("canvas")).toBe(canvas);

    act(() => {
      canvas.dispatchEvent(new Event("webglcontextrestored"));
    });
    await waitFor(() => expect(stage).toHaveAttribute("data-webgl", "webgl2"));
    expect(behaviour.built).toBeGreaterThan(built);
    expect(screen.queryByText("Graphics context lost")).toBeNull();
  });
});

describe("the stage's figure", () => {
  it("draws the anatomical figure derived from the model, and switches to the scientific one", async () => {
    const model = decodeLaboratoryModelResponse(structuredClone(LABORATORY_MODEL)) as LaboratoryModelResponse;
    const stage = await renderLaboratory(figureStreamFor(model));
    await waitFor(() => expect(stage).toHaveAttribute("data-figure", "anatomical"));
    expect(behaviour.figures.at(-1)).toMatchObject({ modelSha256: model.model_sha256, vertexCount: 4 });
    expect(behaviour.modes.at(-1)).toBe("anatomical");

    const figure = screen.getByRole("group", { name: "Figure" });
    await userEvent.setup().click(within(figure).getByRole("button", { name: "Scientific" }));
    await waitFor(() => expect(stage).toHaveAttribute("data-figure", "scientific"));
    expect(behaviour.modes.at(-1)).toBe("scientific");
    expect(useLaboratoryStore.getState().figureMode).toBe("scientific");
  });

  it("keeps the scientific figure, and says why, when the anatomical one cannot be read", async () => {
    const stage = await renderLaboratory(null);
    const anatomical = within(screen.getByRole("group", { name: "Figure" })).getByRole("button", { name: "Anatomical" });
    await waitFor(() => expect(anatomical).toBeDisabled());
    expect(anatomical.title).not.toBe("");
    expect(stage).toHaveAttribute("data-figure", "scientific");
    expect(behaviour.figures.every((entry) => entry === null)).toBe(true);
  });

  it("refuses a figure derived from another model", async () => {
    const model = decodeLaboratoryModelResponse(structuredClone(LABORATORY_MODEL)) as LaboratoryModelResponse;
    const moved = { ...model, bodies: model.bodies.map((body) => (body.name === "shank_l" ? { ...body, position_m: [0, 0, -0.5] as const } : body)) };
    const stage = await renderLaboratory(figureStreamFor(moved as LaboratoryModelResponse));
    const anatomical = within(screen.getByRole("group", { name: "Figure" })).getByRole("button", { name: "Anatomical" });
    await waitFor(() => expect(anatomical.title).toMatch(/shank_l is elsewhere in this model/));
    expect(anatomical).toBeDisabled();
    expect(stage).toHaveAttribute("data-figure", "scientific");
  });
});
