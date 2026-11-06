/**
 * Pure TypeScript Arrow IPC envelope/schema preflight.
 *
 * This reads only bounded framing and FlatBuffers metadata. It does not import apache-arrow,
 * build vectors, decompress buffers, or materialize rows. Keep the constants and FBS field
 * indices aligned with python/src/dynamisbench/transport/arrow_preflight.py.
 */

import {
  ArrowPreflightError,
  MAX_ARROW_BUFFERS,
  MAX_ARROW_COLUMNS,
  MAX_ARROW_DECODED_BYTES,
  MAX_ARROW_FIELD_DEPTH,
  MAX_ARROW_FIELD_NAME_BYTES,
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
  type ArrowFailure,
} from "./limits";

const CONTINUATION = 0xffff_ffff;
const MESSAGE_SCHEMA = 1;
const MESSAGE_DICTIONARY_BATCH = 2;
const MESSAGE_RECORD_BATCH = 3;

interface TableRef {
  readonly position: number;
  readonly vtable: number;
  readonly vtableSize: number;
  readonly objectSize: number;
}

interface FieldSpec {
  readonly typeCode: number;
  readonly valueWidth: number;
  readonly offsetWidth: number;
  readonly bufferCount: number;
}

interface BufferSpec {
  readonly offset: number;
  readonly length: number;
  readonly decodedLength: number;
  readonly dataOffset: number | null;
}

export interface ArrowPreflight {
  readonly messageCount: number;
  readonly recordBatchCount: number;
  readonly rowCount: number;
  readonly columnCount: number;
  readonly fieldNodeCount: number;
  readonly logicalValueCount: number;
  readonly metadataBytes: number;
  readonly encodedBodyBytes: number;
  readonly decodedBufferBytes: number;
}

class FlatBufferView {
  private readonly view: DataView;
  private readonly decoder = new TextDecoder("utf-8", { fatal: true });

  constructor(private readonly bytes: Uint8Array) {
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  }

  private range(position: number, size: number): void {
    if (
      !Number.isSafeInteger(position) ||
      !Number.isSafeInteger(size) ||
      position < 0 ||
      size < 0 ||
      position > this.bytes.byteLength ||
      size > this.bytes.byteLength - position
    ) {
      throw new ArrowPreflightError("malformed");
    }
  }

  u8(position: number): number {
    this.range(position, 1);
    return this.view.getUint8(position);
  }

  i8(position: number): number {
    this.range(position, 1);
    return this.view.getInt8(position);
  }

  i16(position: number): number {
    this.range(position, 2);
    return this.view.getInt16(position, true);
  }

  u16(position: number): number {
    this.range(position, 2);
    return this.view.getUint16(position, true);
  }

  u32(position: number): number {
    this.range(position, 4);
    return this.view.getUint32(position, true);
  }

  i32(position: number): number {
    this.range(position, 4);
    return this.view.getInt32(position, true);
  }

  i64(position: number): bigint {
    this.range(position, 8);
    return this.view.getBigInt64(position, true);
  }

  table(position: number): TableRef {
    this.range(position, 4);
    const vtable = position - this.i32(position);
    this.range(vtable, 4);
    const vtableSize = this.u16(vtable);
    const objectSize = this.u16(vtable + 2);
    if (vtableSize < 4 || vtableSize % 2 !== 0 || objectSize < 4) {
      throw new ArrowPreflightError("malformed");
    }
    this.range(vtable, vtableSize);
    this.range(position, objectSize);
    return { position, vtable, vtableSize, objectSize };
  }

  rootTable(): TableRef {
    return this.table(this.u32(0));
  }

  field(table: TableRef, index: number, size: number): number | null {
    const slot = table.vtable + 4 + index * 2;
    if (slot + 2 > table.vtable + table.vtableSize) return null;
    const relative = this.u16(slot);
    if (relative === 0) return null;
    if (relative + size > table.objectSize) throw new ArrowPreflightError("malformed");
    const position = table.position + relative;
    this.range(position, size);
    return position;
  }

  scalar(table: TableRef, index: number, read: (position: number) => number, size: number, fallback = 0): number {
    const position = this.field(table, index, size);
    return position === null ? fallback : read(position);
  }

  i64Field(table: TableRef, index: number, fallback = 0n): bigint {
    const position = this.field(table, index, 8);
    return position === null ? fallback : this.i64(position);
  }

  offset(table: TableRef, index: number): number | null {
    const position = this.field(table, index, 4);
    if (position === null) return null;
    const relative = this.u32(position);
    if (relative === 0) throw new ArrowPreflightError("malformed");
    const target = position + relative;
    this.range(target, 4);
    return target;
  }

  tableField(table: TableRef, index: number): TableRef | null {
    const position = this.offset(table, index);
    return position === null ? null : this.table(position);
  }

  vector(
    table: TableRef,
    index: number,
    itemSize: number,
    maximum: number,
    refusal: ArrowFailure = "too_many_metadata_entries",
  ): { readonly start: number; readonly count: number } {
    const position = this.offset(table, index);
    if (position === null) return { start: 0, count: 0 };
    const count = this.u32(position);
    if (count > maximum) throw new ArrowPreflightError(refusal);
    const start = position + 4;
    if (count > Math.floor((this.bytes.byteLength - start) / Math.max(itemSize, 1))) {
      throw new ArrowPreflightError("malformed");
    }
    this.range(start, count * itemSize);
    return { start, count };
  }

  vectorTable(start: number, index: number): TableRef {
    const position = start + index * 4;
    const relative = this.u32(position);
    if (relative === 0) throw new ArrowPreflightError("malformed");
    return this.table(position + relative);
  }

  string(table: TableRef, index: number, maximum: number): number {
    const position = this.offset(table, index);
    if (position === null) return 0;
    const length = this.u32(position);
    if (length > maximum) throw new ArrowPreflightError("too_large_metadata");
    const start = position + 4;
    this.range(start, length + 1);
    if (this.u8(start + length) !== 0) throw new ArrowPreflightError("malformed");
    try {
      this.decoder.decode(this.bytes.subarray(start, start + length));
    } catch {
      throw new ArrowPreflightError("malformed");
    }
    return length;
  }
}

type Count = [number];

function metadataEntries(fb: FlatBufferView, table: TableRef, index: number, total: Count): void {
  const { start, count } = fb.vector(table, index, 4, MAX_ARROW_METADATA_ENTRIES);
  total[0] = (total[0] ?? 0) + count;
  if ((total[0] ?? 0) > MAX_ARROW_METADATA_ENTRIES) {
    throw new ArrowPreflightError("too_many_metadata_entries");
  }
  for (let i = 0; i < count; i += 1) {
    const entry = fb.vectorTable(start, i);
    fb.string(entry, 0, MAX_ARROW_FIELD_NAME_BYTES);
    fb.string(entry, 1, MAX_ARROW_METADATA_STRING_BYTES);
  }
}

function fieldSpec(fb: FlatBufferView, field: TableRef, depth: number, total: Count, metadata: Count): FieldSpec {
  if (depth > MAX_ARROW_FIELD_DEPTH) throw new ArrowPreflightError("too_many_columns");
  total[0] = (total[0] ?? 0) + 1;
  if ((total[0] ?? 0) > MAX_ARROW_FIELD_NODES) throw new ArrowPreflightError("too_many_columns");
  fb.string(field, 0, MAX_ARROW_FIELD_NAME_BYTES);
  metadataEntries(fb, field, 6, metadata);
  if (fb.tableField(field, 4) !== null) throw new ArrowPreflightError("unsupported_schema");
  const children = fb.vector(field, 5, 4, MAX_ARROW_FIELD_NODES, "too_many_columns");
  if (children.count !== 0) throw new ArrowPreflightError("unsupported_schema");
  const typeCode = fb.scalar(field, 2, (p) => fb.u8(p), 1);
  const type = fb.tableField(field, 3);
  if (typeCode === 0 || type === null) throw new ArrowPreflightError("unsupported_schema");
  if (typeCode === 1) return { typeCode, valueWidth: 0, offsetWidth: 0, bufferCount: 0 };
  if (typeCode === 6) return { typeCode, valueWidth: 0, offsetWidth: 0, bufferCount: 2 };
  if (typeCode === 4 || typeCode === 5) return { typeCode, valueWidth: 0, offsetWidth: 4, bufferCount: 3 };
  if (typeCode === 19 || typeCode === 20) return { typeCode, valueWidth: 0, offsetWidth: 8, bufferCount: 3 };
  if (typeCode === 2) {
    const width = fb.scalar(type, 0, (p) => fb.i32(p), 4);
    const signed = fb.scalar(type, 1, (p) => fb.i8(p), 1);
    if (![8, 16, 32, 64].includes(width) || (signed !== 0 && signed !== 1)) {
      throw new ArrowPreflightError("unsupported_schema");
    }
    return { typeCode, valueWidth: width / 8, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 3) {
    const precision = fb.scalar(type, 0, (p) => fb.i16(p), 2);
    const widths: Record<number, number> = { 0: 2, 1: 4, 2: 8 };
    const width = widths[precision];
    if (width === undefined) throw new ArrowPreflightError("unsupported_schema");
    return { typeCode, valueWidth: width, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 7) {
    const precision = fb.scalar(type, 0, (p) => fb.i32(p), 4);
    const scale = fb.scalar(type, 1, (p) => fb.i32(p), 4);
    const bitWidth = fb.scalar(type, 2, (p) => fb.i32(p), 4);
    if (precision < 1 || precision > 76 || Math.abs(scale) > 76 || ![32, 64, 128, 256].includes(bitWidth)) {
      throw new ArrowPreflightError("unsupported_schema");
    }
    return { typeCode, valueWidth: bitWidth / 8, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 8) {
    const unit = fb.scalar(type, 0, (p) => fb.i16(p), 2);
    if (unit !== 0 && unit !== 1) throw new ArrowPreflightError("unsupported_schema");
    return { typeCode, valueWidth: unit === 0 ? 4 : 8, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 9) {
    const unit = fb.scalar(type, 0, (p) => fb.i16(p), 2);
    const width = fb.scalar(type, 1, (p) => fb.i32(p), 4);
    if (![0, 1, 2, 3].includes(unit) || (width !== 32 && width !== 64)) {
      throw new ArrowPreflightError("unsupported_schema");
    }
    return { typeCode, valueWidth: width / 8, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 10) {
    const unit = fb.scalar(type, 0, (p) => fb.i16(p), 2);
    if (![0, 1, 2, 3].includes(unit)) throw new ArrowPreflightError("unsupported_schema");
    fb.string(type, 1, MAX_ARROW_METADATA_STRING_BYTES);
    return { typeCode, valueWidth: 8, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 11) {
    const unit = fb.scalar(type, 0, (p) => fb.i16(p), 2);
    const widths: Record<number, number> = { 0: 4, 1: 8, 2: 16 };
    const width = widths[unit];
    if (width === undefined) throw new ArrowPreflightError("unsupported_schema");
    return { typeCode, valueWidth: width, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 15) {
    const width = fb.scalar(type, 0, (p) => fb.i32(p), 4);
    if (width < 1 || width > MAX_ARROW_DECODED_BYTES) throw new ArrowPreflightError("unsupported_schema");
    return { typeCode, valueWidth: width, offsetWidth: 0, bufferCount: 2 };
  }
  if (typeCode === 18) {
    const unit = fb.scalar(type, 0, (p) => fb.i16(p), 2);
    if (![0, 1, 2, 3].includes(unit)) throw new ArrowPreflightError("unsupported_schema");
    return { typeCode, valueWidth: 8, offsetWidth: 0, bufferCount: 2 };
  }
  throw new ArrowPreflightError("unsupported_schema");
}

function schemaFields(fb: FlatBufferView, schema: TableRef, metadata: Count): FieldSpec[] {
  const endianness = fb.scalar(schema, 0, (p) => fb.i16(p), 2);
  if (endianness !== 0) throw new ArrowPreflightError("unsupported_schema");
  metadataEntries(fb, schema, 2, metadata);
  const features = fb.vector(schema, 3, 8, 64);
  for (let i = 0; i < features.count; i += 1) {
    const feature = fb.i64(features.start + i * 8);
    if (feature !== 1n && feature !== 2n) throw new ArrowPreflightError("unsupported_schema");
  }
  const columns = fb.vector(schema, 1, 4, MAX_ARROW_COLUMNS, "too_many_columns");
  const total: Count = [0];
  const fields: FieldSpec[] = [];
  for (let i = 0; i < columns.count; i += 1) {
    fields.push(fieldSpec(fb, fb.vectorTable(columns.start, i), 1, total, metadata));
  }
  return fields;
}

function inspectBatch(
  fb: FlatBufferView,
  batch: TableRef,
  body: Uint8Array,
  fields: readonly FieldSpec[],
): { readonly rows: number; readonly logicalValues: number; readonly decodedBytes: number } {
  const rowsBig = fb.i64Field(batch, 0);
  if (rowsBig < 0n) throw new ArrowPreflightError("malformed");
  if (rowsBig > BigInt(MAX_ARROW_ROWS)) throw new ArrowPreflightError("too_many_rows");
  const rows = Number(rowsBig);
  const nodes = fb.vector(batch, 1, 16, MAX_ARROW_FIELD_NODES, "too_many_columns");
  if (nodes.count !== fields.length) throw new ArrowPreflightError("malformed");
  const nullCounts: bigint[] = [];
  let logicalValues = 0;
  for (let i = 0; i < nodes.count; i += 1) {
    const position = nodes.start + i * 16;
    const length = fb.i64(position);
    const nullCount = fb.i64(position + 8);
    if (length !== rowsBig) throw new ArrowPreflightError("malformed");
    if (length < 0n || length > BigInt(MAX_ARROW_LOGICAL_VALUES)) {
      throw new ArrowPreflightError("too_many_values");
    }
    if (nullCount < -1n || (nullCount >= 0n && nullCount > length)) {
      throw new ArrowPreflightError("malformed");
    }
    logicalValues += Number(length);
    if (logicalValues > MAX_ARROW_LOGICAL_VALUES) throw new ArrowPreflightError("too_many_values");
    nullCounts.push(nullCount);
  }

  const buffers = fb.vector(batch, 2, 16, MAX_ARROW_BUFFERS, "too_many_metadata_entries");
  const compression = fb.tableField(batch, 3);
  if (compression !== null) {
    const codec = fb.scalar(compression, 0, (p) => fb.i8(p), 1);
    const method = fb.scalar(compression, 1, (p) => fb.i8(p), 1);
    if (method !== 0 || (codec !== 0 && codec !== 1)) throw new ArrowPreflightError("malformed");
  }
  const variadic = fb.vector(batch, 4, 8, MAX_ARROW_FIELD_NODES, "too_many_columns");
  let variadicTotal = 0n;
  for (let i = 0; i < variadic.count; i += 1) {
    const count = fb.i64(variadic.start + i * 8);
    if (count < 0n) throw new ArrowPreflightError("malformed");
    variadicTotal += count;
    if (variadicTotal > BigInt(MAX_ARROW_BUFFERS)) throw new ArrowPreflightError("too_many_metadata_entries");
  }
  if (variadicTotal !== 0n) throw new ArrowPreflightError("unsupported_schema");
  const expectedBuffers = fields.reduce((sum, field) => sum + field.bufferCount, 0);
  if (buffers.count !== expectedBuffers) throw new ArrowPreflightError("malformed");

  const decodedBuffers: BufferSpec[] = [];
  let decodedBytes = 0;
  const bodyView = new DataView(body.buffer, body.byteOffset, body.byteLength);
  for (let i = 0; i < buffers.count; i += 1) {
    const position = buffers.start + i * 16;
    const offsetBig = fb.i64(position);
    const lengthBig = fb.i64(position + 8);
    if (offsetBig < 0n || lengthBig < 0n || offsetBig > BigInt(body.byteLength) || lengthBig > BigInt(body.byteLength) - offsetBig) {
      throw new ArrowPreflightError("malformed");
    }
    const offset = Number(offsetBig);
    const length = Number(lengthBig);
    let decodedLength = length;
    let dataOffset: number | null = offset;
    if (compression !== null && length > 0) {
      if (length < 8) throw new ArrowPreflightError("malformed");
      const uncompressed = bodyView.getBigInt64(offset, true);
      if (uncompressed === -1n) {
        decodedLength = length - 8;
        dataOffset = offset + 8;
      } else if (uncompressed >= 0n && uncompressed <= BigInt(MAX_ARROW_DECODED_BYTES)) {
        decodedLength = Number(uncompressed);
        dataOffset = null;
      } else if (uncompressed > BigInt(MAX_ARROW_DECODED_BYTES)) {
        throw new ArrowPreflightError("too_large_decoded");
      } else {
        throw new ArrowPreflightError("malformed");
      }
    }
    decodedBuffers.push({ offset, length, decodedLength, dataOffset });
    decodedBytes += decodedLength;
    if (decodedBytes > MAX_ARROW_DECODED_BYTES) throw new ArrowPreflightError("too_large_decoded");
  }
  if (compression !== null) {
    // Inspect declared expansion before refusing the compression profile; never call an
    // unbounded codec during preflight.
    throw new ArrowPreflightError("unsupported_compression");
  }

  let cursor = 0;
  const bitmapBytes = Math.ceil(rows / 8);
  for (let i = 0; i < fields.length; i += 1) {
    const field = fields[i]!;
    const nullCount = nullCounts[i]!;
    if (field.typeCode === 1) {
      if (nullCount !== -1n && nullCount !== rowsBig) throw new ArrowPreflightError("malformed");
      continue;
    }
    const validity = decodedBuffers[cursor++]!;
    if (validity.decodedLength !== 0 && validity.decodedLength < bitmapBytes) {
      throw new ArrowPreflightError("malformed");
    }
    if (nullCount > 0n && validity.decodedLength < bitmapBytes) throw new ArrowPreflightError("malformed");

    if (field.offsetWidth !== 0) {
      const offsets = decodedBuffers[cursor++]!;
      const values = decodedBuffers[cursor++]!;
      const required = rows === 0 ? 0 : (rows + 1) * field.offsetWidth;
      if (offsets.decodedLength < required) throw new ArrowPreflightError("malformed");
      if (offsets.dataOffset !== null && required > 0) {
        const offsetView = new DataView(body.buffer, body.byteOffset, body.byteLength);
        const read = (row: number): bigint =>
          field.offsetWidth === 4
            ? BigInt(offsetView.getInt32(offsets.dataOffset! + row * 4, true))
            : offsetView.getBigInt64(offsets.dataOffset! + row * 8, true);
        let previous = read(0);
        if (previous !== 0n) throw new ArrowPreflightError("malformed");
        for (let row = 1; row <= rows; row += 1) {
          const current = read(row);
          if (current < previous || current > BigInt(values.decodedLength)) {
            throw new ArrowPreflightError("malformed");
          }
          previous = current;
        }
      }
    } else {
      const values = decodedBuffers[cursor++]!;
      const minimum = field.typeCode === 6 ? bitmapBytes : rows * field.valueWidth;
      if (values.decodedLength < minimum) throw new ArrowPreflightError("malformed");
    }
  }
  if (cursor !== decodedBuffers.length) throw new ArrowPreflightError("malformed");
  return { rows, logicalValues, decodedBytes };
}

/** Establish schema, dimensions, buffer extents and decoded budgets before tableFromIPC. */
export function preflightArrowIpcStream(payload: Uint8Array): ArrowPreflight {
  if (payload.byteLength === 0) throw new ArrowPreflightError("empty");
  if (payload.byteLength > MAX_ARROW_IPC_BYTES) throw new ArrowPreflightError("too_large");
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  let position = 0;
  let metadataBytes = 0;
  let encodedBodyBytes = 0;
  let decodedBufferBytes = 0;
  let messageCount = 0;
  let recordBatchCount = 0;
  let rowCount = 0;
  let logicalValueCount = 0;
  let fields: FieldSpec[] | null = null;
  let fieldNodeCount = 0;
  const metadataTotal: Count = [0];

  while (position < payload.byteLength) {
    if (payload.byteLength - position < 4) throw new ArrowPreflightError("malformed");
    const prefix = view.getUint32(position, true);
    position += 4;
    if (prefix === 0) {
      if (position !== payload.byteLength) throw new ArrowPreflightError("malformed");
      break;
    }
    let metadataLength = prefix;
    if (prefix === CONTINUATION) {
      if (payload.byteLength - position < 4) throw new ArrowPreflightError("malformed");
      metadataLength = view.getUint32(position, true);
      position += 4;
      if (metadataLength === 0) {
        if (position !== payload.byteLength) throw new ArrowPreflightError("malformed");
        break;
      }
    }
    if (metadataLength < 8) throw new ArrowPreflightError("malformed");
    if (metadataLength > payload.byteLength - position) throw new ArrowPreflightError("malformed");
    if (metadataLength > MAX_ARROW_MESSAGE_METADATA_BYTES) {
      throw new ArrowPreflightError("too_large_metadata");
    }
    metadataBytes += metadataLength;
    if (metadataBytes > MAX_ARROW_TOTAL_METADATA_BYTES) {
      throw new ArrowPreflightError("too_large_metadata");
    }
    if (messageCount >= MAX_ARROW_MESSAGES) throw new ArrowPreflightError("too_many_messages");
    messageCount += 1;

    const metadataStart = position;
    const metadataEnd = metadataStart + metadataLength;
    const metadataBytesView = payload.subarray(metadataStart, metadataEnd);
    const fb = new FlatBufferView(metadataBytesView);
    const message = fb.rootTable();
    const version = fb.scalar(message, 0, (p) => fb.i16(p), 2);
    if (![0, 1, 2, 3, 4].includes(version)) throw new ArrowPreflightError("unsupported_schema");
    const messageType = fb.scalar(message, 1, (p) => fb.u8(p), 1);
    const bodyLengthBig = fb.i64Field(message, 3);
    if (bodyLengthBig < 0n || bodyLengthBig % 8n !== 0n) throw new ArrowPreflightError("malformed");
    const header = fb.tableField(message, 2);
    if (header === null) throw new ArrowPreflightError("malformed");
    metadataEntries(fb, message, 4, metadataTotal);
    position = metadataEnd;
    if (bodyLengthBig > BigInt(payload.byteLength - position)) throw new ArrowPreflightError("malformed");
    const bodyLength = Number(bodyLengthBig);
    const bodyStart = position;
    const body = payload.subarray(bodyStart, bodyStart + bodyLength);
    encodedBodyBytes += bodyLength;
    if (encodedBodyBytes > MAX_ARROW_IPC_BYTES) throw new ArrowPreflightError("too_large");

    if (messageType === MESSAGE_SCHEMA) {
      if (fields !== null || messageCount !== 1 || bodyLength !== 0) {
        throw new ArrowPreflightError("malformed");
      }
      fields = schemaFields(fb, header, metadataTotal);
      fieldNodeCount = fields.length;
    } else if (messageType === MESSAGE_RECORD_BATCH) {
      if (fields === null) throw new ArrowPreflightError("malformed");
      recordBatchCount += 1;
      if (recordBatchCount > MAX_ARROW_RECORD_BATCHES) {
        throw new ArrowPreflightError("too_many_batches");
      }
      const stats = inspectBatch(fb, header, body, fields);
      rowCount += stats.rows;
      if (rowCount > MAX_ARROW_ROWS) throw new ArrowPreflightError("too_many_rows");
      logicalValueCount += fields.length === 0 ? stats.rows : stats.logicalValues;
      decodedBufferBytes += stats.decodedBytes;
    } else if (messageType === MESSAGE_DICTIONARY_BATCH) {
      throw new ArrowPreflightError("unsupported_schema");
    } else {
      throw new ArrowPreflightError("unsupported_schema");
    }
    if (logicalValueCount > MAX_ARROW_LOGICAL_VALUES) {
      throw new ArrowPreflightError("too_many_values");
    }
    if (decodedBufferBytes > MAX_ARROW_DECODED_BYTES) {
      throw new ArrowPreflightError("too_large_decoded");
    }
    position = bodyStart + bodyLength;
  }

  if (fields === null) throw new ArrowPreflightError("malformed");
  return {
    messageCount,
    recordBatchCount,
    rowCount,
    columnCount: fields.length,
    fieldNodeCount,
    logicalValueCount,
    metadataBytes,
    encodedBodyBytes,
    decodedBufferBytes,
  };
}
