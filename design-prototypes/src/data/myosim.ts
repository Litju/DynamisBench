/**
 * External reference geometry: MyoSim MyoLegs + MyoTorso (MyoHub/myo_sim @ 93b0ca8f, Apache-2.0;
 * derived from Rajagopal et al. 2016, MIT). Files live in public/assets/myosim (see NOTICE).
 *
 * This module parses the MJCF body tree in the browser so the workbench can show the model's real
 * bodies, joints, axes, ranges and inertial values. It is display and inspection only: no muscle,
 * contact or equality constraint is evaluated and nothing here is a DynamisBench realization.
 */
import { useEffect, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';

export const MYO = {
  repo: 'github.com/MyoHub/myo_sim',
  commit: '93b0ca8f4ec90c9899ee7f05fee561e9911da91b',
  license: 'Apache-2.0 (MyoSim); upstream Rajagopal 2016 full-body model MIT (© 2015 Stanford University)',
  base: '/assets/myosim',
};

export type MJoint = { name: string; type: 'hinge' | 'slide'; axis: THREE.Vector3; pos: THREE.Vector3; range: [number, number] | null; body: string };
export type MGeom = { mesh: string; file: string; pos: THREE.Vector3; quat: THREE.Quaternion };
export type MBody = {
  name: string;
  source: 'myolegs' | 'myotorso';
  pos: THREE.Vector3;
  quat: THREE.Quaternion;
  joints: MJoint[];
  geoms: MGeom[];
  mass: number | null;
  com: THREE.Vector3 | null;
  children: MBody[];
  parent: string | null;
};
export type MyoModel = { roots: MBody[]; bodies: Map<string, MBody>; joints: Map<string, MJoint>; meshes: Map<string, string> };

const vec = (s: string | null, d = [0, 0, 0]) => { const v = (s ?? '').trim().split(/\s+/).map(Number); return new THREE.Vector3(...(v.length === 3 && v.every(Number.isFinite) ? v : d)); };

/** MJCF orientation: quat (w x y z) or euler (intrinsic xyz, radians). */
function orient(el: Element): THREE.Quaternion {
  const q = el.getAttribute('quat');
  if (q) { const [w, x, y, z] = q.trim().split(/\s+/).map(Number); return new THREE.Quaternion(x, y, z, w).normalize(); }
  const e = el.getAttribute('euler');
  if (e) { const [a, b, c] = e.trim().split(/\s+/).map(Number); return new THREE.Quaternion().setFromEuler(new THREE.Euler(a, b, c, 'XYZ')); }
  return new THREE.Quaternion();
}

function parseBody(el: Element, source: MBody['source'], meshes: Map<string, string>, parent: string | null, out: MyoModel): MBody {
  const name = el.getAttribute('name') ?? 'body';
  const b: MBody = { name, source, pos: vec(el.getAttribute('pos')), quat: orient(el), joints: [], geoms: [], mass: null, com: null, children: [], parent };
  for (const c of Array.from(el.children)) {
    if (c.tagName === 'joint') {
      const r = c.getAttribute('range');
      const j: MJoint = {
        name: c.getAttribute('name') ?? '', type: c.getAttribute('type') === 'slide' ? 'slide' : 'hinge',
        axis: vec(c.getAttribute('axis'), [0, 0, 1]).normalize(), pos: vec(c.getAttribute('pos')),
        range: r ? (r.trim().split(/\s+/).map(Number) as [number, number]) : null, body: name,
      };
      b.joints.push(j);
      out.joints.set(j.name, j);
    } else if (c.tagName === 'geom' && c.getAttribute('mesh')) {
      const m = c.getAttribute('mesh')!;
      const file = meshes.get(m);
      if (file) b.geoms.push({ mesh: m, file, pos: vec(c.getAttribute('pos')), quat: orient(c) });
    } else if (c.tagName === 'inertial') {
      b.mass = Number(c.getAttribute('mass'));
      b.com = vec(c.getAttribute('pos'));
    } else if (c.tagName === 'body') {
      b.children.push(parseBody(c, source, meshes, name, out));
    }
  }
  out.bodies.set(name, b);
  return b;
}

async function xml(path: string) {
  const r = await fetch(`${MYO.base}/xml/${path}`);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return new DOMParser().parseFromString(await r.text(), 'application/xml');
}

let modelPromise: Promise<MyoModel> | null = null;
export function loadMyoModel(): Promise<MyoModel> {
  if (modelPromise) return modelPromise;
  modelPromise = (async () => {
    const [la, lc, ta, tc] = await Promise.all([xml('myolegs_assets.xml'), xml('myolegs_chain.xml'), xml('myotorso_assets.xml'), xml('myotorso_chain.xml')]);
    const meshes = new Map<string, string>();
    for (const doc of [la, ta]) for (const m of Array.from(doc.getElementsByTagName('mesh'))) {
      const n = m.getAttribute('name'), f = m.getAttribute('file');
      if (n && f) meshes.set(n, f.split('/').pop()!);
    }
    const out: MyoModel = { roots: [], bodies: new Map(), joints: new Map(), meshes };
    const legRoot = Array.from(lc.documentElement.children).find((c) => c.tagName === 'body');
    const torsoRoot = Array.from(tc.documentElement.children).find((c) => c.tagName === 'body');
    if (legRoot) out.roots.push(parseBody(legRoot, 'myolegs', meshes, null, out));
    if (torsoRoot) out.roots.push(parseBody(torsoRoot, 'myotorso', meshes, null, out));
    return out;
  })();
  return modelPromise;
}

const stlCache = new Map<string, Promise<THREE.BufferGeometry>>();
export function loadMesh(file: string) {
  let p = stlCache.get(file);
  if (!p) {
    p = new STLLoader().loadAsync(`${MYO.base}/meshes/${file}`).then((g) => { g.computeVertexNormals(); return g; });
    stlCache.set(file, p);
  }
  return p;
}

export function useMyoModel() {
  const [state, setState] = useState<{ model: MyoModel | null; error: string | null }>({ model: null, error: null });
  useEffect(() => {
    let live = true;
    loadMyoModel().then((model) => live && setState({ model, error: null }), (e) => live && setState({ model: null, error: String(e) }));
    return () => { live = false; };
  }, []);
  return state;
}

/** Primary coordinates exposed for posing. Coupled knee/patella DOFs stay at 0 (equalities not evaluated). */
export const MYO_COORDS: { joint: string; label: string; side?: 'r' | 'l' }[] = [
  ...(['r', 'l'] as const).flatMap((s) => [
    { joint: `hip_flexion_${s}`, label: `hip_flexion_${s}`, side: s },
    { joint: `hip_adduction_${s}`, label: `hip_adduction_${s}`, side: s },
    { joint: `hip_rotation_${s}`, label: `hip_rotation_${s}`, side: s },
    { joint: `knee_angle_${s}`, label: `knee_angle_${s}`, side: s },
    { joint: `ankle_angle_${s}`, label: `ankle_angle_${s}`, side: s },
    { joint: `subtalar_angle_${s}`, label: `subtalar_angle_${s}`, side: s },
    { joint: `mtp_angle_${s}`, label: `mtp_angle_${s}`, side: s },
  ]),
  { joint: 'flex_extension', label: 'lumbar flex_extension' },
  { joint: 'lat_bending', label: 'lumbar lat_bending' },
  { joint: 'axial_rotation', label: 'lumbar axial_rotation' },
];

/** Local joint transform: product over the body's joints, in MJCF order, about each anchor. */
export function jointMatrix(b: MBody, q: Record<string, number>) {
  const m = new THREE.Matrix4();
  const t = new THREE.Matrix4(), r = new THREE.Matrix4(), ti = new THREE.Matrix4();
  for (const j of b.joints) {
    const v = q[j.name] ?? 0;
    if (!v) continue;
    if (j.type === 'slide') { m.multiply(t.makeTranslation(j.axis.x * v, j.axis.y * v, j.axis.z * v)); continue; }
    t.makeTranslation(j.pos.x, j.pos.y, j.pos.z);
    r.makeRotationAxis(j.axis, v);
    ti.makeTranslation(-j.pos.x, -j.pos.y, -j.pos.z);
    m.multiply(t).multiply(r).multiply(ti);
  }
  return m;
}
