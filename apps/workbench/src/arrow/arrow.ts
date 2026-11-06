/**
 * Arrow IPC stream decoding, as a transport primitive and nothing more.
 *
 * `apache-arrow` is loaded with a dynamic import the first time a payload is decoded, so the
 * workbench's initial module graph, the route tree and the Activity transport never pay for
 * the columnar stack. This module does not persist a table, serve one, visualize one or treat
 * one as scientific authority: it turns bounded bytes into fields and rows for a caller that
 * already has a reason to read them.
 *
 * Refusals are bounded. Empty input, input above `MAX_ARROW_IPC_BYTES`, a table with more rows
 * than `MAX_ARROW_ROWS`, and bytes the official reader rejects all raise `ArrowDecodeError`
 * with a closed reason. The underlying exception text is not attached or quoted.
 */

export const ARROW_IPC_STREAM_CONTENT_TYPE = "application/vnd.apache.arrow.stream";

export const MAX_ARROW_IPC_BYTES = 1 * 1024 * 1024;
export const MAX_ARROW_ROWS = 100_000;

export type ArrowFailure = "empty" | "too_large" | "malformed" | "too_many_rows";

export class ArrowDecodeError extends Error {
  readonly reason: ArrowFailure;

  constructor(reason: ArrowFailure) {
    super(`The Arrow IPC payload was refused (${reason}).`);
    this.name = "ArrowDecodeError";
    this.reason = reason;
  }
}

export interface ArrowField {
  readonly name: string;
  readonly type: string;
  readonly nullable: boolean;
}

export interface DecodedArrowTable {
  readonly fields: readonly ArrowField[];
  readonly rows: readonly Record<string, unknown>[];
  readonly numRows: number;
  readonly contentType: typeof ARROW_IPC_STREAM_CONTENT_TYPE;
}

/**
 * Decode one Arrow IPC *stream* payload.
 *
 * The function is async because the reader is imported on demand. `Uint8Array` is the input
 * shape fetch and Arrow both speak; no base64, file path or URL is accepted here.
 */
export async function decodeArrowIpcStream(
  payload: Uint8Array,
): Promise<DecodedArrowTable> {
  if (payload.byteLength === 0) {
    throw new ArrowDecodeError("empty");
  }
  if (payload.byteLength > MAX_ARROW_IPC_BYTES) {
    throw new ArrowDecodeError("too_large");
  }

  const { tableFromIPC } = await import("apache-arrow");

  let table;
  try {
    table = tableFromIPC(payload);
  } catch {
    throw new ArrowDecodeError("malformed");
  }

  if (table.numRows > MAX_ARROW_ROWS) {
    throw new ArrowDecodeError("too_many_rows");
  }

  const fields: ArrowField[] = table.schema.fields.map((field) => ({
    name: field.name,
    type: String(field.type),
    nullable: field.nullable,
  }));

  let rows: Record<string, unknown>[];
  try {
    rows = table.toArray().map((row) => row.toJSON() as Record<string, unknown>);
  } catch {
    throw new ArrowDecodeError("malformed");
  }

  return {
    fields,
    rows,
    numRows: table.numRows,
    contentType: ARROW_IPC_STREAM_CONTENT_TYPE,
  };
}

export interface DecodedFloatColumns {
  readonly names: readonly string[];
  readonly columns: ReadonlyMap<string, Float64Array>;
  readonly numRows: number;
}

/**
 * Decode one Arrow IPC stream of non-null `float64` columns into typed arrays, column by column.
 *
 * The columnar counterpart of [`decodeArrowIpcStream`] for bulk numeric frames (the server's
 * `encode_float_columns`): no per-row objects are built. The same bounds apply, and a stream
 * whose fields are not all non-null `Float64`, or whose names repeat, is `malformed`.
 */
export async function decodeArrowFloatColumns(payload: Uint8Array): Promise<DecodedFloatColumns> {
  if (payload.byteLength === 0) {
    throw new ArrowDecodeError("empty");
  }
  if (payload.byteLength > MAX_ARROW_IPC_BYTES) {
    throw new ArrowDecodeError("too_large");
  }

  const { tableFromIPC, DataType, Precision } = await import("apache-arrow");

  let table;
  try {
    table = tableFromIPC(payload);
  } catch {
    throw new ArrowDecodeError("malformed");
  }

  if (table.numRows > MAX_ARROW_ROWS) {
    throw new ArrowDecodeError("too_many_rows");
  }

  const names: string[] = [];
  const columns = new Map<string, Float64Array>();
  for (const field of table.schema.fields) {
    const double =
      DataType.isFloat(field.type) && (field.type as { precision: number }).precision === Precision.DOUBLE;
    if (!double || field.nullable || columns.has(field.name)) {
      throw new ArrowDecodeError("malformed");
    }
    const vector = table.getChild(field.name);
    if (vector === null || vector.nullCount !== 0) {
      throw new ArrowDecodeError("malformed");
    }
    const values = vector.toArray();
    if (!(values instanceof Float64Array) || values.length !== table.numRows) {
      throw new ArrowDecodeError("malformed");
    }
    names.push(field.name);
    // A copy: the decoded column must not alias the IPC buffer it was read from.
    columns.set(field.name, Float64Array.from(values));
  }

  return { names, columns, numRows: table.numRows };
}
