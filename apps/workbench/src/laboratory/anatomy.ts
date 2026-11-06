/**
 * Names for what the model publishes: joints, bodies and their anatomical marginalia.
 *
 * Presentation vocabulary only. Joint and body identifiers are the model's own (`knee_flexion_l`,
 * `shank_l`); this module turns them into the labels a reader expects and never invents a joint
 * or a body the model did not publish.
 */

import type { LaboratoryBody, LaboratoryJoint, LaboratoryModelResponse } from "../api/laboratory-types";

/** Latin adjectives agree with their noun: coxa sinistra, genu sinistrum, talus sinister. */
type Gender = "f" | "n" | "m";
const SIDE_LATIN: Record<Gender, { left: string; right: string }> = {
  f: { left: "sinistra", right: "dextra" },
  n: { left: "sinistrum", right: "dextrum" },
  m: { left: "sinister", right: "dexter" },
};

const REGIONS: Record<string, { english: string; latin: string; gender: Gender }> = {
  hip: { english: "Hip", latin: "coxa", gender: "f" },
  knee: { english: "Knee", latin: "genu", gender: "n" },
  ankle: { english: "Ankle", latin: "talus", gender: "m" },
  subtalar: { english: "Subtalar", latin: "articulatio subtalaris", gender: "f" },
  lumbar: { english: "Lumbar spine", latin: "lumbus", gender: "m" },
  thoracic: { english: "Thoracic spine", latin: "thorax", gender: "m" },
  neck: { english: "Neck", latin: "cervix", gender: "f" },
  shoulder: { english: "Shoulder", latin: "humerus", gender: "m" },
  elbow: { english: "Elbow", latin: "cubitus", gender: "m" },
};

const BODY_LABELS: Record<string, string> = {
  pelvis: "Pelvis",
  torso_middle: "Torso — middle",
  torso_upper: "Torso — upper",
  head: "Head",
  upper_arm: "Upper arm",
  forearm: "Forearm",
  hand: "Hand",
  thigh: "Thigh",
  shank: "Shank",
  foot: "Foot",
  barbell: "Barbell",
};

export type Side = "left" | "right" | null;

export interface JointName {
  readonly region: string;
  readonly movement: string;
  readonly side: Side;
  /** "Knee · left" */
  readonly title: string;
  /** "knee flexion · L" */
  readonly short: string;
  /** "genu sinistrum" */
  readonly latin: string;
}

function sideOf(name: string): { stem: string; side: Side } {
  if (name.endsWith("_l")) {
    return { stem: name.slice(0, -2), side: "left" };
  }
  if (name.endsWith("_r")) {
    return { stem: name.slice(0, -2), side: "right" };
  }
  return { stem: name, side: null };
}

/** Reader-facing names of one model joint. */
export function jointName(name: string): JointName {
  const { stem, side } = sideOf(name);
  const [regionKey = stem, ...rest] = stem.split("_");
  const region = REGIONS[regionKey] ?? { english: regionKey, latin: regionKey, gender: "n" };
  const movement = rest.join(" ") || "rotation";
  const primary = movement === "flexion" || movement === "dorsiflexion";
  const latinSide = side === null ? "" : ` ${SIDE_LATIN[region.gender][side]}`;
  let title: string;
  if (side === null) {
    title = `${region.english} · ${movement}`;
  } else if (primary) {
    title = `${region.english} · ${side}`;
  } else {
    title = `${region.english} ${movement} · ${side}`;
  }
  return {
    region: region.english,
    movement,
    side,
    title,
    short: `${regionKey} ${movement}${side === null ? "" : ` · ${side === "left" ? "L" : "R"}`}`,
    latin: `${region.latin}${latinSide}`,
  };
}

/** Reader-facing name of one model body ("Shank · L"). */
export function bodyLabel(name: string): string {
  const { stem, side } = sideOf(name);
  const base = BODY_LABELS[stem] ?? stem.replaceAll("_", " ");
  return side === null ? base : `${base} ${side === "left" ? "L" : "R"}`;
}

/** The axis as a reader names it: "+y", "−x", or the vector. */
export function axisLabel(axis: readonly [number, number, number]): string {
  const names = ["x", "y", "z"];
  for (let i = 0; i < 3; i += 1) {
    const value = axis[i] ?? 0;
    if (Math.abs(Math.abs(value) - 1) < 1e-9) {
      return `${value > 0 ? "+" : "−"}${names[i]}`;
    }
  }
  return `(${axis.map((v) => v.toFixed(2)).join(", ")})`;
}

export interface BodyNode {
  readonly body: LaboratoryBody;
  readonly depth: number;
  readonly joints: readonly LaboratoryJoint[];
}

/** Bodies in depth-first order from the root, each with the joints that move it. */
export function bodyTree(model: LaboratoryModelResponse): BodyNode[] {
  const children = new Map<string, LaboratoryBody[]>();
  for (const body of model.bodies) {
    const siblings = children.get(body.parent) ?? [];
    siblings.push(body);
    children.set(body.parent, siblings);
  }
  const nodes: BodyNode[] = [];
  const visit = (parent: string, depth: number) => {
    for (const body of children.get(parent) ?? []) {
      nodes.push({
        body,
        depth,
        joints: model.joints.filter((joint) => joint.body === body.name),
      });
      visit(body.name, depth + 1);
    }
  };
  visit("world", 0);
  return nodes;
}

/** The sagittal chain of a joint's side, for the stage's marginalia: hip, knee, ankle. */
export function marginaliaFor(selected: string | null): string[] {
  const side = selected !== null && selected.endsWith("_r") ? "r" : "l";
  const chain = [`hip_flexion_${side}`, `knee_flexion_${side}`, `ankle_dorsiflexion_${side}`];
  if (selected !== null && !chain.includes(selected)) {
    return [selected, ...chain.slice(0, 2)];
  }
  return chain;
}
