import { useMemo } from 'react';
import { LCMJ20 } from './authority';
import { ENTITIES, HUMAN_ENTITIES, type Entity, type Prop } from './models';
import { MYO, useMyoModel, type MBody, type MyoModel } from './myosim';
import { STUDIES, useWB } from '../state';

const f3 = (v: { x: number; y: number; z: number }) => `${+v.x.toFixed(4)}, ${+v.y.toFixed(4)}, ${+v.z.toFixed(4)}`;
const deg = (r: number) => `${(r * 180 / Math.PI).toFixed(1)}°`;
const COUPLED = /translation|rotation2|rotation3|beta/;

/** Fixture-declared items that stay meaningful whichever geometry is shown. */
const FIXTURE_IDS = new Set(['g.hframes', 'frame.world', 'body.plate', 'g.hcontact', 'contact.foot_plate', 'g.hact', 'g.hsens', 'sensor.foot', 'solver', 'g.hquant', 'q.grf', 'q.height', 'q.knee']);

export function myoEntities(m: MyoModel): Entity[] {
  const out: Entity[] = [
    { id: 'model', kind: 'model', label: 'MyoSim MyoLegs + MyoTorso', sub: `${m.bodies.size} bodies · ${m.joints.size} joints`, tag: 'EXTERNAL',
      summary: 'Anatomical reference geometry and kinematic tree from MyoSim (MuJoCo port of Rajagopal 2016). Shown to give the target human-movement UX real structure. It is not the LCMJ20 realization, not qualified and not executed; no human physics result exists.',
      props: [
        { name: 'Source', value: `${MYO.repo} @ ${MYO.commit.slice(0, 10)}`, tag: 'EXTERNAL' },
        { name: 'Licence', value: MYO.license, tag: 'EXTERNAL' },
        { name: 'Files', value: 'myolegs_chain.xml, myotorso_chain.xml, 46 STL meshes (unmodified)', tag: 'EXTERNAL' },
        { name: 'Not shown', value: 'muscles, tendons, wrapping surfaces, contacts, head and arms', tag: 'DESIGN_ONLY' },
        { name: 'Coupled knee/patella DOFs', value: 'held at 0 — equality constraints are not evaluated', tag: 'DESIGN_ONLY', note: 'MyoSim reports ~1 cm marker differences below the knee vs OpenSim even when coupled.' },
        { name: 'LCMJ20 realization asset', value: `${LCMJ20.realization.asset.path} (placeholder digest)`, tag: 'FIXTURE' },
      ] },
    { id: 'g.mbodies', kind: 'group', label: 'Bodies (kinematic tree)', parent: 'model', tag: 'EXTERNAL' },
  ];
  const walk = (b: MBody, parentId: string) => {
    const id = `mbody.${b.name}`;
    const props: Prop[] = [
      { name: 'Parent body', value: b.parent ?? 'world (display root)', tag: 'EXTERNAL' },
      { name: 'Mass', value: b.mass != null && Number.isFinite(b.mass) ? String(b.mass) : 'not declared', unit: 'kg', tag: 'EXTERNAL' },
      { name: 'COM (body frame)', value: b.com ? f3(b.com) : 'not declared', unit: 'm', tag: 'EXTERNAL' },
      { name: 'Origin in parent', value: f3(b.pos), unit: 'm', tag: 'EXTERNAL' },
      { name: 'Meshes', value: b.geoms.map((g) => g.file).join(', ') || 'none', tag: 'EXTERNAL' },
      { name: 'Source file', value: b.source === 'myolegs' ? 'myolegs_chain.xml' : 'myotorso_chain.xml', tag: 'EXTERNAL' },
    ];
    out.push({ id, kind: 'body', label: b.name, sub: b.mass != null && Number.isFinite(b.mass) ? `${b.mass} kg` : b.source === 'myotorso' ? 'torso' : '', parent: parentId, tag: 'EXTERNAL', pickable: true, props,
      summary: `Rigid body from ${b.source === 'myolegs' ? 'MyoLegs' : 'MyoTorso'}. Inertial values are the reference model's, not a DynamisBench subject.`,
      signals: b.name.startsWith('tibia_r') ? ['knee_r'] : undefined });
    for (const j of b.joints) {
      const coupled = COUPLED.test(j.name);
      out.push({
        id: `mjoint.${j.name}`, kind: 'joint', label: j.name, sub: `${j.type}${coupled ? ' · coupled' : ''}`, parent: id, tag: 'EXTERNAL', pickable: true,
        summary: coupled
          ? 'Dependent DOF driven by an equality constraint in the full MuJoCo model. The prototype does not evaluate constraints, so it is held at 0.'
          : `${j.type === 'hinge' ? 'Hinge' : 'Slide'} joint of ${b.name}. Axis and range are the reference model's; posing it is design inspection, not simulation.`,
        props: [
          { name: 'Type', value: j.type, tag: 'EXTERNAL' },
          { name: 'Axis (body frame)', value: f3(j.axis), tag: 'EXTERNAL' },
          { name: 'Range', value: j.range ? `${+j.range[0].toFixed(4)} … ${+j.range[1].toFixed(4)}${j.type === 'hinge' ? `  (${deg(j.range[0])} … ${deg(j.range[1])})` : ''}` : 'unlimited', unit: j.type === 'hinge' ? 'rad' : 'm', tag: 'EXTERNAL' },
          { name: 'Pose value', value: '', unit: j.type === 'hinge' ? 'rad' : 'm', tag: 'DESIGN_ONLY', live: `myo:${j.name}` },
          { name: 'Coupling', value: coupled ? 'equality-constrained (not evaluated)' : 'independent', tag: coupled ? 'DESIGN_ONLY' : 'EXTERNAL' },
        ],
        signals: j.name === 'knee_angle_r' ? ['knee_r'] : undefined,
      });
    }
    for (const c of b.children) walk(c, id);
  };
  for (const r of m.roots) walk(r, 'g.mbodies');
  return [...out, ...HUMAN_ENTITIES.filter((e) => FIXTURE_IDS.has(e.id)).map((e) => (e.id === 'body.plate' ? { ...e, parent: 'model' } : e))];
}

/** Entities for the current study and chosen geometry. */
export function useModelEntities(): { entities: Entity[]; loading: boolean; error: string | null } {
  const { s } = useWB();
  const { model, error } = useMyoModel();
  const st = STUDIES[s.study];
  return useMemo(() => {
    if (st.model === 'lcmj-schematic' && s.humanGeo === 'myosim') {
      if (model) return { entities: myoEntities(model), loading: false, error: null };
      return { entities: ENTITIES['lcmj-schematic'], loading: !error, error };
    }
    return { entities: ENTITIES[st.model], loading: false, error: null };
  }, [st.model, s.humanGeo, model, error]);
}
