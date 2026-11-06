import { afterAll, describe, expect, it, vi } from "vitest";

const { tableFromIPCMock } = vi.hoisted(() => ({ tableFromIPCMock: vi.fn() }));
vi.mock("apache-arrow", () => ({ tableFromIPC: tableFromIPCMock }));

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import expandedNullCells from "../test/fixtures/arrow/expanded-null-columns.arrow.b64?raw";
import compressedExpansion from "../test/fixtures/arrow/compressed-buffer-expansion.arrow.b64?raw";
import rowsOverLimit from "../test/fixtures/arrow/rows-over-limit.arrow.b64?raw";
import columnsOverLimit from "../test/fixtures/arrow/columns-over-limit.arrow.b64?raw";
import nestedList from "../test/fixtures/arrow/nested-list.arrow.b64?raw";
import dictionary from "../test/fixtures/arrow/dictionary.arrow.b64?raw";
import smallCompressed from "../test/fixtures/arrow/small-compressed.arrow.b64?raw";
import malformedStringOffsets from "../test/fixtures/arrow/malformed-string-offsets.arrow.b64?raw";
import { ArrowPreflightError } from "./limits";
import type { ArrowFailure } from "./limits";
import { ArrowDecodeError, decodeArrowIpcStream } from "./arrow";
import { preflightArrowIpcStream } from "./preflight";

interface ProbeResult {
  readonly fixture: string;
  readonly input_bytes: number;
  readonly declared_rows: number;
  readonly declared_columns: number;
  readonly declared_logical_values: number;
  readonly expected_refusal: string;
  readonly outcome: string;
  readonly iterations: number;
  readonly elapsed_ms: number;
  readonly cpu_us: number;
  readonly cpu_ms: number;
  readonly heap_delta_bytes: number;
  readonly rss_delta_bytes: number;
}

function bytes(base64: string): Uint8Array {
  const binary = atob(base64.trim());
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

const results: ProbeResult[] = [];

async function measuredRefusal(
  fixture: string,
  base64: string,
  shape: Omit<
    ProbeResult,
    | "fixture"
    | "input_bytes"
    | "expected_refusal"
    | "outcome"
    | "iterations"
    | "elapsed_ms"
    | "cpu_us"
    | "cpu_ms"
    | "heap_delta_bytes"
    | "rss_delta_bytes"
  >,
  expected: ArrowFailure,
): Promise<void> {
  const payload = bytes(base64);
  const before = process.memoryUsage();
  const cpuBefore = process.cpuUsage();
  const started = performance.now();
  let outcome = "accepted";
  const iterations = 64;
  for (let i = 0; i < iterations; i += 1) {
    try {
      await decodeArrowIpcStream(payload);
    } catch (error) {
      if (error instanceof ArrowDecodeError) outcome = error.reason;
      else throw error;
    }
  }
  const elapsed = performance.now() - started;
  const cpu = process.cpuUsage(cpuBefore);
  const after = process.memoryUsage();
  const result: ProbeResult = {
    fixture,
    input_bytes: payload.byteLength,
    ...shape,
    expected_refusal: expected,
    outcome,
    iterations,
    elapsed_ms: Number(elapsed.toFixed(3)),
    cpu_us: cpu.user + cpu.system,
    cpu_ms: Number(((cpu.user + cpu.system) / 1000).toFixed(3)),
    heap_delta_bytes: after.heapUsed - before.heapUsed,
    rss_delta_bytes: after.rss - before.rss,
  };
  results.push(result);
  expect(outcome).toBe(expected);
  expect(elapsed).toBeLessThan(2_000);
  expect(Math.max(0, result.heap_delta_bytes)).toBeLessThan(16 * 1024 * 1024);
  expect(Math.max(0, result.rss_delta_bytes)).toBeLessThan(32 * 1024 * 1024);
  expect(tableFromIPCMock).not.toHaveBeenCalled();
  tableFromIPCMock.mockClear();
}

describe("Arrow allocation preflight", () => {
  it("refuses 25.6 million logical cells in a small zero-body stream before tableFromIPC", async () => {
    const payload = bytes(expandedNullCells);
    expect(payload.byteLength).toBeLessThan(64 * 1024);
    try {
      preflightArrowIpcStream(payload);
      throw new Error("expected the preflight to refuse the stream");
    } catch (error) {
      expect(error).toBeInstanceOf(ArrowPreflightError);
      expect(error).toMatchObject({ reason: "too_many_values" });
    }
    await measuredRefusal(
      "expanded-null-columns",
      expandedNullCells,
      { declared_rows: 100_000, declared_columns: 256, declared_logical_values: 25_600_000 },
      "too_many_values",
    );
  });

  it("refuses a compressed buffer whose declared decoded size exceeds 8 MiB before tableFromIPC", async () => {
    const payload = bytes(compressedExpansion);
    expect(payload.byteLength).toBeLessThan(4 * 1024);
    await measuredRefusal(
      "compressed-buffer-expansion",
      compressedExpansion,
      { declared_rows: 8, declared_columns: 1, declared_logical_values: 8 },
      "too_large_decoded",
    );
  });

  it("keeps row and column limits before tableFromIPC", async () => {
    await measuredRefusal(
      "rows-over-limit",
      rowsOverLimit,
      { declared_rows: 100_001, declared_columns: 1, declared_logical_values: 100_001 },
      "too_many_rows",
    );
    await measuredRefusal(
      "columns-over-limit",
      columnsOverLimit,
      { declared_rows: 100_000, declared_columns: 257, declared_logical_values: 25_700_000 },
      "too_many_columns",
    );
  });

  it("fails closed on nested/dictionary schemas and unsupported bounded compression", async () => {
    await measuredRefusal(
      "nested-list",
      nestedList,
      { declared_rows: 2, declared_columns: 1, declared_logical_values: 5 },
      "unsupported_schema",
    );
    await measuredRefusal(
      "dictionary",
      dictionary,
      { declared_rows: 4, declared_columns: 1, declared_logical_values: 6 },
      "unsupported_schema",
    );
    await measuredRefusal(
      "small-compressed",
      smallCompressed,
      { declared_rows: 8, declared_columns: 1, declared_logical_values: 8 },
      "unsupported_compression",
    );
    await measuredRefusal(
      "malformed-string-offsets",
      malformedStringOffsets,
      { declared_rows: 2, declared_columns: 1, declared_logical_values: 2 },
      "malformed",
    );
  });
});

afterAll(() => {
  const reportPath = process.env.DYNAMISBENCH_ARROW_ALLOCATION_REPORT;
  if (reportPath === undefined || results.length === 0) return;
  mkdirSync(dirname(reportPath), { recursive: true });
  writeFileSync(
    reportPath,
    `${JSON.stringify({
      authority: "RES-566",
      target: process.env.DYNAMISBENCH_ARROW_ALLOCATION_TARGET ?? "local",
      tested_sha: process.env.DYNAMISBENCH_ARROW_ALLOCATION_TESTED_SHA ?? "unknown",
      head_sha: process.env.DYNAMISBENCH_ARROW_ALLOCATION_HEAD_SHA ?? "unknown",
      ref: process.env.DYNAMISBENCH_ARROW_ALLOCATION_REF ?? "local",
      image_os: process.env.ImageOS ?? process.env.RUNNER_OS ?? "unknown",
      image_version: process.env.ImageVersion ?? "unknown",
      node: process.version,
      v8: process.versions.v8,
      runtime: "apache-arrow tableFromIPC is never called for either hostile fixture",
      results,
    }, null, 2)}\n`,
    "utf8",
  );
});
