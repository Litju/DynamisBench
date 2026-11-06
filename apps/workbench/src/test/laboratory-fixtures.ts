/**
 * Laboratory fixtures: the API's own read models and synthetic Arrow frame streams.
 *
 * The JSON files are the real `/api/v1/laboratory` answers for the packaged dataset, written
 * from the in-process API (see `python/tests/laboratory`); they change only with the dataset.
 * Frame streams are synthetic but exactly catalogued: the recording's own column names and
 * row count, a time column on its sample grid, and smooth deterministic values — enough to
 * exercise decoding, lookup and rendering without shipping megabytes of fixture.
 */

import { Field, Float64, RecordBatch, Schema, Struct, Table, makeData, tableToIPC } from "apache-arrow";

import indexFixture from "./fixtures/laboratory/index.json";
import modelFixture from "./fixtures/laboratory/model.json";
import ablationFixture from "./fixtures/laboratory/recording-ablation.json";
import nominalFixture from "./fixtures/laboratory/recording-repetition.json";

export const LABORATORY_INDEX: unknown = indexFixture;
export const LABORATORY_MODEL: unknown = modelFixture;
export const LABORATORY_NOMINAL: unknown = nominalFixture;
export const LABORATORY_ABLATION: unknown = ablationFixture;

export const ARROW_MEDIA_TYPE = "application/vnd.apache.arrow.stream";

interface Catalogue {
  readonly frame_count: number;
  readonly sample_period_s: number;
  readonly frame_groups: Record<string, readonly string[]>;
}

/** A deterministic, smooth value for a named column at row `i` (a squat-like bump). */
export function syntheticValue(name: string, i: number, count: number): number {
  const phase = Math.sin((Math.PI * i) / Math.max(1, count - 1)) ** 2;
  if (name.endsWith(".qw")) return 1;
  if (name.endsWith(".qx") || name.endsWith(".qy") || name.endsWith(".qz")) return 0;
  if (name.endsWith(".angle_deg") || name.endsWith(".reference_deg")) return 5 + 115 * phase;
  if (name.endsWith(".velocity_deg_s")) return 100 * Math.cos((Math.PI * i) / count);
  if (name.endsWith(".torque_nm")) return -20 - 80 * phase;
  if (name.endsWith(".normal_n")) return 93 + 10 * phase;
  if (name === "loaded_contacts") return 10;
  if (name === "heel_load_fraction") return 0.45;
  if (name === "grf_left.z" || name === "grf_right.z") return 466 + 100 * phase;
  if (name === "grf_planned_vertical_n") return 932 + 200 * phase;
  if (name.endsWith(".pz") || name === "com.z" || name === "bar.z") return 1.1 - 0.4 * phase;
  if (name.endsWith("margin_m")) return 0.09;
  return phase;
}

/** The Arrow IPC stream of one catalogued frame group, as the server would encode it. */
export function frameStream(
  recording: unknown,
  group: string,
  options: { rows?: number; names?: readonly string[]; nullable?: boolean; time?: (i: number) => number } = {},
): Uint8Array {
  const catalogue = recording as Catalogue;
  const count = options.rows ?? catalogue.frame_count;
  const names = options.names ?? ["t", ...(catalogue.frame_groups[group] ?? [])];
  const time = options.time ?? ((i: number) => Number((i * catalogue.sample_period_s).toFixed(9)));
  return floatStream(
    names.map((name) => {
      const values = new Float64Array(count);
      for (let i = 0; i < count; i += 1) {
        values[i] = name === "t" ? time(i) : syntheticValue(name, i, count);
      }
      return [name, values] as const;
    }),
    options.nullable ?? false,
  );
}

/** One Arrow IPC stream of named float64 columns, non-null unless asked otherwise. */
export function floatStream(columns: readonly (readonly [string, Float64Array])[], nullable = false): Uint8Array {
  const length = columns[0]?.[1].length ?? 0;
  const fields = columns.map(([name]) => new Field(name, new Float64(), nullable));
  const children = columns.map(([, values]) =>
    makeData({ type: new Float64(), length, nullCount: 0, data: values }),
  );
  const schema = new Schema(fields);
  const batch = new RecordBatch(
    schema,
    makeData({ type: new Struct(fields), length, nullCount: 0, children }),
  );
  return tableToIPC(new Table([batch]), "stream");
}

/** A binary response the client can read: status, headers and bytes. */
export function binaryResponse(bytes: Uint8Array, contentType = ARROW_MEDIA_TYPE, status = 200): Response {
  const copy = bytes.slice();
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": contentType, "content-length": String(copy.byteLength) }),
    json: async () => {
      throw new SyntaxError("not JSON");
    },
    arrayBuffer: async () => copy.buffer.slice(copy.byteOffset, copy.byteOffset + copy.byteLength),
  } as unknown as Response;
}

/** Route a laboratory URL to its fixture (JSON) or a synthetic frame stream (Arrow). */
export function laboratoryAnswer(url: string): Response | null {
  const json = (body: unknown) =>
    ({ ok: true, status: 200, json: async () => body }) as unknown as Response;
  if (url.endsWith("/laboratory")) return json(LABORATORY_INDEX);
  if (url.endsWith("/laboratory/model")) return json(LABORATORY_MODEL);
  const recordings: Record<string, unknown> = {
    repetition: LABORATORY_NOMINAL,
    "ablation-no-internal-model": LABORATORY_ABLATION,
  };
  const frames = /\/laboratory\/recordings\/([^/]+)\/frames\/([^/]+)$/.exec(url);
  if (frames !== null) {
    const recording = recordings[decodeURIComponent(frames[1]!)];
    return recording === undefined ? null : binaryResponse(frameStream(recording, frames[2]!));
  }
  const recording = /\/laboratory\/recordings\/([^/]+)$/.exec(url);
  if (recording !== null) {
    const body = recordings[decodeURIComponent(recording[1]!)];
    return body === undefined ? null : json(body);
  }
  return null;
}
