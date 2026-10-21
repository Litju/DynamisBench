/**
 * The SSE parser is a pure wire-format reader, so its gates are about bytes and boundaries.
 *
 * No network, no clock and no application contract: every case here is a chunk sequence and
 * the frames it must produce (or the refusal it must raise).
 */

import { describe, expect, it } from "vitest";

import { MAX_SSE_FRAME_CHARS, SseParseError, SseParser } from "./sse";

function collect(chunks: readonly string[]): string[] {
  const parser = new SseParser();
  const frames: string[] = [];
  for (const chunk of chunks) {
    for (const frame of parser.push(chunk)) {
      frames.push(frame.data);
    }
  }
  for (const frame of parser.end()) {
    frames.push(frame.data);
  }
  return frames;
}

describe("SseParser", () => {
  it("reads one LF frame", () => {
    expect(collect(["data: {\"a\":1}\n\n"])).toEqual(['{"a":1}']);
  });

  it("reads CRLF and bare-CR endings", () => {
    expect(collect(["data: one\r\n\r\ndata: two\r\r"])).toEqual(["one", "two"]);
  });

  it("does not lose a frame when CRLF is split across chunks", () => {
    expect(collect(["data: one\r", "\n\r", "\ndata: two\r\n\r\n"])).toEqual(["one", "two"]);
  });

  it("joins multiline data with newlines", () => {
    expect(collect(["data: first\ndata: second\n\n"])).toEqual(["first\nsecond"]);
  });

  it("ignores comments, event, id and retry fields", () => {
    expect(
      collect([
        ": heartbeat\n\n",
        "event: workspace.opened\nid: 4\nretry: 1000\ndata: payload\n\n",
      ]),
    ).toEqual(["payload"]);
  });

  it("removes one leading space from a value and keeps the rest", () => {
    expect(collect(["data:   two spaces\n\n"])).toEqual(["  two spaces"]);
  });

  it("strips a leading byte-order mark", () => {
    expect(collect(["\ufeffdata: value\n\n"])).toEqual(["value"]);
  });

  it("dispatches a final frame even when the stream ends without a blank line", () => {
    expect(collect(["data: last"])).toEqual(["last"]);
  });

  it("does not emit empty data frames", () => {
    expect(collect(["data\n\n: comment\n\n"])).toEqual([]);
  });

  it("survives every split of a two-frame stream", () => {
    const source = "data: one\n\ndata: two\n\n";
    for (let index = 0; index <= source.length; index += 1) {
      expect(collect([source.slice(0, index), source.slice(index)])).toEqual(["one", "two"]);
    }
  });

  it("refuses a frame larger than the reviewed bound", () => {
    const parser = new SseParser();

    expect(() => parser.push(`data: ${"x".repeat(MAX_SSE_FRAME_CHARS + 1)}`)).toThrow(
      SseParseError,
    );
    try {
      parser.push(`data: ${"x".repeat(MAX_SSE_FRAME_CHARS + 1)}`);
    } catch (error) {
      expect((error as SseParseError).reason).toBe("frame_too_large");
    }
  });

  it("can be reset after a refusal and read the next stream", () => {
    const parser = new SseParser();
    expect(() => parser.push(`data: ${"x".repeat(MAX_SSE_FRAME_CHARS + 1)}`)).toThrow();
    parser.reset();
    expect(parser.push("data: fresh\n\n").map((frame) => frame.data)).toEqual(["fresh"]);
  });
});
