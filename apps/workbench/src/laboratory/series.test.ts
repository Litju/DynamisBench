/**
 * Display helpers: frame lookup never synthesises a state, playback advances by the wall clock,
 * phases and scales are what the readouts need.
 */

import { describe, expect, it } from "vitest";

import {
  advance,
  at,
  combine,
  convexHull,
  extent,
  formatNumber,
  frameAt,
  mapColumn,
  nearestBoundary,
  niceTicks,
  phaseAt,
  phaseBoundaries,
  timeOf,
} from "./series";

const SPANS = [
  { phase: "standing", start_s: 0, end_s: 0.99 },
  { phase: "descent", start_s: 1, end_s: 2.49 },
  { phase: "bottom", start_s: 2.5, end_s: 2.79 },
  { phase: "ascent", start_s: 2.8, end_s: 3.99 },
  { phase: "return", start_s: 4, end_s: 5.5 },
];

describe("frame lookup", () => {
  it("returns the nearest recorded frame and clamps to the recording", () => {
    expect(frameAt(0, 0.01, 551)).toBe(0);
    expect(frameAt(2.204, 0.01, 551)).toBe(220);
    expect(frameAt(2.206, 0.01, 551)).toBe(221);
    expect(frameAt(-1, 0.01, 551)).toBe(0);
    expect(frameAt(99, 0.01, 551)).toBe(550);
    expect(frameAt(Number.NaN, 0.01, 551)).toBe(0);
  });

  it("reads a time from the table when it has one", () => {
    const t = Float64Array.from([0, 0.01, 0.02, 0.0237]);
    expect(timeOf(3, 0.01, t)).toBe(0.0237);
    expect(timeOf(3, 0.01)).toBeCloseTo(0.03, 12);
    expect(at(t, 9)).toBeNaN();
    expect(at(undefined, 0)).toBeNaN();
  });
});

describe("playback", () => {
  it("advances by wall time × speed while playing", () => {
    expect(advance({ time: 1, playing: true }, 0.016, 1, 5.5, false).time).toBeCloseTo(1.016, 12);
    expect(advance({ time: 1, playing: true }, 0.016, 0.25, 5.5, false).time).toBeCloseTo(1.004, 12);
  });

  it("does not move while paused, or for a clock that went backwards", () => {
    expect(advance({ time: 1, playing: false }, 0.5, 1, 5.5, true)).toEqual({ time: 1, playing: false });
    expect(advance({ time: 1, playing: true }, -0.5, 1, 5.5, true)).toEqual({ time: 1, playing: true });
  });

  it("stops on the last frame, or wraps when looping", () => {
    expect(advance({ time: 5.49, playing: true }, 0.05, 1, 5.5, false)).toEqual({ time: 5.5, playing: false });
    const wrapped = advance({ time: 5.49, playing: true }, 0.05, 1, 5.5, true);
    expect(wrapped.playing).toBe(true);
    expect(wrapped.time).toBeCloseTo(0.04, 12);
  });

  it("never jumps more than a quarter second of wall time in one step", () => {
    expect(advance({ time: 0, playing: true }, 30, 1, 5.5, false).time).toBeCloseTo(0.25, 12);
  });
});

describe("phases", () => {
  it("finds the phase in force at a time", () => {
    expect(phaseAt(SPANS, 0.5)?.phase).toBe("standing");
    expect(phaseAt(SPANS, 2.995)?.phase).toBe("ascent");
    expect(phaseAt(SPANS, 2.5)?.phase).toBe("bottom");
  });

  it("steps between phase boundaries", () => {
    expect(phaseBoundaries(SPANS)).toEqual([1, 2.5, 2.8, 4]);
    expect(nearestBoundary(SPANS, 2.2, 1, 5.5)).toBe(2.5);
    expect(nearestBoundary(SPANS, 2.5, 1, 5.5)).toBe(2.8);
    expect(nearestBoundary(SPANS, 2.5, -1, 5.5)).toBe(1);
    expect(nearestBoundary(SPANS, 4.5, 1, 5.5)).toBe(5.5);
    expect(nearestBoundary(SPANS, 0.5, -1, 5.5)).toBe(0);
  });
});

describe("scales", () => {
  it("pads extents and gives a flat series a span", () => {
    expect(extent([Float64Array.from([0, 10])], 0.1)).toEqual([-1, 11]);
    expect(extent([Float64Array.from([2, 2])])).toEqual([1.5, 2.5]);
    expect(extent([])).toEqual([0, 1]);
    expect(extent([Float64Array.from([Number.NaN, 3, 4])], 0)).toEqual([3, 4]);
  });

  it("picks round tick steps", () => {
    expect(niceTicks(0, 5.5, 6)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(niceTicks(-5, 150, 5)).toEqual([0, 50, 100, 150]);
    expect(niceTicks(0.76, 1.31, 5)).toEqual([0.8, 1, 1.2]);
    expect(niceTicks(0.76, 1.31, 10)).toEqual([0.8, 0.9, 1, 1.1, 1.2, 1.3]);
    expect(niceTicks(1, 1)).toEqual([]);
  });

  it("formats with a real minus sign and a dash for missing values", () => {
    expect(formatNumber(-93.74, 1)).toBe("−93.7");
    expect(formatNumber(58.2, 1, true)).toBe("+58.2");
    expect(formatNumber(-0.0001, 2)).toBe("0.00");
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatNumber(null)).toBe("—");
  });
});

describe("display derivations", () => {
  it("maps and combines columns element-wise", () => {
    const a = Float64Array.from([1, 2, 3]);
    const b = Float64Array.from([10, 20]);
    expect(mapColumn(a, (v) => -v)).toEqual(Float64Array.from([-1, -2, -3]));
    expect(combine(a, b, (x, y) => x + y)).toEqual(Float64Array.from([11, 22]));
    expect(combine(a, undefined, (x, y) => x + y)).toBeUndefined();
  });

  it("outlines loaded points with their convex hull", () => {
    const hull = convexHull([
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
      [0.5, 0.5],
    ]);
    expect(hull).toHaveLength(4);
    expect(hull).not.toContainEqual([0.5, 0.5]);
    expect(convexHull([[0, 0]])).toEqual([[0, 0]]);
  });
});
