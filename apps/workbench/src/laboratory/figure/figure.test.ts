/**
 * The anatomical figure: the stream is accepted only as the format, a figure is drawn only for
 * the model it was derived from, and dual-quaternion skinning carries the bind surface to the
 * recorded poses exactly (rigidly where one bone rules, without collapse where two blend).
 */

import { describe, expect, it } from "vitest";

import { decodeLaboratoryModelResponse } from "../../api/laboratory-decode";
import type { LaboratoryModelResponse } from "../../api/laboratory-types";
import { LABORATORY_MODEL } from "../../test/laboratory-fixtures";
import { figureStream as stream } from "../../test/figure-fixtures";
import { FigureError, decodeFigure, figureMismatch, type FigureAsset } from "./figure";
import { boneDualQuaternions, boneInfluence, dominantBone, skinFigure, type BonePose } from "./skinning";

function refusal(payload: Uint8Array): string {
  try {
    decodeFigure(payload);
  } catch (error) {
    if (error instanceof FigureError) return error.message;
    throw error;
  }
  return "accepted";
}

describe("decodeFigure", () => {
  it("accepts the format: bones, arrays, weights as fractions, garments in metres", () => {
    const figure = decodeFigure(stream());
    expect(figure.vertexCount).toBe(4);
    expect(figure.triangleCount).toBe(4);
    expect(figure.bones.map((bone) => bone.name)).toEqual(["root", "child"]);
    expect(figure.weights[12]).toBeCloseTo(128 / 255, 6);
    expect(figure.garment[0]).toBeCloseTo(-0.01, 6);
  });

  it("refuses anything but the format", () => {
    expect(refusal(stream({ magic: "NOTAFIG!" }))).toMatch(/not a figure stream/);
    expect(refusal(stream({ schema: "other/1" }))).toMatch(/schema/);
    expect(refusal(stream({ truncate: 8 }))).toMatch(/section is not the declared array/);
    expect(refusal(stream({ index: [0, 1, 2, 0, 3, 1, 1, 3, 2, 2, 3, 9] }))).toMatch(/does not exist/);
    expect(refusal(stream({ weights: [255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 128, 126, 0, 0] }))).toMatch(/sum to one/);
    expect(refusal(stream({ joints: [5, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0] }))).toMatch(/bone that does not exist/);
    expect(refusal(stream({ positions: [Number.NaN, 0, 0.5, -0.1, 0.1, 0.5, -0.1, -0.1, 0.5, 0, 0, 0.7] }))).toMatch(/not finite/);
    expect(refusal(new Uint8Array(5))).toMatch(/too short/);
  });
});

describe("figureMismatch", () => {
  const model = decodeLaboratoryModelResponse(structuredClone(LABORATORY_MODEL)) as LaboratoryModelResponse;
  const skeleton = model.bodies
    .filter((body) => body.name !== "barbell")
    .map((body) => ({ name: body.name, parent: body.parent, position_m: [...body.position_m], quaternion: [...body.quaternion] }) as { name: string; parent: string; position_m: number[]; quaternion: number[] });

  it("draws a figure only for the model whose skeleton it carries", () => {
    const figure = { ...decodeFigure(stream({ skeleton })), bones: [{ name: "pelvis", bindPosition: [0, 0, 1], bindQuaternion: [1, 0, 0, 0] }] } as unknown as FigureAsset;
    expect(figureMismatch(figure, model)).toBeNull();

    const moved = structuredClone(skeleton);
    moved[10]!.position_m[2] = moved[10]!.position_m[2]! - 0.01;
    expect(figureMismatch({ ...figure, skeleton: moved } as unknown as FigureAsset, model)).toMatch(/elsewhere/);
    const reparented = structuredClone(skeleton);
    reparented[5]!.parent = "pelvis";
    expect(figureMismatch({ ...figure, skeleton: reparented } as unknown as FigureAsset, model)).toMatch(/another parent/);
    expect(figureMismatch({ ...figure, bones: [{ name: "tail", bindPosition: [0, 0, 0], bindQuaternion: [1, 0, 0, 0] }] } as unknown as FigureAsset, model)).toMatch(/not a body/);
  });
});

function skinned(figure: FigureAsset, poses: BonePose[]) {
  const positions = new Float32Array(figure.vertexCount * 3);
  const normals = new Float32Array(figure.vertexCount * 3);
  skinFigure(figure, boneDualQuaternions(figure, poses), positions, normals);
  return { positions, normals };
}

const ROOT: BonePose = { position: [0, 0, 1], quaternion: [1, 0, 0, 0] };

describe("dual-quaternion skinning", () => {
  const figure = decodeFigure(stream());

  it("leaves the bind surface where it is in the bind pose", () => {
    const { positions, normals } = skinned(figure, [ROOT, { position: [0, 0, 0.5], quaternion: [1, 0, 0, 0] }]);
    for (let i = 0; i < positions.length; i += 1) {
      expect(positions[i]).toBeCloseTo(figure.positions[i]!, 6);
      expect(normals[i]).toBeCloseTo(figure.normals[i]!, 6);
    }
  });

  it("moves a surface ruled by one bone rigidly with it", () => {
    // The child turns 90° about +y at its origin, and the whole figure moves 1 m along +x.
    const half = Math.SQRT1_2;
    const { positions } = skinned(figure, [
      { position: [1, 0, 1], quaternion: [1, 0, 0, 0] },
      { position: [1, 0, 0.5], quaternion: [half, 0, half, 0] },
    ]);
    // Vertex 0 is (0.1, 0, 0.5): 0.1 m along the child's x, which the turn takes to −z.
    expect(positions[0]).toBeCloseTo(1.0, 6);
    expect(positions[1]).toBeCloseTo(0.0, 6);
    expect(positions[2]).toBeCloseTo(0.4, 6);
  });

  it("blends two bones without collapsing the surface towards the joint", () => {
    // Vertex 3 is (0, 0, 0.7), half on each bone. Turning the child 90° about the x axis through
    // its origin takes the child's copy of it to (0, −0.2, 0.5); the blend keeps it 0.2 m from
    // the joint (linear blending would pull it to 0.14 m).
    const half = Math.SQRT1_2;
    const { positions } = skinned(figure, [ROOT, { position: [0, 0, 0.5], quaternion: [half, half, 0, 0] }]);
    const dy = positions[10]! - 0;
    const dz = positions[11]! - 0.5;
    expect(Math.hypot(dy, dz)).toBeCloseTo(0.2, 2);
  });

  it("finds a vertex's segment and a bone's influence", () => {
    expect(figure.bones[dominantBone(figure, 0)]?.name).toBe("child");
    const influence = new Float32Array(figure.vertexCount);
    boneInfluence(figure, 1, influence);
    expect([...influence].map((value) => Number(value.toFixed(3)))).toEqual([1, 1, 1, 0.498]);
  });
});
