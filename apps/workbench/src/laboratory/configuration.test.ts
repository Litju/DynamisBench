/**
 * Factor presentation: display conversions are the run service's own arithmetic, typed values
 * are never clipped or snapped, and a preset is recognised only when every double matches.
 */

import { describe, expect, it } from "vitest";

import { decodeStudyCatalogueResponse } from "../api/run-decode";
import type { CatalogueStudy } from "../api/run-types";
import { RUN_CATALOGUE } from "../test/run-fixtures";
import {
  describeConfiguration,
  factorProblem,
  formatDisplay,
  fromDisplay,
  matchingPreset,
  nominalDraft,
  parseDisplay,
  presetValues,
  sameConfiguration,
  toDisplay,
} from "./configuration";

const study = decodeStudyCatalogueResponse(structuredClone(RUN_CATALOGUE))!.studies[0] as CatalogueStudy;
const factor = (id: string) => study.factors.find((entry) => entry.factor_id === id)!;

describe("display conversion", () => {
  it("turns a typed 120° into exactly the double the qualified upper bound is", () => {
    const depth = factor("f.squat.bottom-knee-flexion");
    expect(fromDisplay("degree", 120)).toBe(depth.upper);
    expect(fromDisplay("degree", 90)).toBe(depth.lower);
    expect(formatDisplay(depth, depth.nominal)).toBe("120");
  });

  it("shows time constants in ms and sends them in s", () => {
    const friction = factor("f.squat.sole-friction-time-constant");
    expect(toDisplay("millisecond", friction.nominal)).toBe(2);
    expect(fromDisplay("millisecond", 15)).toBe(friction.upper);
  });

  it("parses only plain numbers", () => {
    expect(parseDisplay(" 95.5 ")).toBe(95.5);
    expect(parseDisplay("−3")).toBe(-3);
    for (const text of ["", "1e400", "12abc", "0x10", "NaN", "Infinity", "1,5"]) {
      expect(parseDisplay(text)).toBeNull();
    }
  });
});

describe("admissibility", () => {
  it("reports a value outside the qualified range without changing it", () => {
    const depth = factor("f.squat.bottom-knee-flexion");
    expect(factorProblem(depth, fromDisplay("degree", 130))).toMatch(/outside the qualified range 90–120 °/);
    expect(factorProblem(depth, Number.NaN)).toBe("a number is required");
    expect(factorProblem(depth, depth.nominal)).toBeNull();
  });

  it("admits a discrete factor only at a published value", () => {
    const timestep = factor("f.squat.integration-timestep");
    expect(factorProblem(timestep, 0.0005)).toBeNull();
    expect(factorProblem(timestep, 0.0003)).toBe("choose one of the admissible values");
  });
});

describe("presets", () => {
  it("applies a preset over the nominal configuration and recognises it exactly", () => {
    const values = presetValues(study, "slow-tempo");
    expect(values["f.squat.descent-duration"]).toBe(2);
    expect(values["f.squat.bottom-knee-flexion"]).toBe(factor("f.squat.bottom-knee-flexion").nominal);
    expect(matchingPreset(study, values)).toBe("slow-tempo");
    expect(matchingPreset(study, { ...values, "f.squat.descent-duration": 2.0000000001 })).toBe("custom");
    expect(nominalDraft(study)).toMatchObject({ studyId: study.study_id, caseId: "nominal" });
  });

  it("compares configurations double for double", () => {
    const a = presetValues(study, "nominal");
    expect(sameConfiguration(a, { ...a })).toBe(true);
    expect(sameConfiguration(a, { ...a, "f.squat.internal-model-gain": 0.9999999999 })).toBe(false);
    expect(describeConfiguration(study.factors, a)).toBe(
      "bottom-knee-flexion 120° · descent-duration 1.5 s · ascent-duration 1.2 s · integration-timestep 1 ms · internal-model-gain 1 · sole-friction-time-constant 2 ms",
    );
  });
});
