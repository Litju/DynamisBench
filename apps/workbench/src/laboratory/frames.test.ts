/**
 * Frame tables are accepted only as the recording catalogued them.
 */

import { describe, expect, it } from "vitest";

import { decodeLaboratoryRecordingResponse } from "../api/laboratory-decode";
import type { LaboratoryRecordingResponse } from "../api/laboratory-types";
import { LABORATORY_NOMINAL, frameStream } from "../test/laboratory-fixtures";
import { FrameTableError, decodeFrameTable, timestampRefusal } from "./frames";

const recording = decodeLaboratoryRecordingResponse(structuredClone(LABORATORY_NOMINAL)) as LaboratoryRecordingResponse;

async function refusal(payload: Uint8Array): Promise<string> {
  try {
    await decodeFrameTable(recording, "kinematics", payload);
  } catch (error) {
    if (error instanceof FrameTableError) {
      return error.message;
    }
    throw error;
  }
  return "accepted";
}

describe("decodeFrameTable", () => {
  it("accepts the catalogued group: one row per snapshot, every catalogued column", async () => {
    const table = await decodeFrameTable(recording, "kinematics", frameStream(recording, "kinematics"));

    expect(table.count).toBe(551);
    expect(table.t[100]).toBeCloseTo(1.0, 9);
    expect([...table.columns.keys()]).toEqual(recording.frame_groups.kinematics);
    expect(table.columns.has("t")).toBe(false);
  });

  it("refuses a table of another length", async () => {
    expect(await refusal(frameStream(recording, "kinematics", { rows: 550 }))).toMatch(/row count/);
  });

  it("refuses a table whose columns are not the catalogue", async () => {
    const names = ["t", ...recording.frame_groups.kinematics.slice(1)];
    expect(await refusal(frameStream(recording, "kinematics", { names }))).toMatch(/catalogue/);
  });

  it("refuses a table without a leading time column", async () => {
    const names = [...recording.frame_groups.kinematics, "t"];
    expect(await refusal(frameStream(recording, "kinematics", { names }))).toMatch(/time column/);
  });

  it("refuses times off the sample grid", async () => {
    expect(await refusal(frameStream(recording, "kinematics", { time: (i) => i * 0.011 }))).toMatch(/grid/);
  });

  it("validates every row, not only the first ones", async () => {
    // One late row off the grid, one repeated time, one NaN: each is refused wherever it is.
    expect(await refusal(frameStream(recording, "kinematics", { time: (i) => (i === 540 ? i * 0.01 + 0.004 : i * 0.01) }))).toMatch(/grid/);
    expect(await refusal(frameStream(recording, "kinematics", { time: (i) => (i === 300 ? 2.99 : i * 0.01) }))).toMatch(/strictly increase|grid/);
    expect(await refusal(frameStream(recording, "kinematics", { time: (i) => (i === 200 ? Number.NaN : i * 0.01) }))).toMatch(/finite/);
  });
});

describe("timestampRefusal", () => {
  const grid = (count: number, period = 0.01) => Float64Array.from({ length: count }, (_, i) => Number((i * period).toFixed(9)));

  it("accepts a run whose duration ends between two grid instants (the last row is the last instant before it)", () => {
    // The half-timestep companion ends at 5.5005 s: its last row is 5.5 s.
    expect(() => timestampRefusal(grid(551), 0.01, 5.5005)).not.toThrow();
    // A run ending exactly on the grid has its last row at the duration.
    expect(() => timestampRefusal(grid(551), 0.01, 5.5)).not.toThrow();
    // The ablations end at 5.537 s: their last row is 5.53 s.
    expect(() => timestampRefusal(grid(554), 0.01, 5.537)).not.toThrow();
  });

  it("refuses a truncated table that stops a period or more before the duration", () => {
    expect(() => timestampRefusal(grid(540), 0.01, 5.5)).toThrow(/ends before the last sample instant/);
    expect(() => timestampRefusal(grid(550), 0.01, 5.5)).toThrow(/ends before/);
  });

  it("refuses a time after the end of the recording", () => {
    expect(() => timestampRefusal(grid(552), 0.01, 5.5)).toThrow(/after the end/);
  });

  it("refuses an empty table, a non-positive period and a non-finite duration", () => {
    expect(() => timestampRefusal(new Float64Array(0), 0.01, 5.5)).toThrow(/no time base/);
    expect(() => timestampRefusal(grid(10), 0, 0.09)).toThrow(/no time base/);
    expect(() => timestampRefusal(grid(10), 0.01, Number.POSITIVE_INFINITY)).toThrow(/no time base/);
  });

  it("refuses a table that does not start at zero or runs backwards", () => {
    const shifted = grid(551).map((t) => t + 0.01);
    expect(() => timestampRefusal(shifted, 0.01, 5.51)).toThrow(/grid/);
    const backwards = grid(551);
    backwards[10] = backwards[9]!;
    expect(() => timestampRefusal(backwards, 0.01, 5.5)).toThrow(/strictly increase/);
  });
});
