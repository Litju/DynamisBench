/**
 * Columnar decoding of bulk float frames: typed arrays out, and the server's contract (non-null
 * float64, unique names, bounded size) enforced on the way in.
 */

import { describe, expect, it } from "vitest";

import { floatStream } from "../test/laboratory-fixtures";
import { ArrowDecodeError, MAX_ARROW_IPC_BYTES, decodeArrowFloatColumns } from "./arrow";

async function reason(payload: Uint8Array): Promise<string> {
  try {
    await decodeArrowFloatColumns(payload);
  } catch (error) {
    if (error instanceof ArrowDecodeError) {
      return error.reason;
    }
    throw error;
  }
  return "accepted";
}

describe("decodeArrowFloatColumns", () => {
  it("decodes named float64 columns into typed arrays, in stream order", async () => {
    const payload = floatStream([
      ["t", Float64Array.from([0, 0.01, 0.02])],
      ["knee_flexion_l.angle_deg", Float64Array.from([5, 6.5, 8])],
    ]);

    const decoded = await decodeArrowFloatColumns(payload);

    expect(decoded.names).toEqual(["t", "knee_flexion_l.angle_deg"]);
    expect(decoded.numRows).toBe(3);
    expect(decoded.columns.get("knee_flexion_l.angle_deg")).toEqual(Float64Array.from([5, 6.5, 8]));
    expect(decoded.columns.get("t")).toBeInstanceOf(Float64Array);
  });

  it("returns columns that do not alias the payload", async () => {
    const payload = floatStream([["t", Float64Array.from([1, 2])]]);
    const decoded = await decodeArrowFloatColumns(payload);

    payload.fill(0);

    expect(decoded.columns.get("t")).toEqual(Float64Array.from([1, 2]));
  });

  it("refuses nullable fields, which the server never encodes", async () => {
    expect(await reason(floatStream([["t", Float64Array.from([1])]], true))).toBe("malformed");
  });

  it("refuses empty, oversized and non-Arrow payloads", async () => {
    expect(await reason(new Uint8Array())).toBe("empty");
    expect(await reason(new Uint8Array(MAX_ARROW_IPC_BYTES + 1))).toBe("too_large");
    expect(await reason(new TextEncoder().encode("not an arrow stream"))).toBe("malformed");
  });
});
