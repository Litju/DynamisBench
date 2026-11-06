/**
 * Placement of the stage's notes (marginalia) so that none covers another or the HUD.
 *
 * Each note wants to sit beside its joint; in deep flexion, seen obliquely, the hip and the
 * ankle project close together and their notes (both on the left) would be drawn over each
 * other. Notes on the same side are therefore stacked in the order of the heights they want,
 * at least `gap` apart, and kept between the stage's top and their own floor — the stage's
 * bottom, or the HUD's top for a note that would otherwise lie over the HUD.
 */

export interface NoteRequest {
  readonly key: number;
  readonly side: "left" | "right";
  /** The top edge the note would take on its own. */
  readonly top: number;
  readonly height: number;
  /** The lowest its bottom edge may go (stage bottom, or the HUD's top). */
  readonly floor: number;
}

export interface Rect {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
}

/** Top edges, by key, such that notes on one side never overlap and respect their floors. */
export function stackNotes(requests: readonly NoteRequest[], ceiling: number, gap = 4): Map<number, number> {
  const placed = new Map<number, number>();
  for (const side of ["left", "right"] as const) {
    const column = requests.filter((note) => note.side === side).sort((a, b) => a.top - b.top || a.key - b.key);
    const tops = column.map((note) => Math.max(ceiling, Math.min(note.top, note.floor - note.height)));
    // Downward: each note starts below the one above it.
    for (let index = 1; index < column.length; index += 1) {
      const above = column[index - 1]!;
      tops[index] = Math.max(tops[index]!, tops[index - 1]! + above.height + gap);
    }
    // Upward: a note pushed past its floor lifts itself and, if need be, the ones above it.
    for (let index = column.length - 1; index >= 0; index -= 1) {
      const note = column[index]!;
      let limit = note.floor - note.height;
      if (index + 1 < column.length) {
        limit = Math.min(limit, tops[index + 1]! - gap - note.height);
      }
      tops[index] = Math.max(ceiling, Math.min(tops[index]!, limit));
    }
    column.forEach((note, index) => placed.set(note.key, tops[index]!));
  }
  return placed;
}

export function intersects(a: Rect, b: Rect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}
