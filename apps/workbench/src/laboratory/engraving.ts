/**
 * Engraved (SVG) drawings of one recorded instant, for the Model Atlas plates.
 *
 * An orthographic projection of the compiled model's geoms, each placed at its body's recorded
 * world pose: capsules and cylinders as stroked segments, ellipsoids as their projected
 * ellipses, boxes as the hull of their projected corners, sole points as dots. Depth-sorted so
 * near segments cover far ones. Geometry only — no value is computed that the model or the
 * recording did not publish.
 */

import type { LaboratoryFrameTable, LaboratoryGeom, LaboratoryModelResponse } from "../api/laboratory-types";
import { at, column, convexHull, type Point2 } from "./series";

export type Vector3 = [number, number, number];
type Matrix3 = [number, number, number, number, number, number, number, number, number];

/** Row-major rotation matrix of a (w, x, y, z) quaternion. */
export function rotation(q: readonly number[]): Matrix3 {
  const [w0 = 1, x0 = 0, y0 = 0, z0 = 0] = q;
  const n = Math.hypot(w0, x0, y0, z0) || 1;
  const w = w0 / n;
  const x = x0 / n;
  const y = y0 / n;
  const z = z0 / n;
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
    2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
    2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y),
  ];
}

function multiply(a: Matrix3, b: Matrix3): Matrix3 {
  const out = new Array<number>(9).fill(0) as Matrix3;
  for (let r = 0; r < 3; r += 1) {
    for (let c = 0; c < 3; c += 1) {
      let sum = 0;
      for (let k = 0; k < 3; k += 1) {
        sum += a[r * 3 + k]! * b[k * 3 + c]!;
      }
      out[r * 3 + c] = sum;
    }
  }
  return out;
}

function apply(m: Matrix3, v: readonly number[]): Vector3 {
  const [x = 0, y = 0, z = 0] = v;
  return [m[0] * x + m[1] * y + m[2] * z, m[3] * x + m[4] * y + m[5] * z, m[6] * x + m[7] * y + m[8] * z];
}

function columnOf(m: Matrix3, c: number): Vector3 {
  return [m[c]!, m[3 + c]!, m[6 + c]!];
}

const dot = (a: readonly number[], b: readonly number[]) => (a[0] ?? 0) * (b[0] ?? 0) + (a[1] ?? 0) * (b[1] ?? 0) + (a[2] ?? 0) * (b[2] ?? 0);

/** An orthographic view: azimuth/elevation of the viewer, pixels per metre, screen origin. */
export interface OrthoView {
  readonly azimuth: number;
  readonly elevation: number;
  readonly scale: number;
  readonly origin: readonly [number, number];
  readonly target: Vector3;
}

export function viewBasis(view: OrthoView): { right: Vector3; up: Vector3; toward: Vector3 } {
  const a = (view.azimuth * Math.PI) / 180;
  const e = (view.elevation * Math.PI) / 180;
  const toward: Vector3 = [Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e)];
  // right = forward × z, with forward = −toward
  const right: Vector3 = [-toward[1], toward[0], 0];
  const norm = Math.hypot(right[0], right[1]) || 1;
  right[0] /= norm;
  right[1] /= norm;
  // up = right × forward
  const forward: Vector3 = [-toward[0], -toward[1], -toward[2]];
  const up: Vector3 = [
    right[1] * forward[2] - right[2] * forward[1],
    right[2] * forward[0] - right[0] * forward[2],
    right[0] * forward[1] - right[1] * forward[0],
  ];
  return { right, up, toward };
}

export function projectPoint(view: OrthoView, point: readonly number[]): [number, number, number] {
  const { right, up, toward } = viewBasis(view);
  const p: Vector3 = [
    (point[0] ?? 0) - view.target[0],
    (point[1] ?? 0) - view.target[1],
    (point[2] ?? 0) - view.target[2],
  ];
  return [view.origin[0] + view.scale * dot(p, right), view.origin[1] - view.scale * dot(p, up), dot(p, toward)];
}

export type EngravedItem =
  | { kind: "segment"; body: string; geom: string; role: LaboratoryGeom["role"]; depth: number; a: Point2; b: Point2; width: number; round: boolean }
  | { kind: "ellipse"; body: string; geom: string; role: LaboratoryGeom["role"]; depth: number; cx: number; cy: number; rx: number; ry: number; angle: number }
  | { kind: "polygon"; body: string; geom: string; role: LaboratoryGeom["role"]; depth: number; points: Point2[] }
  | { kind: "dot"; body: string; geom: string; role: LaboratoryGeom["role"]; depth: number; cx: number; cy: number; r: number };

/** The world pose of a body at a frame, from the recorded pose columns. */
export function bodyPose(pose: LaboratoryFrameTable, body: string, frame: number): { position: Vector3; rotation: Matrix3 } | null {
  const px = at(column(pose, `${body}.px`), frame);
  if (!Number.isFinite(px)) {
    return null;
  }
  return {
    position: [px, at(column(pose, `${body}.py`), frame), at(column(pose, `${body}.pz`), frame)],
    rotation: rotation([
      at(column(pose, `${body}.qw`), frame),
      at(column(pose, `${body}.qx`), frame),
      at(column(pose, `${body}.qy`), frame),
      at(column(pose, `${body}.qz`), frame),
    ]),
  };
}

/** Every drawable geom at `frame`, projected and depth-sorted far to near. */
export function engrave(
  model: LaboratoryModelResponse,
  pose: LaboratoryFrameTable,
  frame: number,
  view: OrthoView,
): EngravedItem[] {
  const { right, up } = viewBasis(view);
  const items: EngravedItem[] = [];
  for (const geom of model.geoms) {
    if (geom.role === "floor" || geom.body === "world") {
      continue;
    }
    const body = bodyPose(pose, geom.body, frame);
    if (body === null) {
      continue;
    }
    const local = apply(body.rotation, geom.position_m);
    const centre: Vector3 = [body.position[0] + local[0], body.position[1] + local[1], body.position[2] + local[2]];
    const orientation = multiply(body.rotation, rotation(geom.quaternion));
    const [cx, cy, depth] = projectPoint(view, centre);
    const [s0, s1, s2] = geom.size_m;
    const base = { body: geom.body, geom: geom.name, role: geom.role, depth };
    switch (geom.type) {
      case "capsule":
      case "cylinder": {
        const axis = columnOf(orientation, 2);
        const a = projectPoint(view, [centre[0] + axis[0] * s1, centre[1] + axis[1] * s1, centre[2] + axis[2] * s1]);
        const b = projectPoint(view, [centre[0] - axis[0] * s1, centre[1] - axis[1] * s1, centre[2] - axis[2] * s1]);
        items.push({ ...base, kind: "segment", a: [a[0], a[1]], b: [b[0], b[1]], width: 2 * s0 * view.scale, round: geom.type === "capsule" });
        break;
      }
      case "ellipsoid": {
        // Silhouette of an ellipsoid under orthographic projection: the 2×2 projection of
        // M·diag(s²)·Mᵀ onto the screen basis, then its eigen-decomposition.
        const squares = [s0 * s0, s1 * s1, s2 * s2];
        const project2 = (u: Vector3, v: Vector3) => {
          let sum = 0;
          for (let k = 0; k < 3; k += 1) {
            const axis = columnOf(orientation, k);
            sum += squares[k]! * dot(axis, u) * dot(axis, v);
          }
          return sum;
        };
        const a = project2(right, right);
        const b = project2(right, up);
        const d = project2(up, up);
        const mean = (a + d) / 2;
        const radius = Math.sqrt(((a - d) / 2) ** 2 + b * b);
        const major = Math.sqrt(Math.max(mean + radius, 1e-12)) * view.scale;
        const minor = Math.sqrt(Math.max(mean - radius, 1e-12)) * view.scale;
        const angle = (Math.atan2(2 * b, a - d) / 2) * (180 / Math.PI);
        items.push({ ...base, kind: "ellipse", cx, cy, rx: major, ry: minor, angle: -angle });
        break;
      }
      case "box": {
        const corners: Point2[] = [];
        for (const sx of [-1, 1]) {
          for (const sy of [-1, 1]) {
            for (const sz of [-1, 1]) {
              const offset = apply(orientation, [sx * s0, sy * s1, sz * s2]);
              const p = projectPoint(view, [centre[0] + offset[0], centre[1] + offset[1], centre[2] + offset[2]]);
              corners.push([p[0], p[1]]);
            }
          }
        }
        items.push({ ...base, kind: "polygon", points: convexHull(corners) });
        break;
      }
      case "sphere":
        items.push({ ...base, kind: "dot", cx, cy, r: Math.max(1.5, s0 * view.scale) });
        break;
      default:
        break;
    }
  }
  return items.sort((p, q) => p.depth - q.depth);
}
