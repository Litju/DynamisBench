/**
 * The run read-model decoders accept exactly what the run service publishes (the real answers
 * of a real squat workspace) and refuse forged, truncated or inconsistent bodies.
 */

import { describe, expect, it } from "vitest";

import {
  RUN_CATALOGUE,
  RUN_EVIDENCE,
  RUN_EVIDENCE_ABLATION,
  RUN_EVIDENCE_REJECTED,
  RUN_LIST,
  RUN_MODEL,
  RUN_PREFLIGHT,
  RUN_PROGRESS_COMPLETED,
  RUN_RECORDING,
  RUN_STARTED,
} from "../test/run-fixtures";
import { decodeLaboratoryModelResponse, decodeLaboratoryRecordingResponse } from "./laboratory-decode";
import {
  RUN_ID,
  decodePreflightResponse,
  decodeRunEvidenceResponse,
  decodeRunListResponse,
  decodeRunProgressResponse,
  decodeStudyCatalogueResponse,
} from "./run-decode";

type Mutable = Record<string, unknown>;
const copy = (value: unknown): Mutable => structuredClone(value) as Mutable;

describe("the study catalogue", () => {
  it("accepts the published catalogue with its factors, choices and presets", () => {
    const catalogue = decodeStudyCatalogueResponse(copy(RUN_CATALOGUE));
    expect(catalogue).not.toBeNull();
    const study = catalogue!.studies[0]!;
    expect(study.study_id).toBe("st.squat.configuration");
    expect(study.executable).toBe(true);
    expect(study.factors.map((factor) => factor.display)).toEqual(["degree", "second", "second", "millisecond", "unitless", "millisecond"]);
    const timestep = study.factors.find((factor) => factor.factor_id === "f.squat.integration-timestep")!;
    expect(timestep.choices).toContain(0.001);
    expect(timestep.choices).toContain(0.00025);
    expect(timestep.choices.every((choice) => Math.abs(Math.round(0.01 / choice) * choice - 0.01) < 1e-12)).toBe(true);
    expect(study.limitations.length).toBeGreaterThan(3);
  });

  it("refuses a nominal outside its own range and a preset naming an unknown factor", () => {
    const outside = copy(RUN_CATALOGUE);
    ((outside.studies as Mutable[])[0]!.factors as Mutable[])[0]!.nominal = 9;
    expect(decodeStudyCatalogueResponse(outside)).toBeNull();

    const unknown = copy(RUN_CATALOGUE);
    ((unknown.studies as Mutable[])[0]!.presets as Mutable).forged = { "f.nothing": 1 };
    expect(decodeStudyCatalogueResponse(unknown)).toBeNull();

    const display = copy(RUN_CATALOGUE);
    ((display.studies as Mutable[])[0]!.factors as Mutable[])[0]!.display = "furlong";
    expect(decodeStudyCatalogueResponse(display)).toBeNull();
  });
});

describe("preflight and progress", () => {
  it("accepts a ready preflight with its identities", () => {
    const report = decodePreflightResponse(copy(RUN_PREFLIGHT));
    expect(report?.decision).toBe("ready");
    expect(report?.adapter.implementation_digest).toMatch(/^[0-9a-f]{64}$/);
    expect(Object.keys(report?.definitions ?? {}).sort()).toEqual([
      "benchmark",
      "environment",
      "realization",
      "scenario",
      "system_under_test",
    ]);
  });

  it("refuses a ready decision that carries refusals and a refused one that carries none", () => {
    const ready = copy(RUN_PREFLIGHT);
    ready.refusals = [{ code: "asset_digest_mismatch", message: "x" }];
    expect(decodePreflightResponse(ready)).toBeNull();
    const refused = copy(RUN_PREFLIGHT);
    refused.decision = "refused";
    expect(decodePreflightResponse(refused)).toBeNull();
  });

  it("accepts progress and refuses a run identifier that is not the service's", () => {
    expect(decodeRunProgressResponse(copy(RUN_STARTED))?.state).toBe("preflight");
    expect(decodeRunProgressResponse(copy(RUN_PROGRESS_COMPLETED))?.active).toBe(false);
    for (const forged of ["../etc", "run-xyz-001", "run-0123456789-1", ""]) {
      expect(RUN_ID.test(forged)).toBe(false);
      const progress = copy(RUN_STARTED);
      progress.run_id = forged;
      expect(decodeRunProgressResponse(progress)).toBeNull();
    }
    const state = copy(RUN_STARTED);
    state.state = "teleporting";
    expect(decodeRunProgressResponse(state)).toBeNull();
  });
});

describe("the run list", () => {
  it("accepts verified, failing and rejected runs with their counts", () => {
    const list = decodeRunListResponse(copy(RUN_LIST));
    expect(list?.runs.map((run) => run.status).sort()).toEqual(["rejected", "verified", "verified"]);
    const rejected = list!.runs.find((run) => run.status === "rejected")!;
    expect(rejected.trajectory_sha256).toBeNull();
    expect(rejected.reasons[0]).toMatch(/derived bundle/);
  });

  it("refuses duplicate runs and a progress record of another run", () => {
    const duplicated = copy(RUN_LIST);
    duplicated.runs = [...(duplicated.runs as unknown[]), (duplicated.runs as unknown[])[0]];
    expect(decodeRunListResponse(duplicated)).toBeNull();
    const mismatched = copy(RUN_LIST);
    const withProgress = (mismatched.runs as Mutable[]).find((run) => run.progress !== null)!;
    (withProgress.progress as Mutable).run_id = "run-0000000000-001";
    expect(decodeRunListResponse(mismatched)).toBeNull();
  });
});

describe("run evidence", () => {
  it("projects a verified run's seals, provenance, verification and assessment", () => {
    const evidence = decodeRunEvidenceResponse(copy(RUN_EVIDENCE))!;
    expect(evidence.status).toBe("verified");
    expect(evidence.execution.valid && evidence.derived.valid).toBe(true);
    expect(evidence.provenance?.execution_evidence_digest).toBe(evidence.execution.evidence_digest);
    expect(evidence.provenance?.trajectory_sha256?.startsWith("d3b4edafc090")).toBe(true);
    expect(evidence.verification).toHaveLength(11);
    expect(evidence.metrics.length).toBeGreaterThan(10);
    expect(evidence.adapter_checks.length).toBeGreaterThan(10);
    expect(evidence.claim).toMatch(/Neither is validation/);
    expect(Object.keys(evidence.provenance!.definitions).sort()).toContain("study");
  });

  it("projects a verified run whose criteria fail, without hiding the failures", () => {
    const evidence = decodeRunEvidenceResponse(copy(RUN_EVIDENCE_ABLATION))!;
    expect(evidence.status).toBe("verified");
    expect(evidence.metrics.filter((metric) => metric.status === "fail").length).toBeGreaterThan(0);
  });

  it("projects a rejected run as reasons and invalid seals, with no provenance", () => {
    const evidence = decodeRunEvidenceResponse(copy(RUN_EVIDENCE_REJECTED))!;
    expect(evidence.status).toBe("rejected");
    expect(evidence.derived.valid).toBe(false);
    expect(evidence.provenance).toBeNull();
    expect(evidence.verification).toEqual([]);
    expect(evidence.reasons.join(" ")).toMatch(/canonical\/series\.parquet/);
  });

  it("refuses a body that calls itself verified without seals or verification", () => {
    const forged = copy(RUN_EVIDENCE);
    (forged.derived as Mutable).valid = false;
    expect(decodeRunEvidenceResponse(forged)).toBeNull();
    const empty = copy(RUN_EVIDENCE);
    empty.verification = [];
    expect(decodeRunEvidenceResponse(empty)).toBeNull();
    const digest = copy(RUN_EVIDENCE);
    ((digest.provenance as Mutable).execution as Mutable).evidence_digest = "not-a-digest";
    expect(decodeRunEvidenceResponse(digest)).toBeNull();
    const path = copy(RUN_EVIDENCE);
    ((path.execution as Mutable).files as Mutable[])[0]!.path = "../../etc/passwd";
    expect(decodeRunEvidenceResponse(path)).toBeNull();
  });
});

describe("a run as a laboratory recording", () => {
  it("is the packaged recording's shape, of kind run, with its own model", () => {
    const recording = decodeLaboratoryRecordingResponse(copy(RUN_RECORDING));
    expect(recording?.kind).toBe("run");
    expect(recording?.checks.some((check) => check.group === "Verification")).toBe(true);
    expect(recording?.checks.some((check) => check.group === "Benchmark metrics")).toBe(true);
    const model = decodeLaboratoryModelResponse(copy(RUN_MODEL));
    expect(model?.bodies.every((body) => body.position_m.length === 3 && body.quaternion.length === 4)).toBe(true);
  });
});
