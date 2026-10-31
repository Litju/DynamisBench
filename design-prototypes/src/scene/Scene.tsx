import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber';
import { GizmoHelper, GizmoViewport, Grid, Html, Line, OrbitControls, RoundedBox } from '@react-three/drei';
import { Component, useEffect, useMemo, useRef, type ReactNode } from 'react';
import * as THREE from 'three';
import { REF } from '../data/authority';
import { SEG } from '../data/models';
import { idx, seriesById } from '../data/numerics';
import { useWB } from '../state';
import { MyoHuman } from './MyoHuman';

THREE.Object3D.DEFAULT_UP.set(0, 0, 1); // model frames are z-up (MuJoCo world, LCMJ20 fixture)

type Palette = { bone: string; bg: string; seg: string; segAlt: string; joint: string; sel: string; hover: string; plate: string; cell: string; section: string; ghost: string; site: string; trace: string; ink: string; shadow: number };
const PALETTE: Record<'light' | 'dark', Palette> = {
  light: { bone: '#dcd4c2', bg: '#f3f4f6', seg: '#b3bcc7', segAlt: '#c9cfd7', joint: '#66717f', sel: '#1f57a8', hover: '#6f96d0', plate: '#d3d8de', cell: '#dfe3e8', section: '#bcc3cc', ghost: '#c0571b', site: '#e5713a', trace: '#8fa6c6', ink: '#1b2129', shadow: 0.16 },
  dark: { bone: '#b4ab98', bg: '#15191e', seg: '#738091', segAlt: '#5a6573', joint: '#a3aebb', sel: '#6fa3ea', hover: '#4c76ae', plate: '#2b323b', cell: '#232931', section: '#38424d', ghost: '#f0915a', site: '#f08a50', trace: '#58779f', ink: '#e3e7ed', shadow: 0.35 },
};

type Pick = { onPick: (id: string) => void; onHover: (id: string | null) => void };
const handlers = (id: string, { onPick, onHover }: Pick) => ({
  onClick: (e: ThreeEvent<MouseEvent>) => { if (e.delta > 4) return; e.stopPropagation(); onPick(id); },
  onPointerOver: (e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); onHover(id); document.body.style.cursor = 'pointer'; },
  onPointerOut: () => { onHover(null); document.body.style.cursor = ''; },
});

/* Tapered, rounded limb proxy (lathe about the segment axis), built along +z (dir 1) or −z (dir −1). */
const geoCache = new Map<string, THREE.BufferGeometry>();
function limb(len: number, r0: number, r1: number, bulge = 0, dir: 1 | -1 = -1) {
  const key = [len, r0, r1, bulge, dir].join('|');
  const hit = geoCache.get(key);
  if (hit) return hit;
  // Profile in lathe space (x = radius, y = axial), from the bottom pole to the top pole.
  const prof: [number, number][] = []; // [radius, axial distance along segment, 0 → len]
  const capN = 6;
  for (let i = 0; i <= capN; i++) { const a = (Math.PI / 2) * (i / capN); prof.push([r0 * Math.sin(a), -r0 * 0.55 * Math.cos(a)]); }
  const n = 18;
  for (let i = 1; i < n; i++) {
    const u = i / n;
    prof.push([r0 + (r1 - r0) * u + bulge * Math.sin(Math.PI * Math.pow(u, 0.75)), u * len]);
  }
  for (let i = capN; i >= 0; i--) { const a = (Math.PI / 2) * (i / capN); prof.push([r1 * Math.sin(a), len + r1 * 0.55 * Math.cos(a)]); }
  // Lathe needs increasing y for outward normals; build along +y then flip by rotation if dir = −1.
  const pts = prof.map(([r, a]) => new THREE.Vector2(Math.max(r, 1e-4), a)).reverse();
  const g = new THREE.LatheGeometry(pts, 28);
  g.rotateX(dir === 1 ? Math.PI / 2 : -Math.PI / 2); // lathe axis y → model ±z
  g.computeVertexNormals();
  geoCache.set(key, g);
  return g;
}

function Part({ id, geometry, rounded, pos, scale, color, pal, pick, children }: { id: string; geometry?: THREE.BufferGeometry; rounded?: { args: [number, number, number]; radius: number }; pos?: [number, number, number]; scale?: [number, number, number]; color: string; pal: Palette; pick: Pick; children?: ReactNode }) {
  const { s } = useWB();
  const sel = s.selection === id, hov = s.hover === id;
  const c = sel ? pal.sel : hov ? pal.hover : color;
  if (rounded) {
    return (
      <group position={pos} scale={scale}>
        <RoundedBox args={rounded.args} radius={rounded.radius} smoothness={4} castShadow {...handlers(id, pick)}>
          <meshStandardMaterial color={c} roughness={0.62} metalness={0.04} emissive={sel ? pal.sel : '#000000'} emissiveIntensity={sel ? 0.18 : 0} />
        </RoundedBox>
        {sel && (
          <RoundedBox args={rounded.args.map((v) => v * 1.08) as [number, number, number]} radius={rounded.radius * 1.08} smoothness={4} raycast={() => null}>
            <meshBasicMaterial color={pal.sel} side={THREE.BackSide} transparent opacity={0.5} />
          </RoundedBox>
        )}
      </group>
    );
  }
  return (
    <group position={pos} scale={scale}>
      <mesh geometry={geometry} castShadow {...handlers(id, pick)}>
        {children}
        <meshStandardMaterial color={c} roughness={0.62} metalness={0.04} emissive={sel ? pal.sel : '#000000'} emissiveIntensity={sel ? 0.18 : 0} side={THREE.DoubleSide} />
      </mesh>
      {sel && geometry && (
        <mesh geometry={geometry} scale={1.07} raycast={() => null}>
          <meshBasicMaterial color={pal.sel} side={THREE.BackSide} transparent opacity={0.5} />
        </mesh>
      )}
    </group>
  );
}

function Frame({ size = 0.18, label, show, labels = true, labelAt }: { size?: number; label?: string; show: boolean; labels?: boolean; labelAt?: [number, number, number] }) {
  if (!show) return null;
  return (
    <group>
      <Line points={[[0, 0, 0], [size, 0, 0]]} color="#d0453a" lineWidth={1.6} />
      <Line points={[[0, 0, 0], [0, size, 0]]} color="#2f9a5f" lineWidth={1.6} />
      <Line points={[[0, 0, 0], [0, 0, size]]} color="#3a6fc4" lineWidth={1.6} />
      {label && labels && (
        <Html position={labelAt ?? [size * 0.15, 0, size * 1.1]} style={{ pointerEvents: 'none' }} zIndexRange={[5, 0]}>
          <div className="mono chip whitespace-nowrap px-1 text-[10px] text-ink-2">{label}</div>
        </Html>
      )}
    </group>
  );
}

function Label({ at, text, show, strong }: { at: [number, number, number]; text: string; show: boolean; strong?: boolean }) {
  if (!show) return null;
  return (
    <Html position={at} style={{ pointerEvents: 'none' }} zIndexRange={[10, 0]}>
      <div className={`whitespace-nowrap rounded border px-1.5 py-px text-[10.5px] shadow-sm ${strong ? 'border-accent bg-accent text-white' : 'chip text-ink-2'}`}>{text}</div>
    </Html>
  );
}

/** Joint glyph in the parent frame: hinge axis (+y arrow), reference direction (dashed) and swept-angle arc. */
function JointGlyph({ angle, sign, refDir, r, pal, label }: { angle: number; sign: 1 | -1; refDir: 'down' | 'fwd' | 'up'; r: number; pal: Palette; label: string }) {
  const dirAt = (a: number): [number, number, number] => {
    const b = sign * a;
    if (refDir === 'down') return [-Math.sin(b) * r, 0, -Math.cos(b) * r];
    if (refDir === 'up') return [Math.sin(b) * r, 0, Math.cos(b) * r];
    return [Math.cos(b) * r, 0, -Math.sin(b) * r];
  };
  const pts: [number, number, number][] = [];
  const n = Math.max(2, Math.ceil(Math.abs(angle) / 0.04));
  for (let i = 0; i <= n; i++) pts.push(dirAt((angle * i) / n));
  const mid = dirAt(angle / 2);
  return (
    <group>
      <Line points={[[0, -0.15, 0], [0, 0.15, 0]]} color={pal.sel} lineWidth={2.2} />
      <mesh position={[0, 0.165, 0]} raycast={() => null}><coneGeometry args={[0.017, 0.042, 14]} /><meshBasicMaterial color={pal.sel} /></mesh>
      <Line points={[[0, 0, 0], dirAt(0)]} color={pal.ink} lineWidth={1} dashed dashSize={0.02} gapSize={0.015} transparent opacity={0.55} />
      {Math.abs(angle) > 0.005 && <Line points={pts} color={pal.sel} lineWidth={2.4} />}
      <Html position={[mid[0] * 1.3, 0, mid[2] * 1.3]} style={{ pointerEvents: 'none' }} zIndexRange={[12, 0]}>
        <div className="mono whitespace-nowrap rounded bg-accent px-1 text-[10px] text-white">{label}</div>
      </Html>
    </group>
  );
}

/* ---------------- Reference pendulum (authority structure) ---------------- */

function Pendulum({ theta, ghostTheta, pick, compact, pal }: { theta: number; ghostTheta?: number | null; pick: Pick; compact?: boolean; pal: Palette }) {
  const { s } = useWB();
  const o = compact ? { ...s.overlays, labels: false } : s.overlays;
  const traj = useMemo(() => {
    const ser = seriesById('series.rk4-1ms');
    const pts: [number, number, number][] = [];
    for (let i = 0; i < ser.t.length; i += 10) pts.push([-Math.sin(ser.theta[i]), 0, -Math.cos(ser.theta[i])]);
    return pts;
  }, []);
  const rod = useMemo(() => limb(0.92, 0.016, 0.013, 0, -1), []);
  const jointSel = s.selection === 'joint.hinge' || s.selection === 'coord.hinge' || s.selection === 'q.angle';
  return (
    <group>
      <Part id="body.world" pos={[0, 0, 0.075]} color={pal.joint} pal={pal} pick={pick}>
        <boxGeometry args={[0.52, 0.2, 0.035]} />
      </Part>
      <Frame show={o.frames} label="world" size={0.25} labels={o.labels} labelAt={[-0.36, 0, 0.14]} />
      {o.trace && <Line points={traj} color={pal.trace} lineWidth={1} dashed dashSize={0.02} gapSize={0.015} />}
      {ghostTheta != null && (
        <group rotation={[0, ghostTheta, 0]}>
          <mesh geometry={rod} position={[0, 0, -0.03]} raycast={() => null}><meshStandardMaterial color={pal.ghost} transparent opacity={0.6} /></mesh>
          <mesh position={[0, 0, -1]} raycast={() => null}><sphereGeometry args={[0.05, 24, 16]} /><meshStandardMaterial color={pal.ghost} transparent opacity={0.55} /></mesh>
        </group>
      )}
      {jointSel && <JointGlyph angle={theta} sign={1} refDir="down" r={0.42} pal={pal} label={`θ ${theta.toFixed(4)} rad`} />}
      <group rotation={[0, theta, 0]}>
        <Part id="joint.hinge" color={pal.joint} pal={pal} pick={pick}>
          <cylinderGeometry args={[0.032, 0.032, 0.16, 28]} />
        </Part>
        <Frame show={o.frames && !jointSel} label="hinge axis +y" size={0.16} labels={o.labels} labelAt={[0, 0.2, -0.05]} />
        {o.geometry && (
          <>
            <Part id="body.pendulum" geometry={rod} pos={[0, 0, -0.03]} color={pal.seg} pal={pal} pick={pick} />
            <Part id="body.pendulum" pos={[0, 0, -1]} color={pal.seg} pal={pal} pick={pick}>
              <sphereGeometry args={[0.055, 32, 20]} />
            </Part>
          </>
        )}
        <mesh position={[0, 0, -1]} {...handlers('site.bob', pick)}>
          <sphereGeometry args={[s.selection === 'site.bob' ? 0.03 : 0.021, 20, 14]} />
          <meshStandardMaterial color={s.selection === 'site.bob' ? pal.sel : pal.site} emissive={pal.site} emissiveIntensity={0.2} />
        </mesh>
        {o.com && (
          <group position={[0, -0.06, -1]}>
            <Line points={[[-0.09, 0, 0], [0.09, 0, 0]]} color={pal.ink} lineWidth={1} />
            <Line points={[[0, 0, -0.09], [0, 0, 0.09]]} color={pal.ink} lineWidth={1} />
          </group>
        )}
        <Label at={[0.07, 0, -1.09]} text="pendulum · COM / site bob" show={o.labels} strong={s.selection === 'body.pendulum' || s.selection === 'site.bob'} />
      </group>
      {o.gravity && (
        <group position={[-Math.sin(theta), 0, -Math.cos(theta)]}>
          <arrowHelper args={[new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0, 0), 0.35, 0xb07a10, 0.07, 0.04]} />
          <Label at={[0.05, 0, -0.32]} text={`m·g = ${(REF.massKg * REF.gravity).toFixed(3)} N (world −z)`} show={!compact} />
        </group>
      )}
    </group>
  );
}

/* ---------------- LCMJ20 planar sagittal subject: design-only anatomical proxy ---------------- */

function Human({ pick, compact, pal }: { pick: Pick; compact?: boolean; pal: Palette }) {
  const { s } = useWB();
  const q = s.pose;
  const o = compact ? { ...s.overlays, labels: false } : s.overlays;
  const g = useMemo(() => ({
    thigh: limb(SEG.thigh - 0.06, 0.07, 0.046, 0.006),
    shank: limb(SEG.shank - 0.05, 0.05, 0.031, 0.012),
    torso: limb(SEG.trunk - 0.1, 0.118, 0.142, 0.006, 1),
    neck: limb(0.06, 0.035, 0.033, 0, 1),
    upperArm: limb(0.25, 0.04, 0.032, 0.004),
    foreArm: limb(0.23, 0.031, 0.024, 0.004),
  }), []);
  const sel = s.selection;
  const glyph = (jid: string, angle: number, sign: 1 | -1, refDir: 'down' | 'fwd' | 'up', label: string) =>
    sel === jid ? <JointGlyph angle={angle} sign={sign} refDir={refDir} r={0.2} pal={pal} label={label} /> : null;
  const ball = (id: string, r = 0.034) => (
    <Part id={id} color={pal.joint} pal={pal} pick={pick}><sphereGeometry args={[r, 20, 14]} /></Part>
  );
  const leg = (side: 'r' | 'l') => {
    const y = side === 'r' ? -SEG.pelvisHalf : SEG.pelvisHalf;
    const base = side === 'r' ? pal.seg : pal.segAlt;
    return (
      <group key={side} position={[0, y, 0]}>
        {glyph(`joint.hip_${side}`, q[`hip_${side}`], -1, 'down', `hip_flexion_${side} ${q[`hip_${side}`].toFixed(2)} rad`)}
        <group rotation={[0, -q[`hip_${side}`], 0]}>
          {ball(`joint.hip_${side}`)}
          <Frame show={o.frames} size={0.09} />
          {o.geometry && <Part id={`body.thigh_${side}`} geometry={g.thigh} pos={[0, 0, -0.035]} scale={[1, 0.92, 1]} color={base} pal={pal} pick={pick} />}
          <group position={[0, 0, -SEG.thigh]}>
            {glyph(`joint.knee_${side}`, q[`knee_${side}`], 1, 'down', `knee_flexion_${side} ${q[`knee_${side}`].toFixed(2)} rad`)}
            <group rotation={[0, q[`knee_${side}`], 0]}>
              {ball(`joint.knee_${side}`, 0.036)}
              <Frame show={o.frames} size={0.09} />
              {o.geometry && <Part id={`body.shank_${side}`} geometry={g.shank} pos={[0, 0, -0.03]} scale={[1.05, 0.9, 1]} color={base} pal={pal} pick={pick} />}
              <group position={[0, 0, -SEG.shank]}>
                {glyph(`joint.ankle_${side}`, q[`ankle_${side}`], -1, 'fwd', `ankle_dorsiflexion_${side} ${q[`ankle_${side}`].toFixed(2)} rad`)}
                <group rotation={[0, -q[`ankle_${side}`], 0]}>
                  {ball(`joint.ankle_${side}`, 0.028)}
                  <Frame show={o.frames} size={0.08} />
                  {o.geometry && (
                    <Part id={`body.foot_${side}`} pos={[(SEG.foot - SEG.heel) / 2 - SEG.heel / 2, 0, -0.047]} rounded={{ args: [SEG.foot + 0.02, 0.085, 0.066], radius: 0.026 }} color={base} pal={pal} pick={pick} />
                  )}
                </group>
              </group>
            </group>
          </group>
        </group>
      </group>
    );
  };
  const arm = (side: 'r' | 'l') => {
    const y = side === 'r' ? -0.19 : 0.19;
    const base = side === 'r' ? pal.seg : pal.segAlt;
    return (
      <group key={side} position={[0, y, SEG.trunk - 0.05]} rotation={[0, -0.12, 0]}>
        <Part id={`body.arm_${side}`} geometry={g.upperArm} pos={[0, 0, -0.03]} color={base} pal={pal} pick={pick} />
        <group position={[0, 0, -0.29]} rotation={[0, -0.35, 0]}>
          <Part id={`body.arm_${side}`} geometry={g.foreArm} pos={[0, 0, -0.02]} color={base} pal={pal} pick={pick} />
          <Part id={`body.arm_${side}`} pos={[0, 0, -0.28]} scale={[0.8, 0.55, 1.15]} color={base} pal={pal} pick={pick}><sphereGeometry args={[0.045, 18, 12]} /></Part>
        </group>
      </group>
    );
  };
  return (
    <group>
      <Part id="body.plate" pos={[0.06, 0, -0.014]} color={pal.plate} pal={pal} pick={pick}><boxGeometry args={[0.62, 0.52, 0.028]} /></Part>
      <Label at={[0.37, 0.27, 0.0]} text="force_plate (rigid, fixture)" show={o.labels} />
      <Frame show={o.frames} label="world" size={0.22} labels={o.labels} labelAt={[-0.12, -0.3, 0.02]} />
      <group position={[q.pelvis_tx, 0, q.pelvis_tz]}>
        {glyph('joint.ground_pelvis', q.pelvis_tilt, 1, 'up', `pelvis_tilt ${q.pelvis_tilt.toFixed(2)} rad`)}
        <group rotation={[0, q.pelvis_tilt, 0]}>
          <Frame show={o.frames} label="pelvis" size={0.12} labels={o.labels} labelAt={[-0.22, 0, 0.05]} />
          {o.geometry && (
            <Part id="body.pelvis" pos={[-0.005, 0, 0.035]} rounded={{ args: [0.15, 0.3, 0.13], radius: 0.05 }} color={pal.seg} pal={pal} pick={pick} />
          )}
          <group position={[0, 0, 0.09]}>
            {glyph('joint.lumbar', q.lumbar_ext, -1, 'up', `lumbar_extension ${q.lumbar_ext.toFixed(2)} rad`)}
            <group rotation={[0, -q.lumbar_ext, 0]}>
              {ball('joint.lumbar', 0.03)}
              {o.geometry && (
                <>
                  <Part id="body.torso" geometry={g.torso} pos={[0, 0, 0.07]} scale={[0.68, 1.12, 1]} color={pal.seg} pal={pal} pick={pick} />
                  <Part id="body.head" geometry={g.neck} pos={[0.005, 0, SEG.trunk + 0.03]} color={pal.seg} pal={pal} pick={pick} />
                  <Part id="body.head" pos={[0.02, 0, SEG.trunk + 0.17]} scale={[1.08, 0.9, 1.15]} color={pal.seg} pal={pal} pick={pick}><sphereGeometry args={[SEG.head * 0.92, 32, 22]} /></Part>
                  {arm('r')}
                  {arm('l')}
                </>
              )}
            </group>
          </group>
        </group>
        {leg('r')}
        {leg('l')}
      </group>
    </group>
  );
}

/* ---------------- camera rig and canvas ---------------- */

/** Frames a half-extent box (horizontal, vertical, in metres) whatever the viewport aspect. */
function CameraRig({ target, extent, margin = 1 }: { target: [number, number, number]; extent: [number, number]; margin?: number }) {
  const { s } = useWB();
  const { camera, size } = useThree();
  const aspect = size.width / Math.max(1, size.height);
  const tanHalf = Math.tan(((camera as THREE.PerspectiveCamera).fov * Math.PI) / 360);
  const dist = Math.round(Math.max(extent[1] / tanHalf, extent[0] / (tanHalf * aspect)) * margin * 20) / 20;
  const ctl = useRef<any>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  useEffect(() => {
    const [tx, ty, tz] = target;
    const p: Record<string, [number, number, number]> = {
      iso: [tx + dist * 0.42, ty - dist * 0.85, tz + dist * 0.3],
      sagittal: [tx, ty - dist, tz],
      frontal: [tx + dist, ty, tz],
      top: [tx, ty - 0.001, tz + dist],
    };
    camera.position.set(...p[s.view.preset]);
    camera.up.set(0, 0, 1);
    camera.lookAt(tx, ty, tz);
    if (ctl.current) { ctl.current.target.set(tx, ty, tz); ctl.current.update(); }
  }, [s.view.nonce, s.study, dist]); // eslint-disable-line react-hooks/exhaustive-deps
  return <OrbitControls ref={ctl} makeDefault target={target} enableDamping={false} minDistance={0.4} maxDistance={8} />;
}

class GLBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div role="alert" className="flex h-full items-center justify-center p-6 text-center text-ink-2">WebGL is unavailable. The model tree, inspector, signals and table remain fully usable.</div>;
    return this.props.children;
  }
}

export function ModelScene({ ghostSeries, compact }: { ghostSeries?: string | null; compact?: boolean }) {
  const { s, d } = useWB();
  const pal = PALETTE[s.theme];
  const pick: Pick = { onPick: (id) => d({ type: 'select', id }), onHover: (id) => d({ type: 'hover', id }) };
  const isP = s.study === 'pendulum-qual';
  const i = idx(s.t);
  const theta = seriesById('series.rk4-1ms').theta[i];
  const ghost = ghostSeries ? seriesById(ghostSeries).theta[i] : null;
  const groundZ = isP ? -1.25 : -0.029;
  return (
    <GLBoundary>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ fov: 32, near: 0.01, far: 50, position: [2, -2.5, 1] }}
        onPointerMissed={(e) => { if (e.type === 'click') d({ type: 'select', id: 'model' }); }}
        gl={{ antialias: true, preserveDrawingBuffer: true }}
        aria-label="3D model viewport"
        data-testid="viewport"
      >
        <color attach="background" args={[pal.bg]} />
        <hemisphereLight args={['#ffffff', s.theme === 'dark' ? '#2a3038' : '#c9ced6', s.theme === 'dark' ? 0.7 : 1.0]} />
        <directionalLight position={[1.6, -2.4, 4]} intensity={s.theme === 'dark' ? 1.6 : 1.35} castShadow shadow-mapSize={[1024, 1024]} shadow-camera-left={-2} shadow-camera-right={2} shadow-camera-top={2} shadow-camera-bottom={-2} />
        <directionalLight position={[-3, 2, 1]} intensity={0.35} />
        <mesh position={[0, 0, groundZ - 0.001]} receiveShadow raycast={() => null}>
          <planeGeometry args={[8, 8]} />
          <shadowMaterial transparent opacity={pal.shadow} />
        </mesh>
        {s.overlays.grid && (
          <Grid rotation={[Math.PI / 2, 0, 0]} position={[0, 0, groundZ]} args={[6, 6]} cellSize={0.1} sectionSize={0.5} cellColor={pal.cell} sectionColor={pal.section} fadeDistance={7} infiniteGrid />
        )}
        {isP ? <Pendulum theta={theta} ghostTheta={ghost} pick={pick} compact={compact} pal={pal} /> : s.humanGeo === 'myosim' ? (
          <>
            <Part id="body.plate" pos={[0.06, 0, -0.014]} color={pal.plate} pal={pal} pick={pick}><boxGeometry args={[0.62, 0.52, 0.028]} /></Part>
            <MyoHuman pal={pal} />
          </>
        ) : <Human pick={pick} compact={compact} pal={pal} />}
        <CameraRig target={isP ? [0, 0, -0.52] : [0.04, 0, s.humanGeo === 'myosim' ? 0.76 : 0.88]} extent={isP ? [0.72, 0.78] : [0.55, s.humanGeo === 'myosim' ? 0.92 : 1.0]} margin={compact ? 1.15 : 1} />
        {!compact && (
          <GizmoHelper alignment="bottom-right" margin={[46, 46]}>
            <GizmoViewport scale={26} axisColors={['#d0453a', '#2f9a5f', '#3a6fc4']} labelColor="#ffffff" />
          </GizmoHelper>
        )}
      </Canvas>
    </GLBoundary>
  );
}
