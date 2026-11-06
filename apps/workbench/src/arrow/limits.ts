/** Cross-language Arrow IPC resource budgets; keep in sync with python/transport/arrow_limits.py. */
export const MAX_ARROW_IPC_BYTES = 1 * 1024 * 1024;
export const MAX_ARROW_ROWS = 100_000;
export const MAX_ARROW_COLUMNS = 256;
export const MAX_ARROW_FIELD_NODES = 512;
export const MAX_ARROW_LOGICAL_VALUES = 250_000;
export const MAX_ARROW_DECODED_BYTES = 8 * 1024 * 1024;
export const MAX_ARROW_MESSAGE_METADATA_BYTES = 256 * 1024;
export const MAX_ARROW_TOTAL_METADATA_BYTES = 512 * 1024;
export const MAX_ARROW_MESSAGES = 128;
export const MAX_ARROW_RECORD_BATCHES = 64;
export const MAX_ARROW_FIELD_DEPTH = 16;
export const MAX_ARROW_BUFFERS = 4_096;
export const MAX_ARROW_METADATA_ENTRIES = 256;
export const MAX_ARROW_FIELD_NAME_BYTES = 1_024;
export const MAX_ARROW_METADATA_STRING_BYTES = 16 * 1024;

export type ArrowFailure =
  | "empty"
  | "too_large"
  | "too_large_metadata"
  | "too_large_decoded"
  | "malformed"
  | "unsupported_schema"
  | "unsupported_compression"
  | "too_many_rows"
  | "too_many_columns"
  | "too_many_values"
  | "too_many_batches"
  | "too_many_messages"
  | "too_many_metadata_entries";

export class ArrowPreflightError extends Error {
  readonly reason: ArrowFailure;

  constructor(reason: ArrowFailure) {
    super(`The Arrow IPC payload was refused (${reason}).`);
    this.name = "ArrowPreflightError";
    this.reason = reason;
  }
}
