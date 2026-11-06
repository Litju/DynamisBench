/**
 * Display helpers over published frame columns: lookup, time ↔ frame, phases and scales.
 *
 * Nothing here is a scientific computation. Frames are recorded snapshots and are looked up,
 * never interpolated into states the simulation did not produce. The few *display derivations*
 * the workbench performs are named as such where they are defined: a sign flip to show an
 * extensor moment, a unit conversion, the sum of two published foot forces, the difference of
 * two published series on the same sample grid, and the convex hull of published load-bearing
 * contact points. The authoritative scalars (extrema, checks, ledgers) are always the published
 * ones, read from the recording.
 */

import type { LaboratoryFrameTable, LaboratoryPhaseSpan } from "../api/laboratory-types";

/** A value of a typed column, or NaN outside it (the workbench shows "—" for NaN). */
export function at(values: Float64Array | undefined, index: number): number {
  if (values === undefined) {
    return Number.NaN;
  }
  return values[index] ?? Number.NaN;
}

/** A named column of a table, or undefined when the group does not publish it. */
export function column(
  table: LaboratoryFrameTable | undefined,
  name: string,
): Float64Array | undefined {
  return table?.columns.get(name);
}

/** The recorded frame nearest to `time` (frames are snapshots; none is synthesised). */
export function frameAt(time: number, period: number, count: number): number {
  if (count <= 0 || !(period > 0) || !Number.isFinite(time)) {
    return 0;
  }
  return Math.min(count - 1, Math.max(0, Math.round(time / period)));
}

/** The time of a frame, read from the table when it is loaded, else from the sample grid. */
export function timeOf(frame: number, period: number, t?: Float64Array): number {
  const recorded = at(t, frame);
  return Number.isFinite(recorded) ? recorded : frame * period;
}

export interface PlaybackState {
  readonly time: number;
  readonly playing: boolean;
}

/**
 * Advance playback by `elapsed` wall-clock seconds at `speed`.
 *
 * At the end a looping playback wraps to the start; otherwise it stops on the last frame.
 * Negative or non-finite elapsed time (a clock that went backwards, a background tab) does
 * not move playback.
 */
export function advance(
  state: PlaybackState,
  elapsed: number,
  speed: number,
  duration: number,
  loop: boolean,
): PlaybackState {
  if (!state.playing || !(elapsed > 0) || !Number.isFinite(elapsed)) {
    return state;
  }
  // A quarter second of wall time is the most one step may advance: a stalled tab or a slow
  // renderer resumes close to where it was rather than jumping through the recording.
  const step = Math.min(elapsed, 0.25) * speed;
  const next = state.time + step;
  if (next <= duration) {
    return { time: next, playing: true };
  }
  return loop ? { time: next - duration, playing: true } : { time: duration, playing: false };
}

/** The phase span containing `time`, or the last span that started before it. */
export function phaseAt(
  spans: readonly LaboratoryPhaseSpan[],
  time: number,
): LaboratoryPhaseSpan | null {
  let found: LaboratoryPhaseSpan | null = null;
  for (const span of spans) {
    if (span.start_s <= time + 1e-9) {
      found = span;
    }
  }
  return found;
}

/** Phase boundaries (start times after the first), sorted. */
export function phaseBoundaries(spans: readonly LaboratoryPhaseSpan[]): number[] {
  return spans
    .map((span) => span.start_s)
    .filter((start) => start > 0)
    .sort((a, b) => a - b);
}

/** The next (direction 1) or previous (direction −1) phase boundary from `time`. */
export function nearestBoundary(
  spans: readonly LaboratoryPhaseSpan[],
  time: number,
  direction: 1 | -1,
  duration: number,
): number {
  const boundaries = [0, ...phaseBoundaries(spans), duration];
  if (direction === 1) {
    return boundaries.find((boundary) => boundary > time + 1e-6) ?? duration;
  }
  return [...boundaries].reverse().find((boundary) => boundary < time - 1e-6) ?? 0;
}

/** The [min, max] of several series, padded; a flat or empty series gets a unit span. */
export function extent(
  series: readonly (Float64Array | readonly number[])[],
  pad = 0.06,
): [number, number] {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const values of series) {
    for (const value of values) {
      if (Number.isFinite(value)) {
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
    }
  }
  if (!Number.isFinite(min)) {
    return [0, 1];
  }
  if (max - min < 1e-12) {
    const half = Math.max(Math.abs(min) * 0.1, 0.5);
    return [min - half, max + half];
  }
  const margin = (max - min) * pad;
  return [min - margin, max + margin];
}

/** "Nice" tick values covering [min, max] (1, 2, 2.5, 5 × 10ⁿ steps). */
export function niceTicks(min: number, max: number, target = 5): number[] {
  if (!(max > min) || !Number.isFinite(min) || !Number.isFinite(max)) {
    return [];
  }
  const raw = (max - min) / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const residual = raw / magnitude;
  const step =
    (residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 2.5 ? 2.5 : residual <= 5 ? 5 : 10) *
    magnitude;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-9; value += step) {
    ticks.push(Math.abs(value) < step * 1e-9 ? 0 : Number(value.toPrecision(12)));
  }
  return ticks;
}

/** Map each value through `transform`, as a new column (a display derivation, see above). */
export function mapColumn(
  values: Float64Array | undefined,
  transform: (value: number, index: number) => number,
): Float64Array | undefined {
  if (values === undefined) {
    return undefined;
  }
  const out = new Float64Array(values.length);
  for (let i = 0; i < values.length; i += 1) {
    out[i] = transform(values[i] ?? Number.NaN, i);
  }
  return out;
}

/** Element-wise combination of two published columns on the same sample grid. */
export function combine(
  a: Float64Array | undefined,
  b: Float64Array | undefined,
  operation: (x: number, y: number) => number,
): Float64Array | undefined {
  if (a === undefined || b === undefined) {
    return undefined;
  }
  const length = Math.min(a.length, b.length);
  const out = new Float64Array(length);
  for (let i = 0; i < length; i += 1) {
    out[i] = operation(a[i] ?? Number.NaN, b[i] ?? Number.NaN);
  }
  return out;
}

export type Point2 = readonly [number, number];

/**
 * Convex hull (Andrew's monotone chain), counter-clockwise, of published points — the drawn
 * outline of the load-bearing support polygon. A display derivation: the authoritative CoP
 * margin is the published `cop_margin_m` column.
 */
export function convexHull(points: readonly Point2[]): Point2[] {
  const sorted = [...points].sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  if (sorted.length <= 2) {
    return sorted;
  }
  const cross = (o: Point2, a: Point2, b: Point2) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Point2[] = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, point) <= 0) {
      lower.pop();
    }
    lower.push(point);
  }
  const upper: Point2[] = [];
  for (const point of [...sorted].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, point) <= 0) {
      upper.pop();
    }
    upper.push(point);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** Format a number for a readout: fixed decimals, a real minus sign, "—" for NaN. */
export function formatNumber(value: number | null | undefined, digits = 2, signed = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const fixed = Math.abs(value).toFixed(digits);
  const zero = Number(fixed) === 0;
  const sign = value < 0 && !zero ? "−" : signed ? "+" : "";
  return `${sign}${fixed}`;
}

/** The first `length` characters of a digest, for ribbons and tables. */
export function shortDigest(digest: string, length = 12): string {
  return digest.slice(0, length);
}
