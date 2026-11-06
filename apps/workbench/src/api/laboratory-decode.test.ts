/**
 * The laboratory read-model decoders: the real published answers are accepted exactly, and a
 * body that is not the published contract is refused rather than repaired.
 */

import { describe, expect, it } from "vitest";

import {
  LABORATORY_ABLATION,
  LABORATORY_INDEX,
  LABORATORY_MODEL,
  LABORATORY_NOMINAL,
} from "../test/laboratory-fixtures";
import {
  decodeLaboratoryIndexResponse,
  decodeLaboratoryModelResponse,
  decodeLaboratoryRecordingResponse,
  measuredPhases,
  summaryNumber,
} from "./laboratory-decode";

type Json = Record<string, unknown>;
const clone = <T>(value: T): T => structuredClone(value);
const index = () => clone(LABORATORY_INDEX) as Json;
const model = () => clone(LABORATORY_MODEL) as Json;
const nominal = () => clone(LABORATORY_NOMINAL) as Json;

describe("the laboratory index", () => {
  it("accepts the published index: four recordings, the claim and the manifest pin", () => {
    const decoded = decodeLaboratoryIndexResponse(index());

    expect(decoded).not.toBeNull();
    expect(decoded?.recordings.map((entry) => entry.recording_id)).toEqual([
      "repetition",
      "repetition-half-timestep",
      "ablation-no-internal-model",
      "ablation-soft-friction",
    ]);
    expect(decoded?.recordings[0]).toMatchObject({ kind: "nominal", checks_passed: 22, checks_failed: 0 });
    expect(decoded?.claim).toMatch(/not sealed DynamisBench evidence/);
    expect(decoded?.manifest_sha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it("drops fields the contract does not name", () => {
    const body = index();
    body.extra = "not part of the contract";
    (body.recordings as Json[])[0]!.extra = 1;

    const decoded = decodeLaboratoryIndexResponse(body) as unknown as Json;

    expect(decoded).not.toHaveProperty("extra");
    expect((decoded.recordings as Json[])[0]).not.toHaveProperty("extra");
  });

  it.each([
    ["an unknown recording kind", (body: Json) => ((body.recordings as Json[])[0]!.kind = "sealed")],
    ["a digest that is not sha-256 hex", (body: Json) => ((body.recordings as Json[])[0]!.trajectory_sha256 = "D3B4")],
    ["a negative check count", (body: Json) => ((body.recordings as Json[])[0]!.checks_failed = -1)],
    ["a duplicated recording", (body: Json) => (body.recordings as Json[]).push((body.recordings as Json[])[0]!)],
    ["no recordings", (body: Json) => (body.recordings = [])],
    ["a recording id with a path in it", (body: Json) => ((body.recordings as Json[])[0]!.recording_id = "../model")],
    ["a non-finite plan value", (body: Json) => ((body.plan as Json).descent_s = Number.NaN)],
  ])("refuses %s", (_label, corrupt) => {
    const body = index();
    corrupt(body);

    expect(decodeLaboratoryIndexResponse(body)).toBeNull();
  });
});

describe("the laboratory model", () => {
  it("accepts the compiled model: 17 bodies, 33 geoms, 29 joints, 95 kg", () => {
    const decoded = decodeLaboratoryModelResponse(model());

    expect(decoded?.bodies).toHaveLength(17);
    expect(decoded?.geoms).toHaveLength(33);
    expect(decoded?.joints).toHaveLength(29);
    expect(decoded?.total_mass_kg).toBeCloseTo(95, 9);
    expect(decoded?.subject).toEqual({
      body_mass_kg: 75,
      stature_m: 1.75,
      barbell_mass_kg: 20,
      grip_half_width_m: 0.48,
    });
    expect(decoded?.sole_points).toEqual(["heel_lateral", "heel_medial", "met1", "met5", "hallux"]);
  });

  it.each([
    ["a geom on a body the model does not describe", (body: Json) => ((body.geoms as Json[])[1]!.body = "tail")],
    ["a joint range that is inverted", (body: Json) => ((body.joints as Json[])[0]!.range_deg = [50, -25])],
    ["an unknown geom type", (body: Json) => ((body.geoms as Json[])[1]!.type = "mesh")],
    ["a short quaternion", (body: Json) => ((body.geoms as Json[])[1]!.quaternion = [1, 0, 0])],
    ["a missing contact block", (body: Json) => delete body.contact],
  ])("refuses %s", (_label, corrupt) => {
    const body = model();
    corrupt(body);

    expect(decodeLaboratoryModelResponse(body)).toBeNull();
  });
});

describe("a laboratory recording", () => {
  it("accepts the nominal recording with its checks, ledger and frame catalogue", () => {
    const decoded = decodeLaboratoryRecordingResponse(nominal());

    expect(decoded?.recording_id).toBe("repetition");
    expect(decoded?.checks).toHaveLength(22);
    expect(decoded?.checks.every((check) => check.status === "pass")).toBe(true);
    expect(Object.keys(decoded?.work ?? {}).sort()).toEqual(["ascent", "bottom", "descent", "return", "standing"]);
    expect(decoded?.frame_groups.pose).toContain("barbell.qw");
    expect(decoded?.frame_groups.kinetics).toContain("cop_left.x");
    expect(decoded?.frame_groups.kinetics).toContain("contact.l_heel_medial.x");
    expect(decoded?.sample_period_s).toBe(0.01);
  });

  it("accepts an ablation with its failed and unevaluated checks", () => {
    const decoded = decodeLaboratoryRecordingResponse(clone(LABORATORY_ABLATION));
    const statuses = decoded?.checks.map((check) => check.status) ?? [];

    expect(statuses.filter((status) => status === "fail")).toHaveLength(6);
    expect(statuses.filter((status) => status === "not_evaluated")).toHaveLength(3);
    expect(decoded?.checks.find((check) => check.criterion_id === "heel")).toMatchObject({ status: "fail" });
  });

  it("reads published summary numbers by path, and nothing else", () => {
    const decoded = decodeLaboratoryRecordingResponse(nominal());
    const summary = decoded!.summary;

    expect(summaryNumber(summary, "bottom.knee_flexion_deg")).toBeCloseTo(120.09, 2);
    expect(summaryNumber(summary, "torques.knee_flexion_l.peak_extensor_nm_per_kg")).toBeCloseTo(1.577, 3);
    expect(summaryNumber(summary, "bottom")).toBeNull();
    expect(summaryNumber(summary, "bottom.absent")).toBeNull();
    expect(summaryNumber(summary, "balance.com_x_range_m")).toBeNull();
    expect(measuredPhases(summary).map((span) => span.phase)).toEqual([
      "standing",
      "descent",
      "bottom",
      "ascent",
      "standing",
    ]);
  });

  it.each([
    ["a check whose status and value disagree", (body: Json) => ((body.checks as Json[])[0]!.value = null)],
    ["an unknown check status", (body: Json) => ((body.checks as Json[])[0]!.status = "sealed")],
    ["a zero sample period", (body: Json) => (body.sample_period_s = 0)],
    ["a frame group missing", (body: Json) => delete (body.frame_groups as Json).pose],
    ["a column name with markup", (body: Json) => ((body.frame_groups as Json).pose as string[]).push("<script>")],
    ["a summary leaf that is null", (body: Json) => ((body.summary as Json).bottom = null)],
    ["a work entry that is not numeric", (body: Json) => (((body.work as Json).descent as Json).positive_j = "a lot")],
    ["a phase span that ends before it starts", (body: Json) => ((body.phase_spans as Json[])[0]!.end_s = -1)],
  ])("refuses %s", (_label, corrupt) => {
    const body = nominal();
    corrupt(body);

    expect(decodeLaboratoryRecordingResponse(body)).toBeNull();
  });

  it("refuses a summary nested beyond the bound", () => {
    const body = nominal();
    let deep: Json = { value: 1 };
    for (let i = 0; i < 10; i += 1) {
      deep = { deeper: deep };
    }
    (body.summary as Json).deep = deep;

    expect(decodeLaboratoryRecordingResponse(body)).toBeNull();
  });
});
