/**
 * Dual-quaternion skinning of the anatomical figure with recorded body poses.
 *
 * Each bone's skinning transform takes the bind pose to the recorded pose of its body:
 * `M_b = T(recorded_b) · T(bind_b)⁻¹`. A vertex's transform is the normalized, weight-blended
 * dual quaternion of its bones (Kavan et al. 2007), which keeps limbs from collapsing at the
 * joints the way linear blending does. Nothing is simulated, interpolated or smoothed in time:
 * frame *n* of the figure is the bind surface carried by frame *n*'s recorded body poses.
 */

import type { FigureAsset } from "./figure";

/** Per bone: real (w, x, y, z) and dual (w, x, y, z) parts, 8 numbers. */
export type BoneDualQuaternions = Float64Array;

export interface BonePose {
  readonly position: readonly [number, number, number];
  /** (w, x, y, z) */
  readonly quaternion: readonly [number, number, number, number];
}

/** The skinning dual quaternion of every bone, from its recorded pose. */
export function boneDualQuaternions(figure: FigureAsset, poses: readonly BonePose[]): BoneDualQuaternions {
  const out = new Float64Array(figure.bones.length * 8);
  figure.bones.forEach((bone, b) => {
    const pose = poses[b];
    if (pose === undefined) {
      throw new Error(`no recorded pose for ${bone.name}`);
    }
    let [qw, qx, qy, qz] = pose.quaternion;
    const norm = Math.hypot(qw, qx, qy, qz) || 1;
    qw /= norm;
    qx /= norm;
    qy /= norm;
    qz /= norm;
    const [bw, bx, by, bz] = bone.bindQuaternion;
    // r = q · conj(bind)
    const rw = qw * bw + qx * bx + qy * by + qz * bz;
    const rx = -qw * bx + qx * bw - qy * bz + qz * by;
    const ry = -qw * by + qx * bz + qy * bw - qz * bx;
    const rz = -qw * bz - qx * by + qy * bx + qz * bw;
    // t = p − r · P · conj(r)
    const [px, py, pz] = bone.bindPosition;
    const [rpx, rpy, rpz] = rotate(rw, rx, ry, rz, px, py, pz);
    const tx = pose.position[0] - rpx;
    const ty = pose.position[1] - rpy;
    const tz = pose.position[2] - rpz;
    // d = ½ (0, t) · r
    const dw = -0.5 * (tx * rx + ty * ry + tz * rz);
    const dx = 0.5 * (tx * rw + ty * rz - tz * ry);
    const dy = 0.5 * (-tx * rz + ty * rw + tz * rx);
    const dz = 0.5 * (tx * ry - ty * rx + tz * rw);
    out.set([rw, rx, ry, rz, dw, dx, dy, dz], b * 8);
  });
  return out;
}

function rotate(w: number, x: number, y: number, z: number, vx: number, vy: number, vz: number): [number, number, number] {
  // v + 2w (q × v) + 2 q × (q × v)
  const cx = y * vz - z * vy;
  const cy = z * vx - x * vz;
  const cz = x * vy - y * vx;
  return [
    vx + 2 * (w * cx + (y * cz - z * cy)),
    vy + 2 * (w * cy + (z * cx - x * cz)),
    vz + 2 * (w * cz + (x * cy - y * cx)),
  ];
}

/**
 * Skin every vertex (positions and normals) into the output arrays. `out*` may be the arrays a
 * GPU buffer reads, so nothing is allocated per frame.
 */
export function skinFigure(
  figure: FigureAsset,
  bones: BoneDualQuaternions,
  outPositions: Float32Array,
  outNormals: Float32Array,
): void {
  const { positions, normals, joints, weights, vertexCount } = figure;
  for (let v = 0; v < vertexCount; v += 1) {
    const base = v * 4;
    const pivot = joints[base]! * 8;
    const pw = bones[pivot]!;
    const px = bones[pivot + 1]!;
    const py = bones[pivot + 2]!;
    const pz = bones[pivot + 3]!;
    let rw = 0;
    let rx = 0;
    let ry = 0;
    let rz = 0;
    let dw = 0;
    let dx = 0;
    let dy = 0;
    let dz = 0;
    for (let k = 0; k < 4; k += 1) {
      const weight = weights[base + k]!;
      if (weight === 0) {
        continue;
      }
      const o = joints[base + k]! * 8;
      const qw = bones[o]!;
      const qx = bones[o + 1]!;
      const qy = bones[o + 2]!;
      const qz = bones[o + 3]!;
      // Blend in the pivot's hemisphere (q and −q are the same rotation).
      const s = qw * pw + qx * px + qy * py + qz * pz < 0 ? -weight : weight;
      rw += s * qw;
      rx += s * qx;
      ry += s * qy;
      rz += s * qz;
      dw += s * bones[o + 4]!;
      dx += s * bones[o + 5]!;
      dy += s * bones[o + 6]!;
      dz += s * bones[o + 7]!;
    }
    const norm = Math.hypot(rw, rx, ry, rz) || 1;
    rw /= norm;
    rx /= norm;
    ry /= norm;
    rz /= norm;
    dw /= norm;
    dx /= norm;
    dy /= norm;
    dz /= norm;
    // translation t = 2 (rw d − dw r + r × d) (vector parts)
    const tx = 2 * (rw * dx - dw * rx + (ry * dz - rz * dy));
    const ty = 2 * (rw * dy - dw * ry + (rz * dx - rx * dz));
    const tz = 2 * (rw * dz - dw * rz + (rx * dy - ry * dx));
    const i = v * 3;
    const [x, y, z] = rotate(rw, rx, ry, rz, positions[i]!, positions[i + 1]!, positions[i + 2]!);
    outPositions[i] = x + tx;
    outPositions[i + 1] = y + ty;
    outPositions[i + 2] = z + tz;
    const [nx, ny, nz] = rotate(rw, rx, ry, rz, normals[i]!, normals[i + 1]!, normals[i + 2]!);
    outNormals[i] = nx;
    outNormals[i + 1] = ny;
    outNormals[i + 2] = nz;
  }
}

/** The weight of one bone at every vertex (for highlighting a selected segment). */
export function boneInfluence(figure: FigureAsset, bone: number, out: Float32Array): void {
  const { joints, weights, vertexCount } = figure;
  for (let v = 0; v < vertexCount; v += 1) {
    let sum = 0;
    for (let k = 0; k < 4; k += 1) {
      if (joints[v * 4 + k] === bone) {
        sum += weights[v * 4 + k]!;
      }
    }
    out[v] = sum;
  }
}

/** The bone with the largest weight at a vertex. */
export function dominantBone(figure: FigureAsset, vertex: number): number {
  let best = 0;
  let weight = -1;
  for (let k = 0; k < 4; k += 1) {
    const w = figure.weights[vertex * 4 + k]!;
    if (w > weight) {
      weight = w;
      best = figure.joints[vertex * 4 + k]!;
    }
  }
  return best;
}
