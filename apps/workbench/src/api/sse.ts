/**
 * A streaming Server-Sent Events frame parser.
 *
 * This module knows the wire format and nothing about the application: it takes decoded text
 * chunks in whatever sizes the network produced and returns the frames that became complete.
 * It never calls `fetch`, never holds a credential, and never interprets an event's JSON — the
 * client does that, so a malformed payload is reported by the layer that knows the contract.
 *
 * What it handles, because a chunk boundary is not a line boundary:
 *
 * * CRLF, bare CR and LF line endings, including a CR at the end of one chunk followed by the
 *   LF at the start of the next;
 * * `data:` fields split across lines and chunks, joined with `\n` as the format requires;
 * * comment lines (`: heartbeat`) and fields this client does not use (`event`, `id`,
 *   `retry`), which are ignored rather than treated as data;
 * * a frame that grows past a reviewed bound, refused instead of buffered without limit.
 *
 * **The bound covers the accumulated frame, not only its data values.** Every character of
 * every line is counted as it arrives — field names, colons, separators, line endings,
 * comments and ignored fields — along with the terminator of the blank line that dispatches
 * the frame. Counting only `data` values let repeated empty `data:` lines grow a data buffer
 * without limit; counting the whole frame makes every line pay for itself. The pending
 * partial line is included in the same check, so a single oversized comment or ignored field
 * is refused while it is consumed rather than after it has been stored.
 *
 * Empty `data` frames are not events. The server's heartbeat is a comment, so it never
 * arrives here as a payload.
 */

/** The ceiling on one frame's accumulated text, matching the transport's bounded payloads. */
export const MAX_SSE_FRAME_CHARS = 64 * 1024;

export class SseParseError extends Error {
  readonly reason: "frame_too_large";

  constructor(reason: "frame_too_large") {
    super(
      reason === "frame_too_large"
        ? "An event frame exceeded the reviewed bound."
        : "The event stream could not be parsed.",
    );
    this.name = "SseParseError";
    this.reason = reason;
  }
}

/** One complete SSE frame: the joined `data` text, and nothing this client does not use. */
export interface SseFrame {
  readonly data: string;
}

export class SseParser {
  /** The characters of the current, not-yet-terminated line. */
  private lineBuffer = "";
  /** Every character counted since the last dispatched frame, including its line endings. */
  private frameChars = 0;
  private dataLines: string[] = [];
  /** A CR ended the previous line; an LF at the next chunk's start belongs to it. */
  private pendingCarriageReturn = false;
  private atStreamStart = true;

  /** Feed one decoded text chunk; returns every frame that completed because of it. */
  push(chunk: string): SseFrame[] {
    if (chunk.length === 0) {
      return [];
    }

    let offset = 0;
    if (this.atStreamStart) {
      this.atStreamStart = false;
      if (chunk.charCodeAt(0) === 0xfeff) {
        // A leading byte-order mark is not part of the first field's name.
        offset = 1;
      }
    }

    const frames: SseFrame[] = [];

    if (this.pendingCarriageReturn) {
      this.pendingCarriageReturn = false;
      if (chunk.charCodeAt(offset) === 0x0a) {
        offset += 1;
      }
    }

    let segmentStart = offset;
    for (let index = offset; index < chunk.length; index += 1) {
      const character = chunk.charCodeAt(index);
      if (character !== 0x0a && character !== 0x0d) {
        continue;
      }

      this.appendSegment(chunk, segmentStart, index);

      const hasFollowingLf = character === 0x0d && chunk.charCodeAt(index + 1) === 0x0a;
      const terminated = this.terminateLine(hasFollowingLf ? 2 : 1);
      if (terminated !== null) {
        frames.push(terminated);
      }

      if (character === 0x0d) {
        if (index + 1 < chunk.length) {
          if (hasFollowingLf) {
            index += 1;
          }
        } else {
          // The LF that may complete this CRLF pair can only arrive in the next chunk.
          this.pendingCarriageReturn = true;
        }
      }

      segmentStart = index + 1;
    }

    this.appendSegment(chunk, segmentStart, chunk.length);
    return frames;
  }

  /**
   * Finish the stream: flush a final unterminated line and dispatch any pending data.
   *
   * A server that closes without a trailing blank line still sent its last frame. The parser
   * dispatches it rather than holding it forever, because the alternative is silently losing
   * the final event of a complete response.
   */
  end(): SseFrame[] {
    const frames: SseFrame[] = [];
    this.pendingCarriageReturn = false;

    if (this.lineBuffer.length > 0) {
      if (this.frameChars + this.lineBuffer.length > MAX_SSE_FRAME_CHARS) {
        this.reset();
        throw new SseParseError("frame_too_large");
      }
      const line = this.lineBuffer;
      this.lineBuffer = "";
      this.frameChars += line.length;
      this.consumeLine(line);
    }

    const final = this.dispatch();
    if (final !== null) {
      frames.push(final);
    }
    return frames;
  }

  reset(): void {
    this.lineBuffer = "";
    this.dataLines = [];
    this.frameChars = 0;
    this.pendingCarriageReturn = false;
    this.atStreamStart = true;
  }

  /**
   * Append a slice of the current chunk to the pending line, bounded as it arrives.
   *
   * The length is checked before the slice is made, so an oversized single line is refused
   * without first copying an unbounded remainder of the chunk into the parser's own buffer.
   */
  private appendSegment(chunk: string, start: number, end: number): void {
    const length = end - start;
    if (this.frameChars + this.lineBuffer.length + length > MAX_SSE_FRAME_CHARS) {
      this.reset();
      throw new SseParseError("frame_too_large");
    }
    if (length > 0) {
      this.lineBuffer += chunk.slice(start, end);
    }
  }

  /**
   * Finish the pending line and account for its text and terminator.
   *
   * A blank line dispatches the frame; every other line contributes to the frame's text,
   * whether it carries data or not. The check happens here and in [`appendSegment`], so the
   * accumulated frame (and its partial line) never exceeds the reviewed ceiling.
   */
  private terminateLine(terminatorLength: number): SseFrame | null {
    const line = this.lineBuffer;
    this.lineBuffer = "";
    this.frameChars += line.length + terminatorLength;
    if (this.frameChars > MAX_SSE_FRAME_CHARS) {
      this.reset();
      throw new SseParseError("frame_too_large");
    }

    if (line === "") {
      return this.dispatch();
    }

    this.consumeLine(line);
    return null;
  }

  private consumeLine(line: string): void {
    if (line.startsWith(":")) {
      // A comment is counted as frame text by terminateLine, and never becomes data.
      return;
    }

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }

    if (field === "data") {
      this.dataLines.push(value);
    }
  }

  private dispatch(): SseFrame | null {
    this.frameChars = 0;
    if (this.dataLines.length === 0) {
      return null;
    }
    const data = this.dataLines.join("\n");
    this.dataLines = [];
    return data === "" ? null : { data };
  }
}
