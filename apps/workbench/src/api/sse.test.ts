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

describe("SseParser frame accounting", () => {
  /** Feed chunks until the parser refuses, and report how much of the input it consumed. */
  function feedUntilRefused(
    parser: SseParser,
    chunk: string,
    maximumChunks: number,
  ): { readonly error: unknown; readonly chars: number } {
    let chars = 0;
    for (let index = 0; index < maximumChunks; index += 1) {
      try {
        parser.push(chunk);
        chars += chunk.length;
      } catch (error) {
        return { error, chars };
      }
    }
    return { error: null, chars };
  }

  it("refuses more than 65,536 empty data lines before the terminating blank line", () => {
    const attack = `${"data:\n".repeat(65_536 + 1)}\n`;
    const chunk = "data:\n".repeat(128);
    const parser = new SseParser();

    const result = feedUntilRefused(parser, chunk, Math.ceil(attack.length / chunk.length));

    expect(result.error).toBeInstanceOf(SseParseError);
    expect((result.error as SseParseError).reason).toBe("frame_too_large");
    // Refused while consuming, not after the whole attack had been buffered.
    expect(result.chars).toBeLessThan(attack.length);
  });

  it("refuses the same attack when the peer never sends a blank line", () => {
    const attack = "data:\n".repeat(65_536 + 1);
    const chunk = "data:\n".repeat(128);
    const parser = new SseParser();

    const result = feedUntilRefused(parser, chunk, Math.ceil(attack.length / chunk.length));

    expect(result.error).toBeInstanceOf(SseParseError);
    expect(result.chars).toBeLessThan(attack.length);
  });

  it("refuses an oversized comment while it is consumed", () => {
    const parser = new SseParser();

    expect(() => parser.push(`: ${"x".repeat(MAX_SSE_FRAME_CHARS + 1)}`)).toThrow(SseParseError);
  });

  it("refuses an oversized ignored field while it is consumed", () => {
    const parser = new SseParser();

    expect(() => parser.push(`event: ${"x".repeat(MAX_SSE_FRAME_CHARS + 1)}`)).toThrow(
      SseParseError,
    );
  });

  it("accepts a legal frame near the ceiling and refuses one character more", () => {
    const parser = new SseParser();
    // "data: " (6) + value + LF (1) + blank-line LF (1) === MAX_SSE_FRAME_CHARS.
    const legalValue = "x".repeat(MAX_SSE_FRAME_CHARS - 8);
    const legalFrame = `data: ${legalValue}\n\n`;

    expect(legalFrame.length).toBe(MAX_SSE_FRAME_CHARS);
    expect(parser.push(legalFrame)).toEqual([{ data: legalValue }]);

    const oversized = new SseParser();
    expect(() => oversized.push(`data: ${legalValue}x\n\n`)).toThrow(SseParseError);
  });

  it("reads a large legal frame delivered in small chunks", () => {
    const value = "y".repeat(60_000);
    const source = `data: ${value}\n\n`;
    const parser = new SseParser();
    const frames: string[] = [];

    for (let offset = 0; offset < source.length; offset += 7) {
      for (const frame of parser.push(source.slice(offset, offset + 7))) {
        frames.push(frame.data);
      }
    }
    for (const frame of parser.end()) {
      frames.push(frame.data);
    }

    expect(frames).toEqual([value]);
  });

  it("counts multiline data separators and can still recover after a refusal", () => {
    const parser = new SseParser();
    const attack = `${"data:\n".repeat(65_536 + 1)}\n`;

    expect(() => parser.push(attack)).toThrow(SseParseError);

    parser.reset();
    expect(parser.push("data: first\ndata: second\n\n").map((frame) => frame.data)).toEqual([
      "first\nsecond",
    ]);
  });
});

/** The observable result of feeding a chunk sequence: frames, or the refusal it raised. */
type ParseOutcome =
  | { readonly kind: "frames"; readonly frames: readonly string[] }
  | { readonly kind: "refused"; readonly reason: string };

function outcomeOf(chunks: readonly string[]): ParseOutcome {
  const parser = new SseParser();
  const frames: string[] = [];
  try {
    for (const chunk of chunks) {
      for (const frame of parser.push(chunk)) {
        frames.push(frame.data);
      }
    }
    for (const frame of parser.end()) {
      frames.push(frame.data);
    }
    return { kind: "frames", frames };
  } catch (error) {
    return {
      kind: "refused",
      reason: error instanceof SseParseError ? error.reason : "unexpected",
    };
  }
}

/**
 * Frame accounting must depend on the bytes, never on where the network split them.
 *
 * A CRLF terminator is two physical characters whether or not a chunk boundary falls between
 * the CR and the LF. The pre-repair parser terminated the line at a trailing CR, charged one
 * character, and then skipped the LF that opened the next chunk, so identical frames were
 * accounted one character shorter per split CRLF. These cases pin the boundary-independent
 * accounting, including the frame that a split blank-line terminator dispatches.
 */
describe("SseParser chunk-boundary-independent frame accounting", () => {
  /** Representative frames, each with CRLF, mixed or bare terminators. */
  const CRLF_SOURCES = [
    "data: one\r\n\r\n",
    "data: first\r\ndata: second\r\n\r\n",
    ": heartbeat\r\nevent: workspace.opened\r\nid: 4\r\nretry: 1000\r\ndata: payload\r\n\r\n",
    "data: a\r\n\r\ndata: b\r\n\r\n",
    "data: \r\ndata:x\r\n\r\n",
    "data\r\n\r\n",
    "data: one\r\rdata: two\r\r",
    "data: mixed\r\ndata: ending\n\n",
  ];

  it("produces the same frames for every two-chunk split of a CRLF stream", () => {
    for (const source of CRLF_SOURCES) {
      const contiguous = outcomeOf([source]);
      expect(contiguous.kind).toBe("frames");
      for (let split = 0; split <= source.length; split += 1) {
        expect(
          outcomeOf([source.slice(0, split), source.slice(split)]),
          `split at ${split} of ${JSON.stringify(source)}`,
        ).toEqual(contiguous);
      }
    }
  });

  it("produces the same frames when CRLF arrives one character per chunk", () => {
    for (const source of CRLF_SOURCES) {
      expect(outcomeOf(Array.from(source))).toEqual(outcomeOf([source]));
    }
  });

  it("attributes a split blank-line terminator to the frame it closes", () => {
    const parser = new SseParser();

    // The trailing CR cannot be resolved until the next character or end-of-stream, so the
    // line is deliberately held rather than terminated with an uncounted LF to follow.
    expect(parser.push("data: one\r")).toEqual([]);
    expect(parser.push("\n\r")).toEqual([]);
    expect(parser.push("\n")).toEqual([{ data: "one" }]);
    expect(parser.end()).toEqual([]);
  });

  it("settles a pending CR at end of stream", () => {
    expect(collect(["data: tail\r"])).toEqual(["tail"]);
    expect(collect(["data: last\r\n\r"])).toEqual(["last"]);
    expect(collect(["data: last\r\n\r", ""])).toEqual(["last"]);
    expect(collect(["data: last\r", "\r"])).toEqual(["last"]);
  });

  it("refuses repeated split-CRLF data lines that the pre-repair accounting accepted", () => {
    // 10,000 lines are 70,002 physical characters: "data:" + CRLF is seven each, and the
    // blank terminator adds two. The pre-repair parser charged 6 per split line (it dropped
    // every LF that began a chunk) and accepted the frame at 60,000 characters.
    const lineCount = 10_000;
    const parser = new SseParser();
    let completedLines = 0;
    let refusal: unknown = null;

    try {
      for (; completedLines < lineCount; completedLines += 1) {
        parser.push("data:\r");
        parser.push("\n");
      }
      parser.push("\r");
      parser.push("\n");
    } catch (error) {
      refusal = error;
    }

    expect(refusal).toBeInstanceOf(SseParseError);
    expect((refusal as SseParseError).reason).toBe("frame_too_large");
    // Refused while consuming, before the whole oversized frame had been buffered.
    expect(completedLines).toBeLessThan(lineCount);

    // The identical bytes as one contiguous chunk are refused as well, so the decision no
    // longer depends on the split.
    expect(() => new SseParser().push(`${"data:\r\n".repeat(lineCount)}\r\n`)).toThrow(
      SseParseError,
    );
  });

  it("accepts a frame at exactly 65,536 characters and refuses one character more", () => {
    // "data: " (6) + value + terminator + terminating blank line === MAX_SSE_FRAME_CHARS.
    const terminators = [
      { name: "LF", terminator: "\n" },
      { name: "CRLF", terminator: "\r\n" },
      { name: "bare CR", terminator: "\r" },
    ] as const;

    for (const { name, terminator } of terminators) {
      const value = "x".repeat(MAX_SSE_FRAME_CHARS - 6 - terminator.length * 2);
      const legal = `data: ${value}${terminator}${terminator}`;

      expect(legal.length, `${name} legal frame`).toBe(MAX_SSE_FRAME_CHARS);
      expect(outcomeOf([legal]), `${name} contiguous`).toEqual({
        kind: "frames",
        frames: [value],
      });

      // Every boundary inside the two terminators must reach the same decision: between the
      // CR and LF of the data line, between the two terminators, and between the CR and LF
      // of the blank line.
      const dataLineEnd = 6 + value.length;
      for (let split = dataLineEnd; split <= dataLineEnd + terminator.length * 2; split += 1) {
        expect(
          outcomeOf([legal.slice(0, split), legal.slice(split)]),
          `${name} split ${split}`,
        ).toEqual({ kind: "frames", frames: [value] });
      }

      const oversized = `data: ${value}x${terminator}${terminator}`;
      expect(oversized.length, `${name} oversized frame`).toBe(MAX_SSE_FRAME_CHARS + 1);
      expect(outcomeOf([oversized]), `${name} contiguous over`).toEqual({
        kind: "refused",
        reason: "frame_too_large",
      });

      const oversizedDataLineEnd = 6 + value.length + 1;
      for (
        let split = oversizedDataLineEnd;
        split <= oversizedDataLineEnd + terminator.length * 2;
        split += 1
      ) {
        expect(
          outcomeOf([oversized.slice(0, split), oversized.slice(split)]),
          `${name} oversized split ${split}`,
        ).toEqual({ kind: "refused", reason: "frame_too_large" });
      }
    }
  });

  it("resets after refusing a split-CRLF oversized frame and reads the next stream", () => {
    const parser = new SseParser();

    expect(() => {
      for (let index = 0; index < 10_000; index += 1) {
        parser.push("data:\r");
        parser.push("\n");
      }
    }).toThrow(SseParseError);

    expect(parser.push("data: fresh\r\n\r\n").map((frame) => frame.data)).toEqual(["fresh"]);
  });
});
