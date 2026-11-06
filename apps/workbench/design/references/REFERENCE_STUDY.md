# Visual reference study: professional scientific software and Renaissance scientific plates

This study records what DynamisBench's workbench design learned from established scientific
software and from Renaissance scientific illustration, and what it deliberately does
differently. The companion plate is [`reference-study.svg`](reference-study.svg).

**How the references were collected.** The build environment for this work had no web access
beyond package registries, so no screenshots of the reference products were captured and none
are reproduced. The layouts on the plate are *abstract schematics drawn for this study* from
working knowledge of each product's published interaction paradigm: region structure, the flow
of selection and time, and the place of results. No logo, artwork, icon or screen of any
product is copied. Renaissance material is public domain and is used only as a source of
*motifs* (measurement devices, lettered plates, pigments), never reproduced.

## 1. Professional scientific software

| Reference | Paradigm (as studied) | What it does well | Where it falls short for DynamisBench | Codex decision |
| --- | --- | --- | --- | --- |
| **OpenSim** (musculoskeletal modelling) | Navigator tree of the model; 3D view with the model; coordinate sliders; a separate plotter window; motions loaded and played back. | The model is a *navigable tree* of bodies, joints, forces; coordinates are first-class; motion playback is central. | Plotter and viewer are separate windows with separate clocks; provenance of a motion file is invisible; results and the model they came from are loosely linked. | Keep the model tree and coordinate readouts. Put viewer, plots and inspector on **one clock**. Put the recording's identity (model SHA, trajectory hash) on every view. |
| **Creo / CAD "creator" tools** (parametric modelling) | Model tree left; large graphics area; contextual ribbon; properties on selection; view cube and saved views. | Exemplary 3D navigation: view cube, named views, section/visibility control, selection highlight synchronised with the tree. | Ribbon density and modal commands suit authoring, not reading a recording; time is absent. | Adopt named views (Sagittal, Frontal, Oblique, Plan), an orientation instrument, tree-viewport selection sync. Reject the ribbon: a read-only lab needs few commands. |
| **COMSOL Multiphysics** (model builder) | Model Builder tree (definitions, physics, mesh, study, results) left; Settings pane for the selected node; Graphics; Messages/Progress/Log at the bottom. | The tree *is* the scientific workflow (definitions → study → results), and each node has one settings page. Results are nodes, not windows. | Very text-dense settings pages; evidence of correctness (convergence, checks) is buried in logs. | Adopt the workflow spine as the top-level folios: **I Laboratory · II Model Atlas · III Analysis · IV Evidence**. Promote correctness checks from the log to a first-class folio. |
| **ParaView** (scientific visualisation) | Pipeline browser (sources → filters); Properties; multiple linked render/plot views; an animation/time toolbar; colour maps with legends. | Time is a global toolbar that drives every view; views are linked; colour maps are explicit and legended. | Pipeline abstraction is general-purpose and heavy; the domain (a body, a lift) is invisible. | Adopt the **global time toolbar** and linked views, explicit legends and units on every encoding. Replace the pipeline with domain layers (skeleton, forces, CoM, support polygon, paths). |
| **Simulink** (block diagrams, scopes) | Signal-flow diagram; scopes showing signals over time with a cursor; data inspector to compare runs. | Run comparison (Data Inspector) and signal-level inspection with synchronised cursors. | The diagram view is irrelevant to a recorded movement; scopes are separate windows. | Adopt **run comparison** (nominal vs ablations vs timestep study) and cursor-synchronised scopes, docked under the stage. |

Cross-cutting lessons adopted:

1. **One clock.** Playback time is global state; the 3D stage, every plot, the inspector, the
   plantar pressure map and the phase strip are projections of it.
2. **Selection is global.** Selecting a joint in the tree, the stage or a plot selects it
   everywhere.
3. **Provenance is ambient.** A thin colophon ribbon states what is being looked at (recording,
   model, engine, hashes) and what it is *not* (not sealed evidence).
4. **Honest absence.** What the application cannot do (run a new simulation from the UI) is
   shown as *not connected, and why*, never hidden or faked.

## 2. Renaissance scientific illustration (public-domain motifs)

| Source tradition | Motif | Translation into a measuring device |
| --- | --- | --- |
| Leonardo's anatomical and mechanical notebooks | Sanguine (red chalk) and iron-gall ink; marginal annotations next to the figure | **Sanguine** is the kinetics colour (forces, moments); **marginalia** are the stage's live annotations (joint angles beside the joints). |
| Vesalius, *De humani corporis fabrica* (1543) | Lettered figures with a legend | The **Model Atlas** labels segments with letters A-P and a legend table of de Leva inertial properties. |
| Vitruvian proportion (circle and square) | Body inscribed in circle and square | The **floor instrument**: concentric rings with graduated ticks under the athlete, centred on the mid-foot balance point, with the square of the stance. |
| Dürer's proportion studies | Measured grids and scales | Hairline **rules and scales** on plots and the stage; a 4 px baseline and an 8 px grid. |
| Armillary spheres and astrolabes | Graduated rings, brass | The **orientation instrument** (view gizmo) is a ring with graduations; **gold leaf** marks the centre of mass and the barbell. |
| Pacioli, *Summa de arithmetica* (1494), double-entry bookkeeping | A ledger that must balance | The **work-energy ledger**: actuator work, damping dissipation and mechanical-energy change per phase, with the residual that must close. |
| Manuscript layout (folios, rubrics, colophon) | Roman-numeral folios, red rubrics, a colophon stating origin | Folios **I-IV** for the four contexts; small-caps rubrics for section heads; the **colophon ribbon** for provenance. |

What Codex avoids: pastiche (faux parchment textures, drop caps, calligraphic script in data,
sepia photographs). The Renaissance is present in *proportion, pigment, typography and
measurement*; the instrument remains a modern, dense, legible scientific tool.
