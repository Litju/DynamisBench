/**
 * Arrow IPC stream decoding, as a transport primitive and nothing more.
 *
 * `apache-arrow` is loaded with a dynamic import the first time a payload is decoded, so the
 * workbench's initial module graph, the route tree and the Activity transport never pay for
 * the columnar stack. This module does not persist a table, serve one, visualize one or treat
 * one as scientific authority: it turns bounded bytes into fields and rows for a caller that
 * already has a reason to read them.
 *
 * The IPC envelope, schema, dimensions and decoded-buffer sizes are preflighted before the
 * official reader constructs vectors or rows. Refusals use a closed reason; the underlying
 * exception text is not attached or quoted.
 */

import { ArrowPreflightError, type ArrowFailure, MAX_ARROW_IPC_BYTES, MAX_ARROW_ROWS } from "./limits";
import { preflightArrowIpcStream } from "./preflight";

export {
  MAX_ARROW_BUFFERS,
  MAX_ARROW_COLUMNS,
  MAX_ARROW_DECODED_BYTES,
  MAX_ARROW_FIELD_DEPTH,
  MAX_ARROW_FIELD_NODES,
  MAX_ARROW_IPC_BYTES,
  MAX_ARROW_LOGICAL_VALUES,
  MAX_ARROW_MESSAGE_METADATA_BYTES,
  MAX_ARROW_MESSAGES,
  MAX_ARROW_METADATA_ENTRIES,
  MAX_ARROW_METADATA_STRING_BYTES,
  MAX_ARROW_RECORD_BATCHES,
  MAX_ARROW_ROWS,
  MAX_ARROW_TOTAL_METADATA_BYTES,
} from "./limits";
export type { ArrowFailure } from "./limits";

export const ARROW_IPC_STREAM_CONTENT_TYPE = "application/vnd.apache.arrow.stream";

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

  let budget: ReturnType<typeof preflightArrowIpcStream>;
  try {
    budget = preflightArrowIpcStream(payload);
  } catch (error) {
    if (error instanceof ArrowPreflightError) {
      throw new ArrowDecodeError(error.reason);
    }
    throw new ArrowDecodeError("malformed");
  }

  const { tableFromIPC } = await import("apache-arrow");

  let table;
  try {
    table = tableFromIPC(payload);
  } catch {
    throw new ArrowDecodeError("malformed");
  }

  if (table.numRows !== budget.rowCount || table.schema.fields.length !== budget.columnCount) {
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
