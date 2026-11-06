/**
 * The laboratory stage: the compiled model drawn with three.js and posed from recorded frames.
 *
 * Every drawn thing is published data. Segment geometry is the compiled model's geoms in their
 * body frames (`/laboratory/model`); each body is placed, per frame, at its recorded world
 * position and orientation (`pose` frames). Ground-reaction vectors start at each foot's
 * published centre of pressure and are the published per-foot forces; plantar discs sit at the
 * published contact positions and are sized by the published normal loads; the centre of mass,
 * bar path and CoM path are the published trajectories. Nothing is simulated, interpolated or
 * re-derived here: the stage draws frame *n* as it was recorded.
 */

import * as THREE from "three";

import type {
  LaboratoryFrameTable,
  LaboratoryGeom,
  LaboratoryJoint,
  LaboratoryModelResponse,
} from "../../api/laboratory-types";
import type { FigureAsset } from "../figure/figure";
import { boneDualQuaternions, boneInfluence, dominantBone, skinFigure, type BonePose } from "../figure/skinning";
import type { Palette } from "../palette";
import { at, column, convexHull, type Point2 } from "../series";
import type { Layer } from "../store";
import { orbitPosition, type Orbit } from "./camera";

/** Ground-reaction vectors are drawn at this many metres per kilonewton. */
export const GRF_METRES_PER_KN = 0.62;
/** Floor-instrument ring radii, metres. */
export const FLOOR_RINGS_M = [0.25, 0.5, 0.75, 1.0] as const;
export const FIELD_OF_VIEW_DEG = 30;

export interface StageFrames {
  readonly pose: LaboratoryFrameTable;
  readonly kinematics: LaboratoryFrameTable;
  readonly kinetics: LaboratoryFrameTable;
}

export interface ScreenPoint {
  readonly x: number;
  readonly y: number;
  readonly visible: boolean;
}

const SIDES = ["l", "r"] as const;

/** How the athlete is drawn: the anatomical figure, or the model's own segment geometry. */
export type FigureMode = "anatomical" | "scientific";

/**
 * The figure's material: a standard PBR surface whose colour and roughness come from the
 * garment fields (straight hems at their zero crossings, antialiased with screen derivatives),
 * with the selected segment's skin weight as a gold glow.
 */
function figureMaterial(): THREE.MeshStandardMaterial & { userData: { uniforms?: Record<string, THREE.IUniform> } } {
  const material = new THREE.MeshStandardMaterial({ roughness: 0.62, metalness: 0.0 });
  const uniforms: Record<string, THREE.IUniform> = {
    skinColor: { value: new THREE.Color() },
    shirtColor: { value: new THREE.Color() },
    shortsColor: { value: new THREE.Color() },
    shoeColor: { value: new THREE.Color() },
    outsoleColor: { value: new THREE.Color() },
    hairColor: { value: new THREE.Color() },
    selectionColor: { value: new THREE.Color() },
  };
  material.userData.uniforms = uniforms;
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        `#include <common>
attribute vec4 garmentA;
attribute float garmentB;
attribute float selection;
varying vec4 vGarmentA;
varying float vGarmentB;
varying float vSelection;`,
      )
      .replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
vGarmentA = garmentA;
vGarmentB = garmentB;
vSelection = selection;`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
uniform vec3 skinColor;
uniform vec3 shirtColor;
uniform vec3 shortsColor;
uniform vec3 shoeColor;
uniform vec3 outsoleColor;
uniform vec3 hairColor;
uniform vec3 selectionColor;
varying vec4 vGarmentA;
varying float vGarmentB;
varying float vSelection;
float garmentEdge(float v) { float w = max(fwidth(v) * 0.8, 1e-5); return smoothstep(-w, w, v); }`,
      )
      .replace(
        "vec4 diffuseColor = vec4( diffuse, opacity );",
        `float inShorts = garmentEdge(vGarmentA.y);
float inShirt = garmentEdge(vGarmentA.x);
float inShoe = garmentEdge(vGarmentA.z);
float inSole = garmentEdge(vGarmentB);
float inHair = garmentEdge(vGarmentA.w);
vec3 surface = skinColor;
surface = mix(surface, shortsColor, inShorts);
surface = mix(surface, shirtColor, inShirt);
surface = mix(surface, shoeColor, inShoe);
surface = mix(surface, outsoleColor, inSole);
surface = mix(surface, hairColor, inHair);
float fabric = max(max(inShirt, inShorts), max(inShoe, inHair));
vec4 diffuseColor = vec4( surface, opacity );`,
      )
      .replace(
        "#include <roughnessmap_fragment>",
        `#include <roughnessmap_fragment>
roughnessFactor = mix(0.56, 0.86, fabric);`,
      )
      .replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>
totalEmissiveRadiance += selectionColor * (0.38 * vSelection);`,
      );
  };
  return material;
}

/** The anatomical figure as a mesh the stage deforms each frame (CPU dual-quaternion skinning). */
class FigureLayer {
  readonly mesh: THREE.Mesh;
  private readonly positions: Float32Array;
  private readonly normals: Float32Array;
  private readonly selection: Float32Array;
  private readonly poseColumns: (readonly [string, string, string, string, string, string, string])[];

  constructor(
    readonly figure: FigureAsset,
    readonly material: ReturnType<typeof figureMaterial>,
  ) {
    const geometry = new THREE.BufferGeometry();
    this.positions = figure.positions.slice();
    this.normals = figure.normals.slice();
    this.selection = new Float32Array(figure.vertexCount);
    const garmentA = new Float32Array(figure.vertexCount * 4);
    const garmentB = new Float32Array(figure.vertexCount);
    for (let v = 0; v < figure.vertexCount; v += 1) {
      garmentA[v * 4] = figure.garment[v * 5]!;
      garmentA[v * 4 + 1] = figure.garment[v * 5 + 1]!;
      garmentA[v * 4 + 2] = figure.garment[v * 5 + 2]!;
      garmentA[v * 4 + 3] = figure.garment[v * 5 + 4]!;
      garmentB[v] = figure.garment[v * 5 + 3]!;
    }
    geometry.setAttribute("position", new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute("normal", new THREE.BufferAttribute(this.normals, 3).setUsage(THREE.DynamicDrawUsage));
    geometry.setAttribute("garmentA", new THREE.BufferAttribute(garmentA, 4));
    geometry.setAttribute("garmentB", new THREE.BufferAttribute(garmentB, 1));
    geometry.setAttribute("selection", new THREE.BufferAttribute(this.selection, 1).setUsage(THREE.DynamicDrawUsage));
    geometry.setIndex(new THREE.BufferAttribute(figure.indices, 1));
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.castShadow = true;
    this.mesh.receiveShadow = true;
    // The skinned surface moves every frame; its bounds are computed where they are needed.
    this.mesh.frustumCulled = false;
    this.mesh.userData.role = "figure";
    this.poseColumns = figure.bones.map((bone) => [
      `${bone.name}.px`,
      `${bone.name}.py`,
      `${bone.name}.pz`,
      `${bone.name}.qw`,
      `${bone.name}.qx`,
      `${bone.name}.qy`,
      `${bone.name}.qz`,
    ]);
  }

  /** Whether every bone has a recorded pose in this table. */
  covers(pose: LaboratoryFrameTable): boolean {
    return this.poseColumns.every((names) => names.every((name) => pose.columns.has(name)));
  }

  pose(pose: LaboratoryFrameTable, frame: number): void {
    const poses: BonePose[] = this.poseColumns.map(([px, py, pz, qw, qx, qy, qz]) => ({
      position: [at(column(pose, px), frame), at(column(pose, py), frame), at(column(pose, pz), frame)],
      quaternion: [at(column(pose, qw), frame), at(column(pose, qx), frame), at(column(pose, qy), frame), at(column(pose, qz), frame)],
    }));
    skinFigure(this.figure, boneDualQuaternions(this.figure, poses), this.positions, this.normals);
    const geometry = this.mesh.geometry;
    (geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    (geometry.getAttribute("normal") as THREE.BufferAttribute).needsUpdate = true;
    geometry.boundingSphere = null;
    geometry.boundingBox = null;
  }

  select(body: string | null): void {
    const bone = body === null ? -1 : this.figure.bones.findIndex((entry) => entry.name === body);
    if (bone < 0) {
      this.selection.fill(0);
    } else {
      boneInfluence(this.figure, bone, this.selection);
    }
    (this.mesh.geometry.getAttribute("selection") as THREE.BufferAttribute).needsUpdate = true;
  }

  pick(raycaster: THREE.Raycaster): string | null {
    const geometry = this.mesh.geometry;
    geometry.computeBoundingSphere();
    const [hit] = raycaster.intersectObject(this.mesh, false);
    if (hit === undefined || hit.face === undefined || hit.face === null) {
      return null;
    }
    // The face's corner nearest the hit decides the segment.
    const { a, b, c } = hit.face;
    const corners = [a, b, c];
    let nearest = a;
    let best = Number.POSITIVE_INFINITY;
    for (const corner of corners) {
      const dx = this.positions[corner * 3]! - hit.point.x;
      const dy = this.positions[corner * 3 + 1]! - hit.point.y;
      const dz = this.positions[corner * 3 + 2]! - hit.point.z;
      const distance = dx * dx + dy * dy + dz * dz;
      if (distance < best) {
        best = distance;
        nearest = corner;
      }
    }
    return this.figure.bones[dominantBone(this.figure, nearest)]?.name ?? null;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
  }
}

function quaternionOf(q: readonly number[]): THREE.Quaternion {
  // MuJoCo stores (w, x, y, z); three.js takes (x, y, z, w).
  return new THREE.Quaternion(q[1] ?? 0, q[2] ?? 0, q[3] ?? 0, q[0] ?? 1).normalize();
}

function geometryOf(geom: LaboratoryGeom): THREE.BufferGeometry | null {
  const [a, b, c] = geom.size_m;
  switch (geom.type) {
    case "sphere":
      return new THREE.SphereGeometry(a, 20, 14);
    case "ellipsoid": {
      const sphere = new THREE.SphereGeometry(1, 40, 28);
      sphere.scale(a, b, c);
      return sphere;
    }
    case "capsule": {
      // MuJoCo capsules lie along the local z axis; three.js builds them along y.
      const capsule = new THREE.CapsuleGeometry(a, 2 * b, 10, 28);
      capsule.rotateX(Math.PI / 2);
      return capsule;
    }
    case "cylinder": {
      const cylinder = new THREE.CylinderGeometry(a, a, 2 * b, 32, 1);
      cylinder.rotateX(Math.PI / 2);
      return cylinder;
    }
    case "box":
      return new THREE.BoxGeometry(2 * a, 2 * b, 2 * c);
    default:
      return null;
  }
}

/** A thick arrow along +z of unit length, scaled per frame. */
class Arrow {
  readonly group = new THREE.Group();
  private readonly shaft: THREE.Mesh;
  private readonly head: THREE.Mesh;

  constructor(material: THREE.Material) {
    this.shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.0075, 0.0075, 1, 12), material);
    this.shaft.geometry.rotateX(Math.PI / 2);
    this.shaft.geometry.translate(0, 0, 0.5);
    this.head = new THREE.Mesh(new THREE.ConeGeometry(0.022, 0.065, 18), material);
    this.head.geometry.rotateX(Math.PI / 2);
    this.head.geometry.translate(0, 0, -0.0325);
    this.group.add(this.shaft, this.head);
  }

  set(origin: THREE.Vector3, vector: THREE.Vector3): void {
    const length = vector.length();
    if (!(length > 1e-6)) {
      this.group.visible = false;
      return;
    }
    this.group.visible = true;
    this.group.position.copy(origin);
    this.group.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 0, 1),
      vector.clone().divideScalar(length),
    );
    const shaft = Math.max(0.001, length - 0.06);
    this.shaft.scale.set(1, 1, shaft);
    this.head.position.set(0, 0, length);
  }
}

export class LaboratoryScene {
  readonly renderer: THREE.WebGLRenderer;
  readonly camera: THREE.PerspectiveCamera;
  private readonly scene = new THREE.Scene();
  private readonly bodies = new Map<string, THREE.Group>();
  private readonly bodyMeshes = new Map<string, THREE.Mesh[]>();
  private readonly layerGroups = new Map<Layer, THREE.Object3D>();
  private readonly materials: {
    bone: THREE.MeshStandardMaterial;
    boneSelected: THREE.MeshStandardMaterial;
    steel: THREE.MeshStandardMaterial;
    sole: THREE.MeshStandardMaterial;
    shadow: THREE.ShadowMaterial;
    sanguine: THREE.MeshStandardMaterial;
    gold: THREE.MeshStandardMaterial;
    lapisLine: THREE.LineBasicMaterial;
    ring: THREE.LineBasicMaterial;
    ringStrong: THREE.LineBasicMaterial;
    plumb: THREE.LineDashedMaterial;
    support: THREE.MeshBasicMaterial;
    supportLine: THREE.LineBasicMaterial;
    plantar: THREE.MeshBasicMaterial;
    barPast: THREE.LineBasicMaterial;
    barFuture: THREE.LineDashedMaterial;
    comPath: THREE.LineDashedMaterial;
    selectedRing: THREE.MeshBasicMaterial;
  };
  private readonly grf = new Map<string, Arrow>();
  private readonly com: THREE.Mesh;
  private readonly plumb: THREE.Line;
  private readonly comFoot: THREE.Mesh;
  private readonly supportFill: THREE.Mesh;
  private readonly supportOutline: THREE.LineLoop;
  private readonly plantarDiscs: THREE.Mesh[] = [];
  private readonly floorInstrument = new THREE.Group();
  private readonly jointAxes = new THREE.Group();
  private readonly selectedRing: THREE.Mesh;
  private barPast: THREE.Line | null = null;
  private barFuture: THREE.Line | null = null;
  private comPathLine: THREE.Line | null = null;
  private readonly hemisphere: THREE.HemisphereLight;
  private frames: StageFrames | null = null;
  private readonly contactNames: string[];
  private selectedBody: string | null = null;
  private selectedJoint: LaboratoryJoint | null = null;
  private orbit: Orbit | null = null;
  private frameIndex = 0;
  private loadedThreshold: number;
  private readonly athlete: THREE.Group;
  private readonly figureMaterial = figureMaterial();
  private figureLayer: FigureLayer | null = null;
  private figureMode: FigureMode = "scientific";

  constructor(
    canvas: HTMLCanvasElement,
    private readonly model: LaboratoryModelResponse,
    palette: Palette,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.camera = new THREE.PerspectiveCamera(FIELD_OF_VIEW_DEG, 1, 0.05, 60);
    this.camera.up.set(0, 0, 1);
    this.loadedThreshold = model.contact.loaded_threshold_n;
    this.contactNames = SIDES.flatMap((side) =>
      model.sole_points.map((point) => `${side}_${point}`),
    );

    this.materials = {
      bone: new THREE.MeshStandardMaterial({ roughness: 0.78, metalness: 0.0 }),
      boneSelected: new THREE.MeshStandardMaterial({ roughness: 0.6, metalness: 0.05 }),
      steel: new THREE.MeshStandardMaterial({ roughness: 0.42, metalness: 0.12 }),
      sole: new THREE.MeshStandardMaterial({ roughness: 0.9 }),
      shadow: new THREE.ShadowMaterial({ opacity: 0.28 }),
      sanguine: new THREE.MeshStandardMaterial({ roughness: 0.5 }),
      gold: new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.3 }),
      lapisLine: new THREE.LineBasicMaterial(),
      ring: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.55 }),
      ringStrong: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.9 }),
      plumb: new THREE.LineDashedMaterial({ dashSize: 0.03, gapSize: 0.02 }),
      support: new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0.22,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
      supportLine: new THREE.LineBasicMaterial(),
      plantar: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.88, depthWrite: false }),
      barPast: new THREE.LineBasicMaterial(),
      barFuture: new THREE.LineDashedMaterial({ dashSize: 0.025, gapSize: 0.02, transparent: true, opacity: 0.6 }),
      comPath: new THREE.LineDashedMaterial({ dashSize: 0.02, gapSize: 0.015 }),
      selectedRing: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.9 }),
    };

    // Light: a warm hemisphere, a key light that casts the floor shadow, and a cool fill.
    this.hemisphere = new THREE.HemisphereLight(0xfff4e0, 0x3a3024, 1.25);
    this.hemisphere.position.set(0, 0, 1);
    const key = new THREE.DirectionalLight(0xfff1dc, 2.1);
    key.position.set(2.2, -2.6, 4.2);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -1.4;
    key.shadow.camera.right = 1.4;
    key.shadow.camera.top = 1.4;
    key.shadow.camera.bottom = -1.4;
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 10;
    key.shadow.bias = -0.0005;
    key.shadow.radius = 4;
    const fill = new THREE.DirectionalLight(0xdfe6ff, 0.55);
    fill.position.set(-3, 2.5, 2);
    this.scene.add(this.hemisphere, key, key.target, fill);

    // The floor receives the shadow only; the instrument is drawn on it.
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(8, 8), this.materials.shadow);
    floor.receiveShadow = true;
    floor.position.z = -0.0005;
    this.scene.add(floor);

    // Bodies and their geoms, in the bodies' own frames.
    const athlete = new THREE.Group();
    this.athlete = athlete;
    for (const body of model.bodies) {
      const group = new THREE.Group();
      group.name = body.name;
      group.matrixAutoUpdate = true;
      this.bodies.set(body.name, group);
      athlete.add(group);
    }
    for (const geom of model.geoms) {
      if (geom.role === "floor" || geom.body === "world") {
        continue;
      }
      const geometry = geometryOf(geom);
      const group = this.bodies.get(geom.body);
      if (geometry === null || group === undefined) {
        continue;
      }
      const material =
        geom.role === "barbell"
          ? this.materials.steel
          : geom.role === "sole"
            ? this.materials.sole
            : this.materials.bone;
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(...geom.position_m);
      mesh.quaternion.copy(quaternionOf(geom.quaternion));
      mesh.castShadow = geom.role !== "sole";
      mesh.userData.body = geom.body;
      mesh.userData.role = geom.role;
      group.add(mesh);
      const meshes = this.bodyMeshes.get(geom.body) ?? [];
      meshes.push(mesh);
      this.bodyMeshes.set(geom.body, meshes);
    }
    this.scene.add(athlete);
    this.layerGroups.set("athlete", athlete);

    // Joint axes: a short segment along each hinge axis at its anchor, in the child body frame.
    for (const joint of model.joints) {
      const group = this.bodies.get(joint.body);
      if (group === undefined) {
        continue;
      }
      const [px, py, pz] = joint.position_m;
      const [ax, ay, az] = joint.axis;
      const geometry = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(px - ax * 0.07, py - ay * 0.07, pz - az * 0.07),
        new THREE.Vector3(px + ax * 0.07, py + ay * 0.07, pz + az * 0.07),
      ]);
      const line = new THREE.Line(geometry, this.materials.lapisLine);
      line.userData.body = joint.body;
      this.jointAxes.add(line);
    }
    this.scene.add(this.jointAxes);
    this.layerGroups.set("jointAxes", this.jointAxes);

    // The selected joint's ring: a torus about its hinge axis, attached to its body each frame.
    this.selectedRing = new THREE.Mesh(
      new THREE.TorusGeometry(0.075, 0.0035, 8, 48),
      this.materials.selectedRing,
    );
    this.selectedRing.visible = false;
    this.scene.add(this.selectedRing);

    // Ground reaction: one arrow per foot, from that foot's centre of pressure.
    const grfGroup = new THREE.Group();
    for (const side of SIDES) {
      const arrow = new Arrow(this.materials.sanguine);
      this.grf.set(side, arrow);
      grfGroup.add(arrow.group);
    }
    this.scene.add(grfGroup);
    this.layerGroups.set("grf", grfGroup);

    // Centre of mass, its plumb line and its foot on the floor.
    const comGroup = new THREE.Group();
    this.com = new THREE.Mesh(new THREE.SphereGeometry(0.028, 24, 16), this.materials.gold);
    this.plumb = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      this.materials.plumb,
    );
    this.comFoot = new THREE.Mesh(
      new THREE.RingGeometry(0.018, 0.026, 32),
      this.materials.selectedRing,
    );
    comGroup.add(this.com, this.plumb, this.comFoot);
    this.scene.add(comGroup);
    this.layerGroups.set("com", comGroup);

    // The loaded support polygon (fill and outline), rebuilt per frame from ≤ 10 points.
    const supportGroup = new THREE.Group();
    this.supportFill = new THREE.Mesh(new THREE.BufferGeometry(), this.materials.support);
    this.supportOutline = new THREE.LineLoop(new THREE.BufferGeometry(), this.materials.supportLine);
    this.supportFill.position.z = 0.0015;
    this.supportOutline.position.z = 0.002;
    supportGroup.add(this.supportFill, this.supportOutline);
    this.scene.add(supportGroup);
    this.layerGroups.set("support", supportGroup);

    // Plantar load discs, one per sole contact point.
    const plantarGroup = new THREE.Group();
    for (let i = 0; i < this.contactNames.length; i += 1) {
      const disc = new THREE.Mesh(new THREE.CircleGeometry(1, 32), this.materials.plantar);
      disc.position.z = 0.003;
      this.plantarDiscs.push(disc);
      plantarGroup.add(disc);
    }
    this.scene.add(plantarGroup);
    this.layerGroups.set("plantar", plantarGroup);

    this.scene.add(this.floorInstrument);
    this.layerGroups.set("floor", this.floorInstrument);

    this.setPalette(palette);
  }

  /** Re-colour every material for a ground (Studiolo or Vellum). */
  setPalette(palette: Palette): void {
    const m = this.materials;
    this.scene.background = new THREE.Color(palette.stage);
    m.bone.color.set(palette.bone);
    m.boneSelected.color.set(palette.bone);
    m.boneSelected.emissive.set(palette.gold);
    m.boneSelected.emissiveIntensity = 0.42;
    m.steel.color.set(palette.steel);
    m.sole.color.set(palette.sole);
    m.sanguine.color.set(palette.sanguine);
    m.sanguine.emissive.set(palette.sanguine);
    m.sanguine.emissiveIntensity = 0.25;
    m.gold.color.set(palette.gold);
    m.gold.emissive.set(palette.gold);
    m.gold.emissiveIntensity = 0.2;
    m.lapisLine.color.set(palette.lapis);
    m.ring.color.set(palette.line2);
    m.ringStrong.color.set(palette.gold);
    m.plumb.color.set(palette.gold);
    m.support.color.set(palette.verdigris);
    m.supportLine.color.set(palette.verdigris);
    m.plantar.color.set(palette.verdigris);
    m.barPast.color.set(palette.gold);
    m.barFuture.color.set(palette.gold);
    m.comPath.color.set(palette.ochre);
    m.selectedRing.color.set(palette.gold);
    m.shadow.opacity = palette.shadowOpacity;
    this.hemisphere.groundColor.set(palette.boneShade);
    const figure = this.figureMaterial.userData.uniforms;
    if (figure !== undefined) {
      (figure.skinColor!.value as THREE.Color).set(palette.figure.skin);
      (figure.shirtColor!.value as THREE.Color).set(palette.figure.shirt);
      (figure.shortsColor!.value as THREE.Color).set(palette.figure.shorts);
      (figure.shoeColor!.value as THREE.Color).set(palette.figure.shoe);
      (figure.outsoleColor!.value as THREE.Color).set(palette.figure.outsole);
      (figure.hairColor!.value as THREE.Color).set(palette.figure.hair);
      (figure.selectionColor!.value as THREE.Color).set(palette.gold);
    }
  }

  /**
   * Attach the anatomical figure (or none). The figure is drawn only when it was derived from
   * this model and the recording has a pose for every one of its bones; `setFigureMode`
   * chooses between it and the model's segment geometry.
   */
  setFigure(figure: FigureAsset | null): void {
    if (this.figureLayer !== null) {
      this.athlete.remove(this.figureLayer.mesh);
      this.figureLayer.dispose();
      this.figureLayer = null;
    }
    if (figure !== null) {
      this.figureLayer = new FigureLayer(figure, this.figureMaterial);
      this.athlete.add(this.figureLayer.mesh);
      this.figureLayer.select(this.selectedBody);
    }
    this.applyFigureMode();
    if (this.frames !== null) {
      this.setFrame(this.frameIndex);
    }
  }

  setFigureMode(mode: FigureMode): void {
    this.figureMode = mode;
    this.applyFigureMode();
    if (this.frames !== null) {
      this.setFrame(this.frameIndex);
    }
  }

  /** Whether the anatomical figure is what is drawn right now. */
  anatomicalShown(): boolean {
    return (
      this.figureMode === "anatomical" &&
      this.figureLayer !== null &&
      (this.frames === null || this.figureLayer.covers(this.frames.pose))
    );
  }

  private applyFigureMode(): void {
    const anatomical = this.anatomicalShown();
    if (this.figureLayer !== null) {
      this.figureLayer.mesh.visible = anatomical;
    }
    for (const meshes of this.bodyMeshes.values()) {
      for (const mesh of meshes) {
        if (mesh.userData.role !== "barbell") {
          mesh.visible = !anatomical;
        }
      }
    }
    // Instruments inside the body — joint axes, the selected joint's ring, the centre of mass
    // and its plumb line — are drawn through the skin when the figure covers the segments.
    for (const material of [this.materials.lapisLine, this.materials.selectedRing, this.materials.gold, this.materials.plumb]) {
      material.depthTest = !anatomical;
      material.needsUpdate = true;
    }
    for (const object of [this.com, this.plumb, this.selectedRing, this.jointAxes]) {
      object.traverse((child) => {
        child.renderOrder = anatomical ? 10 : 0;
      });
    }
  }

  /** Attach a recording's frames: paths and the floor instrument are built once per recording. */
  setFrames(frames: StageFrames): void {
    this.frames = frames;
    this.applyFigureMode();
    this.disposePaths();
    const bar = this.path(frames.kinematics, "bar");
    const com = this.path(frames.kinematics, "com");
    if (bar !== null) {
      const past = new THREE.BufferGeometry().setFromPoints(bar);
      const future = new THREE.BufferGeometry().setFromPoints(bar);
      this.barPast = new THREE.Line(past, this.materials.barPast);
      this.barFuture = new THREE.Line(future, this.materials.barFuture);
      this.barFuture.computeLineDistances();
      const group = new THREE.Group();
      group.add(this.barPast, this.barFuture);
      this.scene.add(group);
      this.replaceLayer("barPath", group);
    }
    if (com !== null) {
      this.comPathLine = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(com),
        this.materials.comPath,
      );
      this.comPathLine.computeLineDistances();
      this.scene.add(this.comPathLine);
      this.replaceLayer("comPath", this.comPathLine);
    }
    this.buildFloorInstrument(this.balancePoint());
    this.setFrame(Math.min(this.frameIndex, frames.pose.count - 1));
  }

  /** The floor instrument's centre: the recording's first centre of pressure. */
  balancePoint(): [number, number] {
    const kinetics = this.frames?.kinetics;
    const x = at(column(kinetics, "cop.x"), 0);
    const y = at(column(kinetics, "cop.y"), 0);
    return [Number.isFinite(x) ? x : 0, Number.isFinite(y) ? y : 0];
  }

  private path(table: LaboratoryFrameTable, prefix: string): THREE.Vector3[] | null {
    const x = column(table, `${prefix}.x`);
    const y = column(table, `${prefix}.y`);
    const z = column(table, `${prefix}.z`);
    if (x === undefined || y === undefined || z === undefined) {
      return null;
    }
    const points: THREE.Vector3[] = [];
    for (let i = 0; i < table.count; i += 1) {
      points.push(new THREE.Vector3(at(x, i), at(y, i), at(z, i)));
    }
    return points;
  }

  private replaceLayer(layer: Layer, object: THREE.Object3D): void {
    const previous = this.layerGroups.get(layer);
    if (previous !== undefined && previous !== object) {
      this.scene.remove(previous);
    }
    this.layerGroups.set(layer, object);
  }

  private disposePaths(): void {
    for (const line of [this.barPast, this.barFuture, this.comPathLine]) {
      line?.geometry.dispose();
    }
    for (const layer of ["barPath", "comPath"] as const) {
      const object = this.layerGroups.get(layer);
      if (object !== undefined) {
        this.scene.remove(object);
        this.layerGroups.delete(layer);
      }
    }
    this.barPast = null;
    this.barFuture = null;
    this.comPathLine = null;
  }

  private buildFloorInstrument(centre: [number, number]): void {
    for (const child of [...this.floorInstrument.children]) {
      this.floorInstrument.remove(child);
      if (child instanceof THREE.Line) {
        child.geometry.dispose();
      }
    }
    const [cx, cy] = centre;
    for (const radius of FLOOR_RINGS_M) {
      const points: THREE.Vector3[] = [];
      for (let k = 0; k <= 128; k += 1) {
        const angle = (k / 128) * Math.PI * 2;
        points.push(new THREE.Vector3(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle), 0.0005));
      }
      const material = radius === 0.5 || radius === 1.0 ? this.materials.ringStrong : this.materials.ring;
      this.floorInstrument.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material));
    }
    // Graduation: every 10° on the outer ring, longer every 30°.
    const ticks: THREE.Vector3[] = [];
    for (let degree = 0; degree < 360; degree += 10) {
      const angle = (degree * Math.PI) / 180;
      const inner = degree % 30 === 0 ? 0.94 : 0.97;
      ticks.push(
        new THREE.Vector3(cx + inner * Math.cos(angle), cy + inner * Math.sin(angle), 0.0005),
        new THREE.Vector3(cx + Math.cos(angle), cy + Math.sin(angle), 0.0005),
      );
    }
    // A cross through the centre, along the athlete's axes.
    ticks.push(
      new THREE.Vector3(cx - 1.0, cy, 0.0005),
      new THREE.Vector3(cx + 1.0, cy, 0.0005),
      new THREE.Vector3(cx, cy - 1.0, 0.0005),
      new THREE.Vector3(cx, cy + 1.0, 0.0005),
    );
    this.floorInstrument.add(
      new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(ticks), this.materials.ring),
    );
  }

  /** Pose everything at recorded frame `index`. */
  setFrame(index: number): void {
    const frames = this.frames;
    if (frames === null) {
      return;
    }
    const frame = Math.min(Math.max(0, index), frames.pose.count - 1);
    this.frameIndex = frame;
    const pose = frames.pose;
    for (const [name, group] of this.bodies) {
      const px = at(column(pose, `${name}.px`), frame);
      if (!Number.isFinite(px)) {
        group.visible = false;
        continue;
      }
      group.visible = true;
      group.position.set(px, at(column(pose, `${name}.py`), frame), at(column(pose, `${name}.pz`), frame));
      group.quaternion.copy(
        quaternionOf([
          at(column(pose, `${name}.qw`), frame),
          at(column(pose, `${name}.qx`), frame),
          at(column(pose, `${name}.qy`), frame),
          at(column(pose, `${name}.qz`), frame),
        ]),
      );
      group.updateMatrixWorld(true);
    }
    if (this.figureLayer !== null && this.anatomicalShown()) {
      this.figureLayer.pose(pose, frame);
    }
    // The joint axes follow their bodies.
    for (const line of this.jointAxes.children) {
      const group = this.bodies.get(String(line.userData.body));
      if (group !== undefined) {
        line.position.copy(group.position);
        line.quaternion.copy(group.quaternion);
      }
    }

    const kinetics = frames.kinetics;
    const kinematics = frames.kinematics;
    const metresPerNewton = GRF_METRES_PER_KN / 1000;
    for (const [side, arrow] of this.grf) {
      const foot = side === "l" ? "left" : "right";
      const origin = new THREE.Vector3(
        at(column(kinetics, `cop_${foot}.x`), frame),
        at(column(kinetics, `cop_${foot}.y`), frame),
        0.004,
      );
      const force = new THREE.Vector3(
        at(column(kinetics, `grf_${foot}.x`), frame),
        at(column(kinetics, `grf_${foot}.y`), frame),
        at(column(kinetics, `grf_${foot}.z`), frame),
      ).multiplyScalar(metresPerNewton);
      if (!Number.isFinite(origin.x) || !Number.isFinite(force.z)) {
        arrow.group.visible = false;
      } else {
        arrow.set(origin, force);
      }
    }

    const com = new THREE.Vector3(
      at(column(kinematics, "com.x"), frame),
      at(column(kinematics, "com.y"), frame),
      at(column(kinematics, "com.z"), frame),
    );
    this.com.position.copy(com);
    this.plumb.geometry.setFromPoints([com, new THREE.Vector3(com.x, com.y, 0.001)]);
    this.plumb.computeLineDistances();
    this.comFoot.position.set(com.x, com.y, 0.002);

    // Plantar discs (√ of the published normal load) and the loaded support polygon.
    const loaded: Point2[] = [];
    this.contactNames.forEach((name, i) => {
      const disc = this.plantarDiscs[i];
      if (disc === undefined) {
        return;
      }
      const load = at(column(kinetics, `contact.${name}.normal_n`), frame);
      const x = at(column(kinetics, `contact.${name}.x`), frame);
      const y = at(column(kinetics, `contact.${name}.y`), frame);
      const bearing = Number.isFinite(load) && load > this.loadedThreshold;
      disc.visible = bearing && Number.isFinite(x);
      if (disc.visible) {
        const radius = 0.006 + 0.0024 * Math.sqrt(Math.max(0, load));
        disc.position.set(x, y, 0.003);
        disc.scale.set(radius, radius, 1);
        loaded.push([x, y]);
      }
    });
    const hull = convexHull(loaded);
    if (hull.length >= 3) {
      const shape = new THREE.Shape(hull.map(([x, y]) => new THREE.Vector2(x, y)));
      this.supportFill.geometry.dispose();
      this.supportFill.geometry = new THREE.ShapeGeometry(shape);
      this.supportOutline.geometry.dispose();
      this.supportOutline.geometry = new THREE.BufferGeometry().setFromPoints(
        hull.map(([x, y]) => new THREE.Vector3(x, y, 0)),
      );
      this.supportFill.visible = true;
      this.supportOutline.visible = true;
    } else {
      this.supportFill.visible = false;
      this.supportOutline.visible = false;
    }

    // The bar path: travelled solid, still to come dashed.
    if (this.barPast !== null && this.barFuture !== null) {
      this.barPast.geometry.setDrawRange(0, frame + 1);
      this.barFuture.geometry.setDrawRange(frame, frames.kinematics.count - frame);
    }

    this.placeSelectedRing();
  }

  setLayers(layers: Readonly<Record<Layer, boolean>>): void {
    for (const [layer, object] of this.layerGroups) {
      object.visible = layers[layer];
    }
  }

  /** Highlight the selected body's segments and ring the selected joint. */
  setSelection(body: string | null, joint: string | null): void {
    if (this.selectedBody !== null) {
      for (const mesh of this.bodyMeshes.get(this.selectedBody) ?? []) {
        if (mesh.userData.role === "segment" || mesh.userData.role === "visual") {
          mesh.material = this.materials.bone;
        }
      }
    }
    this.selectedBody = body;
    for (const mesh of this.bodyMeshes.get(body ?? "") ?? []) {
      if (mesh.userData.role === "segment" || mesh.userData.role === "visual") {
        mesh.material = this.materials.boneSelected;
      }
    }
    this.selectedJoint = this.model.joints.find((entry) => entry.name === joint) ?? null;
    this.figureLayer?.select(body);
    this.placeSelectedRing();
  }

  private placeSelectedRing(): void {
    const joint = this.selectedJoint;
    const group = joint === null ? undefined : this.bodies.get(joint.body);
    if (joint === null || group === undefined) {
      this.selectedRing.visible = false;
      return;
    }
    this.selectedRing.visible = true;
    const anchor = new THREE.Vector3(...joint.position_m).applyMatrix4(group.matrixWorld);
    const axis = new THREE.Vector3(...joint.axis).applyQuaternion(group.quaternion).normalize();
    this.selectedRing.position.copy(anchor);
    this.selectedRing.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axis);
  }

  /** World position of a joint's anchor at the current frame. */
  jointPosition(joint: LaboratoryJoint): THREE.Vector3 | null {
    const group = this.bodies.get(joint.body);
    if (group === undefined || !group.visible) {
      return null;
    }
    return new THREE.Vector3(...joint.position_m).applyMatrix4(group.matrixWorld);
  }

  /** Published per-foot centre of pressure and force at the current frame. */
  footForce(side: "l" | "r"): { origin: THREE.Vector3; tip: THREE.Vector3; newtons: number } | null {
    const kinetics = this.frames?.kinetics;
    if (kinetics === undefined) {
      return null;
    }
    const foot = side === "l" ? "left" : "right";
    const frame = this.frameIndex;
    const origin = new THREE.Vector3(
      at(column(kinetics, `cop_${foot}.x`), frame),
      at(column(kinetics, `cop_${foot}.y`), frame),
      0,
    );
    const force = new THREE.Vector3(
      at(column(kinetics, `grf_${foot}.x`), frame),
      at(column(kinetics, `grf_${foot}.y`), frame),
      at(column(kinetics, `grf_${foot}.z`), frame),
    );
    if (!Number.isFinite(origin.x) || !Number.isFinite(force.z)) {
      return null;
    }
    return {
      origin,
      tip: origin.clone().addScaledVector(force, GRF_METRES_PER_KN / 1000),
      newtons: force.length(),
    };
  }

  centreOfMass(): THREE.Vector3 {
    return this.com.position.clone();
  }

  setOrbit(orbit: Orbit): void {
    this.orbit = orbit;
    this.camera.position.set(...orbitPosition(orbit));
    this.camera.lookAt(...orbit.target);
    this.camera.updateMatrixWorld(true);
  }

  resize(width: number, height: number): void {
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
  }

  /** A world point in CSS pixels of a `width` × `height` canvas. */
  project(point: THREE.Vector3, width: number, height: number): ScreenPoint {
    const projected = point.clone().project(this.camera);
    return {
      x: ((projected.x + 1) / 2) * width,
      y: ((1 - projected.y) / 2) * height,
      visible: projected.z > -1 && projected.z < 1,
    };
  }

  /** The body under a canvas point, if any. */
  pick(x: number, y: number, width: number, height: number): string | null {
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(new THREE.Vector2((x / width) * 2 - 1, 1 - (y / height) * 2), this.camera);
    if (this.figureLayer !== null && this.anatomicalShown()) {
      return this.figureLayer.pick(raycaster);
    }
    const meshes = [...this.bodyMeshes.values()].flat().filter((mesh) => mesh.visible);
    const [hit] = raycaster.intersectObjects(meshes, false);
    return hit === undefined ? null : String(hit.object.userData.body);
  }

  /** Screen-space unit axes of the world frame (for the orientation instrument). */
  worldAxes(): { x: [number, number]; y: [number, number]; z: [number, number] } {
    const view = this.camera.matrixWorldInverse;
    const axis = (v: THREE.Vector3): [number, number] => {
      const d = v.clone().transformDirection(view);
      return [d.x, -d.y];
    };
    return {
      x: axis(new THREE.Vector3(1, 0, 0)),
      y: axis(new THREE.Vector3(0, 1, 0)),
      z: axis(new THREE.Vector3(0, 0, 1)),
    };
  }

  /** Pixels per metre at the orbit target's depth (for the scale bar). */
  pixelsPerMetre(height: number): number {
    const distance = this.orbit?.distance ?? 4;
    return height / (2 * distance * Math.tan((FIELD_OF_VIEW_DEG * Math.PI) / 360));
  }

  render(): void {
    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.disposePaths();
    this.figureLayer?.dispose();
    this.figureMaterial.dispose();
    this.scene.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
        object.geometry.dispose();
      }
    });
    for (const material of Object.values(this.materials)) {
      material.dispose();
    }
    this.renderer.dispose();
  }
}

/** Whether this runtime can draw the stage at all (jsdom and some hosts cannot).
 *
 * The probe context is released immediately: browsers cap live WebGL contexts, and a probe
 * that held one would push the stage's own context towards eviction.
 */
export function webglAvailable(): boolean {
  if (typeof window === "undefined" || typeof WebGL2RenderingContext === "undefined") {
    return false;
  }
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2");
    if (context === null) {
      return false;
    }
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

/** A bounded, path-free account of why the stage could not start or continue. */
export function stageFailureReason(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  const firstLine = text.split("\n")[0] ?? "";
  // A renderer message can name a file or a URL; neither is shown.
  const pathFree = firstLine.replace(/(?:[A-Za-z]+:\/\/|[A-Za-z]:\\|\/)[^\s)]*/g, "…");
  return (pathFree.trim() || "the renderer reported an error").slice(0, 160);
}
