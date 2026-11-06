/**
 * The laboratory store: one clock, one selection, bounded pinning, nothing persisted.
 */

import { afterEach, describe, expect, it } from "vitest";

import { decodeLaboratoryModelResponse } from "../api/laboratory-decode";
import type { LaboratoryModelResponse } from "../api/laboratory-types";
import { LABORATORY_MODEL } from "../test/laboratory-fixtures";
import { bodyLabel, bodyTree, jointName, marginaliaFor } from "./anatomy";
import { primaryJointOf } from "./stage/stage";
import { MAX_PINNED, resetLaboratoryStore, useLaboratoryStore } from "./store";

afterEach(() => resetLaboratoryStore());

const TIMEBASE = { period: 0.01, count: 551, duration: 5.5 };

describe("the laboratory clock", () => {
  it("seeks to the nearest recorded frame and keeps time and frame together", () => {
    const store = useLaboratoryStore.getState();
    store.setTimebase(TIMEBASE);
    store.seek(2.2049);

    expect(useLaboratoryStore.getState().frame).toBe(220);
    store.seekFrame(999);
    expect(useLaboratoryStore.getState()).toMatchObject({ frame: 550, time: 5.5 });
    store.stepFrame(-10);
    expect(useLaboratoryStore.getState().frame).toBe(540);
  });

  it("plays from the start when play is pressed on the last frame, and stops at the end", () => {
    const store = useLaboratoryStore.getState();
    store.setTimebase(TIMEBASE);
    store.seekFrame(550);
    store.togglePlay();
    expect(useLaboratoryStore.getState()).toMatchObject({ playing: true, frame: 0 });

    useLaboratoryStore.setState({ loop: false });
    store.seek(5.45);
    useLaboratoryStore.getState().tick(0.1);
    expect(useLaboratoryStore.getState()).toMatchObject({ playing: false, time: 5.5, frame: 550 });
  });

  it("pauses on a frame step and on a change of recording", () => {
    const store = useLaboratoryStore.getState();
    store.setTimebase(TIMEBASE);
    store.togglePlay();
    store.stepFrame(1);
    expect(useLaboratoryStore.getState().playing).toBe(false);
    store.togglePlay();
    store.setRecording({ source: "dataset", id: "ablation-no-internal-model" });
    expect(useLaboratoryStore.getState()).toMatchObject({
      playing: false,
      recording: { source: "dataset", id: "ablation-no-internal-model" },
    });
  });
});

describe("the bound workspace", () => {
  it("drops runs of the previous workspace, keeps packaged recordings and clears the draft", () => {
    const store = useLaboratoryStore.getState();
    store.setWorkspace("w-1");
    store.setRecording({ source: "run", id: "run-0123456789-001" });
    store.setCompare({ source: "dataset", id: "repetition" });
    store.setDraft({ studyId: "st.x", caseId: "nominal", values: { "f.x": 1 } });
    store.setActiveRun("run-0123456789-001");
    store.inspectEvidence("run-0123456789-001");

    useLaboratoryStore.getState().setWorkspace("w-2");

    expect(useLaboratoryStore.getState()).toMatchObject({
      workspaceId: "w-2",
      recording: null,
      compare: { source: "dataset", id: "repetition" },
      draft: null,
      activeRunId: null,
      evidenceRunId: null,
    });
  });

  it("does nothing when the same workspace is bound again", () => {
    const store = useLaboratoryStore.getState();
    store.setWorkspace("w-1");
    store.setRecording({ source: "run", id: "run-0123456789-001" });
    useLaboratoryStore.getState().setWorkspace("w-1");
    expect(useLaboratoryStore.getState().recording).toEqual({ source: "run", id: "run-0123456789-001" });
  });
});

describe("the dock", () => {
  it("pins at most three plots, dropping the oldest, and never unpins the last", () => {
    const store = useLaboratoryStore.getState();
    expect(useLaboratoryStore.getState().pinned).toEqual(["kinematics", "kinetics", "ground"]);
    store.togglePinned("contact");
    expect(useLaboratoryStore.getState().pinned).toEqual(["kinetics", "ground", "contact"]);
    expect(useLaboratoryStore.getState().pinned).toHaveLength(MAX_PINNED);
    store.togglePinned("kinetics");
    store.togglePinned("ground");
    store.togglePinned("contact");
    expect(useLaboratoryStore.getState().pinned).toEqual(["contact"]);
  });
});

describe("the store is presentation only", () => {
  it("holds no server data and carries no persistence", () => {
    const state = useLaboratoryStore.getState() as unknown as Record<string, unknown>;
    for (const key of ["index", "model", "frames", "checks", "runs", "evidence", "catalogue", "preflight"]) {
      expect(state).not.toHaveProperty(key);
    }
    // The recording on show is a reference (source and identifier), never the read model.
    useLaboratoryStore.getState().setRecording({ source: "dataset", id: "repetition" });
    expect(Object.keys(useLaboratoryStore.getState().recording ?? {}).sort()).toEqual(["id", "source"]);
    expect((useLaboratoryStore as unknown as Record<string, unknown>).persist).toBeUndefined();
  });
});

describe("names", () => {
  it("names joints as a reader expects, in English and in the plate's Latin", () => {
    expect(jointName("knee_flexion_l")).toMatchObject({ title: "Knee · left", latin: "genu sinistrum", short: "knee flexion · L" });
    expect(jointName("hip_flexion_r").latin).toBe("coxa dextra");
    expect(jointName("ankle_dorsiflexion_l").latin).toBe("talus sinister");
    expect(jointName("hip_adduction_r").title).toBe("Hip adduction · right");
    expect(jointName("lumbar_flexion").title).toBe("Lumbar spine · flexion");
    expect(bodyLabel("upper_arm_l")).toBe("Upper arm L");
    expect(bodyLabel("torso_middle")).toBe("Torso — middle");
  });

  it("orders bodies from the root and selects a body's sagittal hinge", () => {
    const model = decodeLaboratoryModelResponse(structuredClone(LABORATORY_MODEL)) as LaboratoryModelResponse;
    const tree = bodyTree(model);

    expect(tree[0]?.body.name).toBe("pelvis");
    expect(tree.find((node) => node.body.name === "shank_l")?.depth).toBe(2);
    expect(tree).toHaveLength(model.bodies.length);
    expect(primaryJointOf(model.joints, "thigh_l")).toBe("hip_flexion_l");
    expect(primaryJointOf(model.joints, "foot_r")).toBe("ankle_dorsiflexion_r");
    expect(primaryJointOf(model.joints, "barbell")).toBeNull();
    expect(marginaliaFor("knee_flexion_r")).toEqual(["hip_flexion_r", "knee_flexion_r", "ankle_dorsiflexion_r"]);
    expect(marginaliaFor("lumbar_flexion")[0]).toBe("lumbar_flexion");
  });
});
