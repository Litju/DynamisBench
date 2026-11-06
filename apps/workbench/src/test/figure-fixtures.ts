/**
 * Figure streams in the published format (`python/tools/mujoco_squat_figure.py`), small enough
 * to reason about: a tetrahedron on two bones by default, with any field replaceable so a test
 * can hand the decoder exactly the defect it is about.
 */

import { FIGURE_GARMENTS } from "../laboratory/figure/figure";
import type { LaboratoryModelResponse } from "../api/laboratory-types";

export interface StreamOptions {
  readonly bones?: { name: string; bind_position_m: number[]; bind_quaternion: number[] }[];
  readonly modelSha256?: string;
  readonly magic?: string;
  readonly index?: number[];
  readonly weights?: number[];
  readonly joints?: number[];
  readonly positions?: number[];
  readonly truncate?: number;
  readonly schema?: string;
  readonly skeleton?: unknown[];
}


/**
 * A small figure stream in the published format: two bones (a root at z = 1 and a child 0.5 m
 * below it), a tetrahedron around the child's origin, weights 255/0 except one shared vertex.
 */
export function figureStream(options: StreamOptions = {}): Uint8Array {
  const vertexCount = 4;
  const positions = options.positions ?? [0.1, 0, 0.5, -0.1, 0.1, 0.5, -0.1, -0.1, 0.5, 0, 0, 0.7];
  const normals = [1, 0, 0, -0.7071, 0.7071, 0, -0.7071, -0.7071, 0, 0, 0, 1];
  const joints = options.joints ?? [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0];
  const weights = options.weights ?? [255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 128, 127, 0, 0];
  const garment = new Array(vertexCount * 5).fill(-100);
  const index = options.index ?? [0, 1, 2, 0, 3, 1, 1, 3, 2, 2, 3, 0];
  const sections: [string, string, ArrayBufferView][] = [
    ["position", "float32", new Float32Array(positions)],
    ["normal", "float32", new Float32Array(normals)],
    ["joints", "uint8", new Uint8Array(joints)],
    ["weights", "uint8", new Uint8Array(weights)],
    ["garment", "int16", new Int16Array(garment)],
    ["index", "uint32", new Uint32Array(index)],
  ];
  let offset = 0;
  const layout = sections.map(([name, dtype, data]) => {
    const entry = { name, dtype, offset, bytes: data.byteLength };
    offset += data.byteLength + ((4 - (data.byteLength % 4)) % 4);
    return entry;
  });
  const header = {
    schema: options.schema ?? "dynamisbench.laboratory.figure/1",
    generator: "test",
    model_sha256: options.modelSha256 ?? "a".repeat(64),
    claim: "a test figure",
    skeleton: options.skeleton ?? [],
    bones: options.bones ?? [
      { name: "root", bind_position_m: [0, 0, 1], bind_quaternion: [1, 0, 0, 0] },
      { name: "child", bind_position_m: [0, 0, 0.5], bind_quaternion: [1, 0, 0, 0] },
    ],
    garments: [...FIGURE_GARMENTS],
    garment_scale: 10000,
    volumes_l: {},
    mesh_volume_l: 0.001,
    counts: { vertices: vertexCount, triangles: index.length / 3 },
    sections: layout,
  };
  let text = new TextEncoder().encode(JSON.stringify(header));
  const padded = new Uint8Array(text.length + ((4 - (text.length % 4)) % 4)).fill(32);
  padded.set(text);
  text = padded;
  const total = 12 + text.length + offset;
  const out = new Uint8Array(total);
  out.set(new TextEncoder().encode(options.magic ?? "DBFIGUR1"), 0);
  new DataView(out.buffer).setUint32(8, text.length, true);
  out.set(text, 12);
  sections.forEach(([, , data], i) => {
    out.set(new Uint8Array(data.buffer, data.byteOffset, data.byteLength), 12 + text.length + layout[i]!.offset);
  });
  return options.truncate === undefined ? out : out.slice(0, out.length - options.truncate);
}


/** A stream whose skeleton and bones are the given model's, so it is drawn for that model. */
export function figureStreamFor(model: LaboratoryModelResponse): Uint8Array {
  const athlete = model.bodies.filter((body) => body.name !== "barbell");
  return figureStream({
    modelSha256: model.model_sha256,
    skeleton: athlete.map((body) => ({ name: body.name, parent: body.parent, position_m: body.position_m, quaternion: body.quaternion })),
    bones: [
      { name: "pelvis", bind_position_m: [0, 0, 1], bind_quaternion: [1, 0, 0, 0] },
      { name: "shank_l", bind_position_m: [0, 0, 0.5], bind_quaternion: [1, 0, 0, 0] },
    ],
  });
}
