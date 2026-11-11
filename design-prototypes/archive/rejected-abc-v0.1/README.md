# DynamisBench — three interactive design prototypes

Source brief: Linear RES-575 and Integrated Scientific Workbench Blueprint v0.2. Prototype branch: prototype/res-575-three-concepts. Production application, backend, CI and scientific authority are untouched.

From the repository root, start with:

    pnpm --dir design-prototypes dev

First installation: `pnpm --dir design-prototypes install`. Requires Node 22+ and pnpm. Open http://localhost:5178/concepts, /concepts/a, /concepts/b or /concepts/c. Server uses port 5178 exclusively. Local browser app only, no deployment.

`pnpm --dir design-prototypes build` checks TypeScript and creates a Vite bundle. `pnpm --dir design-prototypes test` runs the targeted browser smoke journey using installed Microsoft Edge. Screenshots are retained in evidence/ at desktop and wide sizes.

## Revision map

- src/demo.tsx: shared deterministic fixture and mock lifecycle adapter
- src/visuals.tsx: R3F pendulum, orbit/zoom/reset/select, synchronized playback, SVG plot and accessible table
- src/panels.tsx: shared scientific configuration, preflight/run, assessment and evidence primitives
- src/concepts.tsx: three independently editable compositions and navigation systems
- src/style.css: concept visual systems and responsive layouts
- src/main.tsx: selector and direct routes

A starts with evidence and uses a source index, compact comparison and a secondary lab. B opens the model in a persistent scene with an explorer and contextual inspector; the viewport can expand. C starts with a question, uses a four-stage investigation and progressively reveals technical controls. Shared primitives preserve scientific semantics rather than dictating page composition.

## Scientific boundary

Physical configuration is transcribed from python/src/dynamisbench/adapters/mujoco/reference.py and assets/reference_pendulum.xml: mass 1 kg, COM 1 m, inertia 1.001 kg m², g 9.80665 m/s² along −z, initial angle π/6, initial velocity zero, timestep 0.001 s, duration 2 s. Display trajectory is a harmonic synthetic illustration sampled every 0.01 s, NOT MuJoCo output and NOT a nonlinear solution. Reference is the same synthetic angle plus 0.003 sin(2t). The illustrative tolerance is a UI example, never a scientific criterion. Geometry is schematic display geometry, not the native model's contact geometry. There are no seals, invented digests, native artifacts or validation badges.

Only study selection survives reload/concept links. Run and playback state persists between workspaces inside a concept, and resets on direct route reload. Configuration changes invalidate preflight. DEMO execution uses a timer with explicit failure/timeout injections and cancel. Restore fixture recovers incompatible/invalid/offline/stale/partial/missing states. Human movement is conceptual and refuses admission. Experimental validation and UQ are explicitly not assessed/unavailable.

## Review comparison

| Dimension | A: Instrument | B: Spatial IDE | C: Investigation |
|---|---|---|---|
| Entry point | Evidence and status dimensions | Model and 3D scene | Research question |
| Navigation | Persistent research index | Explorer and contextual inspector | Four-stage investigation map |
| Hierarchy | Dense quantitative panels | Scene, signals, properties | Narrative margin and active task |
| 3D | Secondary laboratory | Dominant persistent viewport | Experiment stage |
| Analysis | Dedicated evidence/comparison view | Inspector beside synchronized scene | Comparison stage in argument |
| Evidence | Global inspector, status strip | Global inspector and console | Global inspector and conclusion trail |
| Responsive | Index scrolls, panels stack | Explorer wraps, properties stack | Stages wrap, narrative stacks |
| Tradeoff | More workspace switching for spatial tasks | More simultaneous information, narrower inspector | More steps between deep controls |
| Complexity | Low composition complexity | Highest layout and WebGL density | Moderate stage and disclosure logic |

All share project/study/scenario/realization/SUT/environment, RunSpec, capability refusal, mock lifecycle, 3D and signals, numerical illustration, experimental/UQ limitations and native/canonical/assessment provenance. Tests navigate each representative journey and capture actual application views. Keyboard uses native controls, visible focus, slider arrows and a table selection alternative. Pointer orbit/zoom supplements accessible time/angle state and reset. WebGL failure has a text fallback; fallback rendering is implemented but not forced in the smoke journey.

Revision 0.1: implemented all three concepts from the approved brief; no preferred concept selected. Stop here for owner selection or combination.
