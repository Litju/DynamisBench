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
  private buffer = "";
  private dataLines: string[] = [];
  private frameChars = 0;

  /** Feed one decoded text chunk; returns every frame that completed because of it. */
  push(chunk: string): SseFrame[] {
    if (chunk.length === 0) {
      return [];
    }

    if (this.buffer.length === 0 && chunk.charCodeAt(0) === 0xfeff) {
      // A leading byte-order mark is not part of the first field's name.
      chunk = chunk.slice(1);
    }

    this.buffer += chunk;

    const frames: SseFrame[] = [];
    for (;;) {
      const line = this.takeLine();
      if (line === null) {
        break;
      }
      const frame = this.consumeLine(line);
      if (frame !== null) {
        frames.push(frame);
      }
    }

    if (this.buffer.length + this.frameChars > MAX_SSE_FRAME_CHARS) {
      this.reset();
      throw new SseParseError("frame_too_large");
    }
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
    if (this.buffer.length > 0) {
      const line = this.buffer.endsWith("\r") ? this.buffer.slice(0, -1) : this.buffer;
      this.buffer = "";
      const frame = this.consumeLine(line);
      if (frame !== null) {
        frames.push(frame);
      }
    }
    const final = this.dispatch();
    if (final !== null) {
      frames.push(final);
    }
    return frames;
  }

  reset(): void {
    this.buffer = "";
    this.dataLines = [];
    this.frameChars = 0;
  }

  /**
   * One line, or `null` when the buffer does not yet contain a complete one.
   *
   * A trailing CR is deliberately left in the buffer: the next chunk may begin with the LF
   * that completes a CRLF pair, and treating the CR now as a line break would invent an
   * empty line and dispatch an event early.
   */
  private takeLine(): string | null {
    for (let index = 0; index < this.buffer.length; index += 1) {
      const character = this.buffer[index];
      if (character === "\r") {
        if (index === this.buffer.length - 1) {
          return null;
        }
        const line = this.buffer.slice(0, index);
        const skip = this.buffer[index + 1] === "\n" ? 2 : 1;
        this.buffer = this.buffer.slice(index + skip);
        this.frameChars += line.length;
        return line;
      }
      if (character === "\n") {
        const line = this.buffer.slice(0, index);
        this.buffer = this.buffer.slice(index + 1);
        this.frameChars += line.length;
        return line;
      }
    }
    return null;
  }

  private consumeLine(line: string): SseFrame | null {
    if (line === "") {
      return this.dispatch();
    }

    if (line.startsWith(":")) {
      return null;
    }

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }

    if (field === "data") {
      this.dataLines.push(value);
      this.frameChars += value.length;
      if (this.frameChars > MAX_SSE_FRAME_CHARS) {
        this.reset();
        throw new SseParseError("frame_too_large");
      }
    }

    return null;
  }

  private dispatch(): SseFrame | null {
    if (this.dataLines.length === 0) {
      return null;
    }
    const data = this.dataLines.join("\n");
    this.dataLines = [];
    this.frameChars = 0;
    return data === "" ? null : { data };
  }
}
