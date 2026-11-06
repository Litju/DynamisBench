/**
 * Frame groups: the one place the laboratory turns an Arrow IPC stream into typed columns.
 *
 * The client answers a frame request with bytes; this module decodes them through the Arrow
 * transport utility (loaded on demand) and checks the result is the table the recording's
 * catalogue promised: a `t` column, exactly the catalogued columns, the catalogued row count,
 * and times on the recording's sample grid. A table that is not is refused, never repaired.
 */

import { queryOptions } from "@tanstack/react-query";

import type { ApiClient } from "../api/client";
import type {
  LaboratoryFrameGroup,
  LaboratoryFrameTable,
  LaboratoryRecordingResponse,
} from "../api/laboratory-types";
import { LABORATORY_QUERY_TIMING, RUN_QUERY_TIMING, apiQueryKeys } from "../api/queries";
import { decodeArrowFloatColumns } from "../arrow/arrow";

export class FrameTableError extends Error {
  constructor(reason: string) {
    super(`The frame group was refused: ${reason}.`);
    this.name = "FrameTableError";
  }
}

/** Grid tolerance: times are stored to nanosecond resolution by the publisher. */
const GRID_TOLERANCE_S = 1e-6;

/**
 * Refuse a time column that is not the recording's sample grid, every row included.
 *
 * Snapshots are taken at exactly t = k × period from t = 0, through the end of the run: the
 * last row is the last grid instant at or before the published duration (a run that ends
 * between two grid instants has its final state closing the work ledger, not a row). A time
 * that is not finite, repeats, runs backwards, leaves the grid, or stops short of the duration
 * by a period or more is a corrupt or truncated table — never something to re-grid.
 */
export function timestampRefusal(t: Float64Array, period: number, duration: number): void {
  const count = t.length;
  if (count === 0 || !(period > 0) || !Number.isFinite(duration)) {
    throw new FrameTableError("it has no time base");
  }
  for (let i = 0; i < count; i += 1) {
    const value = t[i] ?? Number.NaN;
    if (!Number.isFinite(value)) {
      throw new FrameTableError("a time is not finite");
    }
    if (i > 0 && !(value > (t[i - 1] ?? Number.NaN))) {
      throw new FrameTableError("its times do not strictly increase");
    }
    if (Math.abs(value - i * period) > GRID_TOLERANCE_S) {
      throw new FrameTableError("its times are not on the sample grid");
    }
  }
  const last = t[count - 1] ?? Number.NaN;
  if (last > duration + GRID_TOLERANCE_S) {
    throw new FrameTableError("it has a time after the end of the recording");
  }
  if (duration - last >= period - GRID_TOLERANCE_S) {
    throw new FrameTableError("it ends before the last sample instant of the recording");
  }
}

/** Decode and check one frame group against the recording that catalogued it. */
export async function decodeFrameTable(
  recording: Pick<
    LaboratoryRecordingResponse,
    "frame_count" | "sample_period_s" | "frame_groups" | "duration_s"
  >,
  group: LaboratoryFrameGroup,
  payload: Uint8Array,
): Promise<LaboratoryFrameTable> {
  const decoded = await decodeArrowFloatColumns(payload);
  const expected = recording.frame_groups[group];
  const t = decoded.columns.get("t");
  if (t === undefined || decoded.names[0] !== "t") {
    throw new FrameTableError("it has no leading time column");
  }
  if (decoded.numRows !== recording.frame_count) {
    throw new FrameTableError("its row count is not the recording's frame count");
  }
  const names = decoded.names.slice(1);
  if (names.length !== expected.length || names.some((name, i) => name !== expected[i])) {
    throw new FrameTableError("its columns are not the recording's catalogue");
  }
  timestampRefusal(t, recording.sample_period_s, recording.duration_s);
  for (const values of decoded.columns.values()) {
    for (const value of values) {
      if (!Number.isFinite(value)) {
        throw new FrameTableError("it carries a non-finite value");
      }
    }
  }
  const columns = new Map<string, Float64Array>();
  for (const name of names) {
    const values = decoded.columns.get(name);
    if (values !== undefined) {
      columns.set(name, values);
    }
  }
  return { group, count: decoded.numRows, t, columns };
}

/** One frame group of one recording, read and decoded once per session. */
export function laboratoryFramesOptions(
  client: ApiClient,
  recording: LaboratoryRecordingResponse,
  group: LaboratoryFrameGroup,
) {
  return queryOptions<LaboratoryFrameTable>({
    queryKey: apiQueryKeys.laboratoryFrames(recording.recording_id, group),
    queryFn: async () =>
      decodeFrameTable(
        recording,
        group,
        await client.laboratoryFrames(recording.recording_id, group),
      ),
    ...LABORATORY_QUERY_TIMING,
  });
}

/** One frame group of one verified run, read through the run service and decoded the same way. */
export function runFramesOptions(
  client: ApiClient,
  workspaceId: string,
  recording: LaboratoryRecordingResponse,
  group: LaboratoryFrameGroup,
) {
  return queryOptions<LaboratoryFrameTable>({
    queryKey: apiQueryKeys.runFrames(workspaceId, recording.recording_id, group),
    queryFn: async () =>
      decodeFrameTable(
        recording,
        group,
        await client.runFrames(workspaceId, recording.recording_id, group),
      ),
    ...RUN_QUERY_TIMING,
  });
}
