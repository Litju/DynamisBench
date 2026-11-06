import { describe, expect, it, vi } from "vitest";

const { tableFromIPCMock } = vi.hoisted(() => ({ tableFromIPCMock: vi.fn() }));
vi.mock("apache-arrow", () => ({ tableFromIPC: tableFromIPCMock }));

import expandedNullCells from "../test/fixtures/arrow/expanded-null-columns.arrow.b64?raw";
import compressedExpansion from "../test/fixtures/arrow/compressed-buffer-expansion.arrow.b64?raw";
import { decodeArrowFloatColumns } from "./arrow";

function payload(base64: string): Uint8Array {
  const binary = atob(base64.trim());
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

describe("RES-591 Laboratory float-frame pre-materialization admission", () => {
  it("refuses a tiny stream declaring 25.6 million values before the Arrow reader loads", async () => {
    await expect(decodeArrowFloatColumns(payload(expandedNullCells))).rejects.toMatchObject({
      reason: "too_many_values",
    });
    expect(tableFromIPCMock).not.toHaveBeenCalled();
  });

  it("refuses a compressed expansion beyond 8 MiB before the Arrow reader loads", async () => {
    await expect(decodeArrowFloatColumns(payload(compressedExpansion))).rejects.toMatchObject({
      reason: "too_large_decoded",
    });
    expect(tableFromIPCMock).not.toHaveBeenCalled();
  });
});
