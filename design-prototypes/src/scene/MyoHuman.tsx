import { Html, Line } from '@react-three/drei';
import { type ThreeEvent } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { jointMatrix, loadMesh, useMyoModel, type MBody, type MGeom, type MJoint } from '../data/myosim';
import { useWB } from '../state';

type Pal = { bone: string; sel: string; hover: string; ink: string };

// MyoSim bodies use OpenSim frames (y up, x anterior). Their root euler maps them into MuJoCo's
// z-up world facing −y; the extra +90° about z makes the subject face +x like the rest of the scene.
const FACING = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2);

function GeomMesh({ g, id, color, sel, pal }: { g: MGeom; id: string; color: string; sel: boolean; pal: Pal }) {
  const { d } = useWB();
  const [geo, setGeo] = useState<THREE.BufferGeometry | null>(null);
  useEffect(() => { let live = true; loadMesh(g.file).then((x) => live && setGeo(x)); return () => { live = false; }; }, [g.file]);
  if (!geo) return null;
  return (
    <group position={g.pos} quaternion={g.quat}>
      <mesh
        geometry={geo}
        castShadow
        onClick={(e: ThreeEvent<MouseEvent>) => { if (e.delta > 4) return; e.stopPropagation(); d({ type: 'select', id }); }}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); d({ type: 'hover', id }); document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { d({ type: 'hover', id: null }); document.body.style.cursor = ''; }}
      >
        <meshStandardMaterial color={color} roughness={0.55} metalness={0.02} emissive={sel ? pal.sel : '#000000'} emissiveIntensity={sel ? 0.25 : 0} />
      </mesh>
    </group>
  );
}

/** Axis arrow and swept-angle arc for a selected joint, drawn in the body frame before the joint acts. */
function AxisGlyph({ j, value, pal }: { j: MJoint; value: number; pal: Pal }) {
  const a = j.axis.clone().normalize();
  const ref = Math.abs(a.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
  const u = ref.sub(a.clone().multiplyScalar(ref.dot(a))).normalize().multiplyScalar(0.09);
  const pts: [number, number, number][] = [];
  const n = Math.max(2, Math.ceil(Math.abs(value) / 0.04));
  for (let i = 0; i <= n; i++) { const p = u.clone().applyAxisAngle(a, (value * i) / n).add(j.pos); pts.push([p.x, p.y, p.z]); }
  const tip = j.pos.clone().add(a.clone().multiplyScalar(0.13)), tail = j.pos.clone().add(a.clone().multiplyScalar(-0.13));
  const lab = pts[Math.floor(pts.length / 2)];
  return (
    <group>
      <Line points={[tail.toArray() as [number, number, number], tip.toArray() as [number, number, number]]} color={pal.sel} lineWidth={2.4} depthTest={false} />
      <mesh position={tip} quaternion={new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), a)} renderOrder={10}>
        <coneGeometry args={[0.012, 0.03, 12]} />
        <meshBasicMaterial color={pal.sel} depthTest={false} />
      </mesh>
      <Line points={[j.pos.toArray() as [number, number, number], j.pos.clone().add(u).toArray() as [number, number, number]]} color={pal.ink} lineWidth={1} dashed dashSize={0.012} gapSize={0.01} depthTest={false} />
      {Math.abs(value) > 0.005 && <Line points={pts} color={pal.sel} lineWidth={2.6} depthTest={false} />}
      <Html position={lab} style={{ pointerEvents: 'none' }} zIndexRange={[12, 0]}>
        <div className="mono whitespace-nowrap rounded bg-accent px-1 text-[10px] text-white">{j.name} {value.toFixed(2)} rad</div>
      </Html>
    </group>
  );
}

function BodyNode({ b, pal }: { b: MBody; pal: Pal }) {
  const { s } = useWB();
  const inner = useRef<THREE.Group>(null);
  const m = jointMatrix(b, s.myoPose);
  useLayoutEffect(() => { if (inner.current) { inner.current.matrix.copy(m); inner.current.matrixWorldNeedsUpdate = true; } });
  const id = `mbody.${b.name}`;
  const sel = s.selection === id, hov = s.hover === id;
  const color = sel ? pal.sel : hov ? pal.hover : pal.bone;
  const selJoint = s.selection?.startsWith('mjoint.') ? b.joints.find((j) => `mjoint.${j.name}` === s.selection) : undefined;
  return (
    <group position={b.pos} quaternion={b.quat}>
      {selJoint && selJoint.type === 'hinge' && <AxisGlyph j={selJoint} value={s.myoPose[selJoint.name] ?? 0} pal={pal} />}
      <group ref={inner} matrixAutoUpdate={false}>
        {s.overlays.geometry && b.geoms.map((g) => <GeomMesh key={g.mesh} g={g} id={id} color={color} sel={sel} pal={pal} />)}
        {s.overlays.frames && b.joints.length > 0 && (
          <group>
            <Line points={[[0, 0, 0], [0.06, 0, 0]]} color="#d0453a" lineWidth={1.2} depthTest={false} />
            <Line points={[[0, 0, 0], [0, 0.06, 0]]} color="#2f9a5f" lineWidth={1.2} depthTest={false} />
            <Line points={[[0, 0, 0], [0, 0, 0.06]]} color="#3a6fc4" lineWidth={1.2} depthTest={false} />
          </group>
        )}
        {s.overlays.com && b.com && b.mass && (
          <mesh position={b.com} renderOrder={5}><sphereGeometry args={[0.012, 12, 8]} /><meshBasicMaterial color={pal.ink} depthTest={false} transparent opacity={0.7} /></mesh>
        )}
        {b.children.map((c) => <BodyNode key={c.name} b={c} pal={pal} />)}
      </group>
    </group>
  );
}

/** Standing height: lowest point of the meshes in the neutral pose sits on the plate (z = 0). */
const STAND_Z = 0.935;

export function MyoHuman({ pal }: { pal: Pal }) {
  const { s } = useWB();
  const { model, error } = useMyoModel();
  const q = s.pose;
  const roots = useMemo(() => model?.roots ?? [], [model]);
  if (error) return <Html center><div className="chip px-2 py-1 text-[12px] text-err">MyoSim reference model failed to load: {error}</div></Html>;
  if (!model) return <Html center><div className="chip px-2 py-1 text-[12px] text-ink-2">Loading MyoSim reference geometry…</div></Html>;
  return (
    <group position={[q.pelvis_tx, 0, STAND_Z + (q.pelvis_tz - 0.93)]} rotation={[0, q.pelvis_tilt, 0]}>
      <group quaternion={FACING}>
        {roots.map((r) => <BodyNode key={r.name} b={r} pal={pal} />)}
      </group>
    </group>
  );
}
