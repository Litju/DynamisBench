/**
 * Cross-language Arrow IPC proof.
 *
 * The bytes are the base64 golden fixture also decoded by the Python suite. That suite proves
 * the Python encoder reproduces the fixture byte for byte; this one proves the official
 * JavaScript reader observes the same schema, nullability, values and row count.
 */

import { describe, expect, it } from "vitest";

import qualificationFixture from "../test/fixtures/qualification.arrow.b64?raw";
import {
  ARROW_IPC_STREAM_CONTENT_TYPE,
  ArrowDecodeError,
  MAX_ARROW_IPC_BYTES,
  decodeArrowIpcStream,
} from "./arrow";

function fixtureBytes(): Uint8Array {
  const binary = atob(qualificationFixture.trim());
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

describe("decodeArrowIpcStream", () => {
  it("decodes the Python-generated fixture with the frozen schema", async () => {
    const table = await decodeArrowIpcStream(fixtureBytes());

    expect(table.contentType).toBe(ARROW_IPC_STREAM_CONTENT_TYPE);
    expect(table.numRows).toBe(4);
    expect(table.fields).toEqual([
      { name: "sample_index", type: "Int64", nullable: false },
      { name: "label", type: "Utf8", nullable: false },
      { name: "measurement", type: "Float64", nullable: true },
      { name: "note", type: "Utf8", nullable: true },
    ]);
  });

  it("decodes exact values, including both nullable columns' nulls", async () => {
    const table = await decodeArrowIpcStream(fixtureBytes());

    expect(table.rows).toEqual([
      { sample_index: 0n, label: "baseline", measurement: 1.5, note: null },
      { sample_index: 1n, label: "perturbed", measurement: 2.25, note: "first trial" },
      { sample_index: 2n, label: "baseline", measurement: null, note: "not measured" },
      { sample_index: 3n, label: "recovered", measurement: -0.5, note: null },
    ]);
  });

  it("is deterministic across two decodes", async () => {
    await expect(decodeArrowIpcStream(fixtureBytes())).resolves.toEqual(
      await decodeArrowIpcStream(fixtureBytes()),
    );
  });

  it("refuses empty input", async () => {
    await expect(decodeArrowIpcStream(new Uint8Array())).rejects.toMatchObject({
      name: "ArrowDecodeError",
      reason: "empty",
    });
  });

  it("refuses an oversized payload before importing the reader", async () => {
    const oversize = new Uint8Array(MAX_ARROW_IPC_BYTES + 1);

    const error = await decodeArrowIpcStream(oversize).catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(ArrowDecodeError);
    expect((error as ArrowDecodeError).reason).toBe("too_large");
  });

  it("refuses malformed and truncated bytes", async () => {
    for (const payload of [
      new TextEncoder().encode("not an arrow stream"),
      fixtureBytes().slice(0, 40),
    ]) {
      const error = await decodeArrowIpcStream(payload).catch((failure: unknown) => failure);
      expect(error).toBeInstanceOf(ArrowDecodeError);
      expect((error as ArrowDecodeError).reason).toBe("malformed");
    }
  });
});
