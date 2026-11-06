/**
 * The anatomical figure: decoding the published figure stream and checking it belongs to the
 * model on show.
 *
 * The figure is a presentation surface derived offline from the model (its skeleton, landmarks
 * and segment masses) by `python/tools/mujoco_squat_figure.py`, pinned by digest in the
 * application and published at `/laboratory/figure`. It is deformed here with the *recorded*
 * body poses only (see `skinning.ts`); it has no role in the mechanics and adds no data.
 *
 * The stream is refused — never repaired — unless it is exactly the format: the magic, a JSON
 * header of the expected schema, sections inside the stream with the lengths the counts imply,
 * triangle indices and bone indices in range, and weights that sum to one per vertex. A figure
 * is then drawn for a model only if its skeleton *is* that model's (same bodies, parents,
 * positions and orientations); otherwise the stage keeps the scientific figure and says why.
 */

import type { LaboratoryModelResponse, Quat, Vec3 } from "../../api/laboratory-types";

export const FIGURE_MAGIC = "DBFIGUR1";
export const FIGURE_SCHEMA = "dynamisbench.laboratory.figure/1";
export const FIGURE_GARMENTS = ["shirt", "shorts", "shoe", "sole", "hair"] as const;
const MAX_VERTICES = 400_000;
const MAX_TRIANGLES = 800_000;
const MAX_BONES = 64;

export class FigureError extends Error {
  constructor(reason: string) {
    super(`The anatomical figure was refused: ${reason}.`);
    this.name = "FigureError";
  }
}

export interface FigureBone {
  readonly name: string;
  /** World position and orientation (w, x, y, z) of the body frame in the bind pose. */
  readonly bindPosition: Vec3;
  readonly bindQuaternion: Quat;
}

export interface FigureSkeletonBody {
  readonly name: string;
  readonly parent: string;
  readonly position_m: Vec3;
  readonly quaternion: Quat;
}

export interface FigureAsset {
  readonly modelSha256: string;
  readonly claim: string;
  readonly generator: string;
  readonly bones: readonly FigureBone[];
  readonly skeleton: readonly FigureSkeletonBody[];
  readonly volumes: Readonly<Record<string, { figure: number; mass_over_density: number; calibrated: boolean }>>;
  readonly meshVolumeL: number;
  readonly vertexCount: number;
  readonly triangleCount: number;
  /** Bind-pose positions (m) and unit normals, 3 per vertex. */
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  /** Four bone indices and four weights (bytes summing to 255) per vertex. */
  readonly joints: Uint8Array;
  readonly weights: Float32Array;
  /** Garment fields (m), five per vertex: positive inside shirt, shorts, shoe, sole, hair. */
  readonly garment: Float32Array;
  readonly indices: Uint32Array;
}

type JsonObject = Record<string, unknown>;

function object(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as JsonObject) : null;
}

function numbers(value: unknown, length: number): number[] | null {
  if (!Array.isArray(value) || value.length !== length) return null;
  return value.every((item) => typeof item === "number" && Number.isFinite(item)) ? (value as number[]) : null;
}

function vec3(value: unknown): Vec3 | null {
  const v = numbers(value, 3);
  return v === null ? null : [v[0]!, v[1]!, v[2]!];
}

function quat(value: unknown): Quat | null {
  const q = numbers(value, 4);
  if (q === null) return null;
  const norm = Math.hypot(q[0]!, q[1]!, q[2]!, q[3]!);
  return Math.abs(norm - 1) > 1e-6 ? null : [q[0]!, q[1]!, q[2]!, q[3]!];
}

const IDENTIFIER = /^[A-Za-z0-9_.:-]{1,96}$/;

interface Section {
  readonly name: string;
  readonly dtype: string;
  readonly offset: number;
  readonly bytes: number;
}

/** Decode and check one figure stream. Throws `FigureError` for anything but the format. */
export function decodeFigure(payload: Uint8Array): FigureAsset {
  if (payload.byteLength < 12) throw new FigureError("it is too short");
  const magic = new TextDecoder().decode(payload.subarray(0, 8));
  if (magic !== FIGURE_MAGIC) throw new FigureError("it is not a figure stream");
  const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  const headerLength = view.getUint32(8, true);
  if (12 + headerLength > payload.byteLength || headerLength > 1_000_000) throw new FigureError("its header is truncated");
  let header: JsonObject | null;
  try {
    header = object(JSON.parse(new TextDecoder().decode(payload.subarray(12, 12 + headerLength))));
  } catch {
    throw new FigureError("its header is not JSON");
  }
  if (header === null || header.schema !== FIGURE_SCHEMA) throw new FigureError("its header is not the expected schema");

  const counts = object(header.counts);
  const vertexCount = counts?.vertices;
  const triangleCount = counts?.triangles;
  if (
    typeof vertexCount !== "number" ||
    typeof triangleCount !== "number" ||
    !Number.isInteger(vertexCount) ||
    !Number.isInteger(triangleCount) ||
    vertexCount < 4 ||
    triangleCount < 4 ||
    vertexCount > MAX_VERTICES ||
    triangleCount > MAX_TRIANGLES
  ) {
    throw new FigureError("its counts are not usable");
  }
  const modelSha256 = typeof header.model_sha256 === "string" && /^[0-9a-f]{64}$/.test(header.model_sha256) ? header.model_sha256 : null;
  const claim = typeof header.claim === "string" ? header.claim.slice(0, 2000) : null;
  const generator = typeof header.generator === "string" ? header.generator.slice(0, 200) : null;
  if (modelSha256 === null || claim === null || generator === null) throw new FigureError("its provenance is incomplete");

  const bones: FigureBone[] = [];
  if (!Array.isArray(header.bones) || header.bones.length === 0 || header.bones.length > MAX_BONES) throw new FigureError("it has no bones");
  for (const entry of header.bones) {
    const bone = object(entry);
    const name = bone?.name;
    const position = vec3(bone?.bind_position_m);
    const quaternion = quat(bone?.bind_quaternion);
    if (typeof name !== "string" || !IDENTIFIER.test(name) || position === null || quaternion === null) throw new FigureError("a bone is malformed");
    bones.push({ name, bindPosition: position, bindQuaternion: quaternion });
  }
  if (new Set(bones.map((bone) => bone.name)).size !== bones.length) throw new FigureError("a bone is named twice");

  const skeleton: FigureSkeletonBody[] = [];
  if (!Array.isArray(header.skeleton)) throw new FigureError("it names no skeleton");
  for (const entry of header.skeleton) {
    const body = object(entry);
    const position = vec3(body?.position_m);
    const quaternion = numbers(body?.quaternion, 4);
    if (typeof body?.name !== "string" || typeof body.parent !== "string" || position === null || quaternion === null) {
      throw new FigureError("its skeleton is malformed");
    }
    skeleton.push({ name: body.name, parent: body.parent, position_m: position, quaternion: [quaternion[0]!, quaternion[1]!, quaternion[2]!, quaternion[3]!] });
  }
  const volumes: Record<string, { figure: number; mass_over_density: number; calibrated: boolean }> = {};
  for (const [kind, entry] of Object.entries(object(header.volumes_l) ?? {})) {
    const record = object(entry);
    if (record !== null && typeof record.figure === "number" && typeof record.mass_over_density === "number") {
      volumes[kind] = { figure: record.figure, mass_over_density: record.mass_over_density, calibrated: record.calibrated === true };
    }
  }
  const meshVolumeL = typeof header.mesh_volume_l === "number" ? header.mesh_volume_l : Number.NaN;
  const garmentScale = header.garment_scale;
  if (typeof garmentScale !== "number" || !(garmentScale > 0)) throw new FigureError("its garment scale is missing");
  if (!Array.isArray(header.garments) || header.garments.join(",") !== FIGURE_GARMENTS.join(",")) throw new FigureError("its garments are not the expected ones");

  // Sections: aligned, inside the stream, with exactly the lengths the counts imply.
  const base = 12 + headerLength;
  if (base % 4 !== 0) throw new FigureError("its sections are not aligned");
  const expected: Record<string, { dtype: string; bytes: number }> = {
    position: { dtype: "float32", bytes: vertexCount * 12 },
    normal: { dtype: "float32", bytes: vertexCount * 12 },
    joints: { dtype: "uint8", bytes: vertexCount * 4 },
    weights: { dtype: "uint8", bytes: vertexCount * 4 },
    garment: { dtype: "int16", bytes: vertexCount * 10 },
    index: { dtype: "uint32", bytes: triangleCount * 12 },
  };
  const sections = new Map<string, Section>();
  if (!Array.isArray(header.sections)) throw new FigureError("it has no section table");
  for (const entry of header.sections) {
    const section = object(entry);
    const name = section?.name;
    const dtype = section?.dtype;
    const offset = section?.offset;
    const bytes = section?.bytes;
    if (typeof name !== "string" || typeof dtype !== "string" || typeof offset !== "number" || typeof bytes !== "number") {
      throw new FigureError("its section table is malformed");
    }
    const want = expected[name];
    if (want === undefined || want.dtype !== dtype || want.bytes !== bytes || offset % 4 !== 0 || base + offset + bytes > payload.byteLength) {
      throw new FigureError(`its ${name} section is not the declared array`);
    }
    sections.set(name, { name, dtype, offset, bytes });
  }
  if (sections.size !== Object.keys(expected).length) throw new FigureError("a section is missing");
  const slice = (name: string) => {
    const section = sections.get(name) as Section;
    // Copy into aligned storage: the payload's own buffer offset may not be 4-aligned.
    return payload.slice(base + section.offset, base + section.offset + section.bytes).buffer;
  };
  const positions = new Float32Array(slice("position"));
  const normals = new Float32Array(slice("normal"));
  const joints = new Uint8Array(slice("joints"));
  const weightBytes = new Uint8Array(slice("weights"));
  const garmentRaw = new Int16Array(slice("garment"));
  const indices = new Uint32Array(slice("index"));

  for (let i = 0; i < positions.length; i += 1) {
    if (!Number.isFinite(positions[i]!) || !Number.isFinite(normals[i]!)) throw new FigureError("a vertex is not finite");
  }
  for (let i = 0; i < indices.length; i += 1) {
    if (indices[i]! >= vertexCount) throw new FigureError("a triangle names a vertex that does not exist");
  }
  const weights = new Float32Array(vertexCount * 4);
  for (let v = 0; v < vertexCount; v += 1) {
    let sum = 0;
    for (let k = 0; k < 4; k += 1) {
      const j = joints[v * 4 + k]!;
      const w = weightBytes[v * 4 + k]!;
      if (w > 0 && j >= bones.length) throw new FigureError("a vertex is bound to a bone that does not exist");
      sum += w;
      weights[v * 4 + k] = w / 255;
    }
    if (sum !== 255) throw new FigureError("a vertex's weights do not sum to one");
  }
  const garment = new Float32Array(garmentRaw.length);
  for (let i = 0; i < garmentRaw.length; i += 1) {
    garment[i] = garmentRaw[i]! / garmentScale;
  }
  return {
    modelSha256,
    claim,
    generator,
    bones,
    skeleton,
    volumes,
    meshVolumeL,
    vertexCount,
    triangleCount,
    positions,
    normals,
    joints,
    weights,
    garment,
    indices,
  };
}

/**
 * Why a figure cannot be drawn for a model, or `null` when it can: its skeleton must be the
 * model's athlete bodies, with the same parents, positions and orientations (to 1 µm / 1e-9),
 * and every bone must be a body of that model.
 */
export function figureMismatch(figure: FigureAsset, model: LaboratoryModelResponse): string | null {
  const bodies = new Map(model.bodies.map((body) => [body.name, body]));
  for (const bone of figure.bones) {
    if (!bodies.has(bone.name)) return `the figure's bone ${bone.name} is not a body of this model`;
  }
  for (const body of figure.skeleton) {
    const other = bodies.get(body.name);
    if (other === undefined) return `the model has no body ${body.name}`;
    if (other.parent !== body.parent) return `the body ${body.name} hangs from another parent`;
    for (let i = 0; i < 3; i += 1) {
      if (Math.abs(other.position_m[i]! - body.position_m[i]!) > 1e-6) return `the body ${body.name} is elsewhere in this model`;
    }
    for (let i = 0; i < 4; i += 1) {
      if (Math.abs(other.quaternion[i]! - body.quaternion[i]!) > 1e-9) return `the body ${body.name} is oriented otherwise in this model`;
    }
  }
  const athletes = model.bodies.filter((body) => body.name !== "barbell").length;
  if (athletes !== figure.skeleton.length) return "the model's skeleton has other bodies";
  return null;
}
