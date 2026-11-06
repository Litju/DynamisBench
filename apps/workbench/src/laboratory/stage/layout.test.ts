import { describe, expect, it } from "vitest";

import { intersects, stackNotes, type NoteRequest } from "./layout";

function overlaps(requests: readonly NoteRequest[], tops: Map<number, number>): boolean {
  for (const a of requests) {
    for (const b of requests) {
      if (a.key >= b.key || a.side !== b.side) continue;
      const ta = tops.get(a.key)!;
      const tb = tops.get(b.key)!;
      if (ta < tb + b.height && tb < ta + a.height) return true;
    }
  }
  return false;
}

describe("stage note stacking", () => {
  it("leaves notes that do not collide where they want to be", () => {
    const requests: NoteRequest[] = [
      { key: 0, side: "left", top: 40, height: 48, floor: 400 },
      { key: 2, side: "left", top: 200, height: 48, floor: 400 },
      { key: 1, side: "right", top: 120, height: 48, floor: 400 },
    ];
    const tops = stackNotes(requests, 4);
    expect(tops.get(0)).toBe(40);
    expect(tops.get(2)).toBe(200);
    expect(tops.get(1)).toBe(120);
  });

  it("separates the hip and ankle notes when deep flexion projects them together", () => {
    const requests: NoteRequest[] = [
      { key: 0, side: "left", top: 150, height: 48, floor: 420 },
      { key: 2, side: "left", top: 158, height: 48, floor: 420 },
      { key: 1, side: "right", top: 152, height: 48, floor: 420 },
    ];
    const tops = stackNotes(requests, 4);
    expect(overlaps(requests, tops)).toBe(false);
    // Notes on different sides are independent.
    expect(tops.get(1)).toBe(152);
  });

  it("keeps a note off the HUD and lifts the notes above it rather than overlapping", () => {
    // The ankle note would lie over the HUD, whose top is at 300.
    const requests: NoteRequest[] = [
      { key: 0, side: "left", top: 250, height: 48, floor: 460 },
      { key: 2, side: "left", top: 310, height: 48, floor: 300 },
    ];
    const tops = stackNotes(requests, 4);
    expect(tops.get(2)! + 48).toBeLessThanOrEqual(300);
    expect(overlaps(requests, tops)).toBe(false);
    expect(tops.get(0)! + 48 + 4).toBeLessThanOrEqual(tops.get(2)!);
  });

  it("never places a note above the stage", () => {
    const requests: NoteRequest[] = [
      { key: 0, side: "left", top: -30, height: 48, floor: 120 },
      { key: 2, side: "left", top: -10, height: 48, floor: 120 },
    ];
    const tops = stackNotes(requests, 4);
    expect(Math.min(...tops.values())).toBeGreaterThanOrEqual(4);
    expect(overlaps(requests, tops)).toBe(false);
  });

  it("detects rectangle intersection", () => {
    expect(intersects({ left: 0, top: 0, right: 10, bottom: 10 }, { left: 5, top: 5, right: 15, bottom: 15 })).toBe(true);
    expect(intersects({ left: 0, top: 0, right: 10, bottom: 10 }, { left: 10, top: 0, right: 20, bottom: 10 })).toBe(false);
  });
});
