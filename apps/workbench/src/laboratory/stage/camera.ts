/**
 * The stage camera as an orbit about a target: azimuth, elevation, distance (z is up).
 *
 * Pure functions, so presets, dragging and zooming are testable without WebGL. The world is the
 * model's own frame: +x is anterior (the athlete faces +x), +y is the athlete's left, +z is up.
 */

import type { ViewPreset } from "../store";

export interface Orbit {
  /** Degrees from +x toward +y. */
  readonly azimuth: number;
  /** Degrees above the floor plane. */
  readonly elevation: number;
  /** Metres from the target. */
  readonly distance: number;
  readonly target: readonly [number, number, number];
}

export const MIN_DISTANCE = 0.8;
export const MAX_DISTANCE = 12;
export const MIN_ELEVATION = -10;
export const MAX_ELEVATION = 89;

/** The stage's view presets, framed on a standing athlete with the bar on the shoulders. */
export function presetOrbit(preset: ViewPreset, target: readonly [number, number, number]): Orbit {
  switch (preset) {
    case "oblique":
      return { azimuth: -58, elevation: 13, distance: 4.1, target };
    case "sagittal":
      return { azimuth: -90, elevation: 4, distance: 4.3, target };
    case "frontal":
      return { azimuth: 0, elevation: 4, distance: 4.3, target };
    case "plan":
      return { azimuth: -90, elevation: 89, distance: 4.4, target: [target[0], target[1], 0.4] };
  }
}

/** The camera position of an orbit. */
export function orbitPosition(orbit: Orbit): [number, number, number] {
  const az = (orbit.azimuth * Math.PI) / 180;
  const el = (orbit.elevation * Math.PI) / 180;
  const [x, y, z] = orbit.target;
  return [
    x + orbit.distance * Math.cos(el) * Math.cos(az),
    y + orbit.distance * Math.cos(el) * Math.sin(az),
    z + orbit.distance * Math.sin(el),
  ];
}

/** Rotate by a pointer drag of (dx, dy) CSS pixels. */
export function orbitDrag(orbit: Orbit, dx: number, dy: number): Orbit {
  return {
    ...orbit,
    azimuth: wrapDegrees(orbit.azimuth - dx * 0.35),
    elevation: Math.min(MAX_ELEVATION, Math.max(MIN_ELEVATION, orbit.elevation + dy * 0.3)),
  };
}

/** Zoom by a wheel delta (positive is away). */
export function orbitZoom(orbit: Orbit, deltaY: number): Orbit {
  const factor = Math.exp(Math.max(-1, Math.min(1, deltaY * 0.0012)));
  return {
    ...orbit,
    distance: Math.min(MAX_DISTANCE, Math.max(MIN_DISTANCE, orbit.distance * factor)),
  };
}

/** Pan the target in the camera's screen plane by (dx, dy) CSS pixels at `height` pixels. */
export function orbitPan(orbit: Orbit, dx: number, dy: number, height: number, fovDeg: number): Orbit {
  const metresPerPixel =
    (2 * orbit.distance * Math.tan((fovDeg * Math.PI) / 360)) / Math.max(1, height);
  const az = (orbit.azimuth * Math.PI) / 180;
  const el = (orbit.elevation * Math.PI) / 180;
  // Screen right and screen up, in world coordinates.
  const right: [number, number, number] = [-Math.sin(az), Math.cos(az), 0];
  const up: [number, number, number] = [
    -Math.sin(el) * Math.cos(az),
    -Math.sin(el) * Math.sin(az),
    Math.cos(el),
  ];
  const [x, y, z] = orbit.target;
  return {
    ...orbit,
    target: [
      x - (right[0] * dx - up[0] * dy) * metresPerPixel,
      y - (right[1] * dx - up[1] * dy) * metresPerPixel,
      z - (right[2] * dx - up[2] * dy) * metresPerPixel,
    ],
  };
}

export function wrapDegrees(value: number): number {
  const wrapped = ((((value + 180) % 360) + 360) % 360) - 180;
  return wrapped === -180 ? 180 : wrapped;
}
