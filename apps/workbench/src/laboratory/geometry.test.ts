/**
 * Stage camera presets and controls, and the Atlas engraving's projection.
 */

import { describe, expect, it } from "vitest";

import { decodeLaboratoryModelResponse } from "../api/laboratory-decode";
import type { LaboratoryFrameTable, LaboratoryModelResponse } from "../api/laboratory-types";
import { LABORATORY_MODEL } from "../test/laboratory-fixtures";
import { engrave, projectPoint, rotation, viewBasis } from "./engraving";
import {
  MAX_DISTANCE,
  MAX_ELEVATION,
  MIN_DISTANCE,
  orbitDrag,
  orbitPan,
  orbitPosition,
  orbitZoom,
  presetOrbit,
  wrapDegrees,
} from "./stage/camera";

const TARGET = [0.05, 0, 0.92] as const;

describe("the stage camera", () => {
  it("places the sagittal view on the athlete's right, looking across the sagittal plane", () => {
    const [x, y, z] = orbitPosition(presetOrbit("sagittal", TARGET));
    expect(x).toBeCloseTo(0.05, 6);
    expect(y).toBeLessThan(-4);
    expect(z).toBeGreaterThan(0.92);
  });

  it("places the frontal view in front of the athlete (+x) and the plan view above", () => {
    expect(orbitPosition(presetOrbit("frontal", TARGET))[0]).toBeGreaterThan(4);
    const plan = presetOrbit("plan", TARGET);
    expect(orbitPosition(plan)[2]).toBeGreaterThan(4);
  });

  it("clamps elevation and distance, and wraps azimuth", () => {
    const orbit = presetOrbit("oblique", TARGET);
    expect(orbitDrag(orbit, 0, 10_000).elevation).toBe(MAX_ELEVATION);
    expect(orbitZoom(orbit, 1e9).distance).toBeLessThanOrEqual(MAX_DISTANCE);
    let near = orbit;
    for (let i = 0; i < 50; i += 1) near = orbitZoom(near, -1e9);
    expect(near.distance).toBe(MIN_DISTANCE);
    expect(wrapDegrees(190)).toBe(-170);
    expect(wrapDegrees(-180)).toBe(180);
  });

  it("pans in the screen plane: a horizontal drag in the sagittal view moves along x", () => {
    const orbit = presetOrbit("sagittal", TARGET);
    const panned = orbitPan(orbit, 100, 0, 500, 30);
    expect(panned.target[0]).toBeLessThan(TARGET[0]);
    expect(panned.target[1]).toBeCloseTo(TARGET[1], 9);
    expect(panned.target[2]).toBeCloseTo(TARGET[2], 9);
  });
});

describe("the engraving", () => {
  it("builds rotation matrices from (w, x, y, z) quaternions", () => {
    const half = Math.SQRT1_2;
    // 90° about z: x → y
    const m = rotation([half, 0, 0, half]);
    expect(m[0]).toBeCloseTo(0, 9);
    expect(m[3]).toBeCloseTo(1, 9);
    expect(rotation([2, 0, 0, 0])).toEqual([1, 0, 0, 0, 1, 0, 0, 0, 1]);
  });

  it("projects orthographically: frontal puts +y to the right, up is up", () => {
    const view = { azimuth: 0, elevation: 0, scale: 100, origin: [200, 400] as const, target: [0, 0, 0] as [number, number, number] };
    const { right, up } = viewBasis(view);
    expect(right[1]).toBeCloseTo(1, 9);
    expect(up[2]).toBeCloseTo(1, 9);
    expect(projectPoint(view, [0, 0.5, 1])).toEqual([250, 300, 0]);
  });

  it("draws every non-floor geom at its body's recorded pose, far to near", () => {
    const model = decodeLaboratoryModelResponse(structuredClone(LABORATORY_MODEL)) as LaboratoryModelResponse;
    const columns = new Map<string, Float64Array>();
    for (const body of model.bodies) {
      columns.set(`${body.name}.px`, Float64Array.from([0]));
      columns.set(`${body.name}.py`, Float64Array.from([body.name.endsWith("_l") ? 0.1 : body.name.endsWith("_r") ? -0.1 : 0]));
      columns.set(`${body.name}.pz`, Float64Array.from([1]));
      columns.set(`${body.name}.qw`, Float64Array.from([1]));
      for (const axis of ["qx", "qy", "qz"]) columns.set(`${body.name}.${axis}`, Float64Array.from([0]));
    }
    const pose: LaboratoryFrameTable = { group: "pose", count: 1, t: Float64Array.from([0]), columns };
    const items = engrave(model, pose, 0, { azimuth: -90, elevation: 0, scale: 200, origin: [200, 400], target: [0, 0, 0] });

    expect(items).toHaveLength(model.geoms.length - 1);
    expect(items.every((item, i) => i === 0 || items[i - 1]!.depth <= item.depth)).toBe(true);
    const head = items.find((item) => item.geom === "head_geom");
    expect(head?.kind).toBe("ellipse");
    const sole = items.find((item) => item.role === "sole");
    expect(sole?.kind).toBe("dot");
  });
});
