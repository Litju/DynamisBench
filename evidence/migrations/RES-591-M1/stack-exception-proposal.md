# Draft authority proposal: preserve the VM rendering stack

**Status: proposed, not accepted.** This document asks the product/architecture owner to record a narrow exception for the owner-selected VM product. It does not edit or supersede an ADR, the locked stack, or scientific authority.

## Decision requested

Approve direct reuse of the VM's existing raw Three.js Laboratory renderer and custom SVG plots for the DynamisBench Workbench. Keep those implementations as the product stack for the integrated Laboratory; do not replace them with React Three Fiber v9 or Plotly during source migration.

## Exact scope

- Three.js: `apps/workbench/src/laboratory/stage/**`, `figure/**`, and the bundled anatomical figure decoder/skinning code.
- Custom SVG: `apps/workbench/src/laboratory/plot.tsx` and its existing series/timeline data bindings.
- Bundled runtime dependencies: the pinned `three` and `@types/three` versions already needed by the source; no network-loaded renderer or chart library.

The exception covers rendering and interaction implementation only. It does not approve new scientific quantities, numerical tolerances, simulation contracts, worker behavior, evidence status, or empirical claims. The 3D scene remains a presentation of the pinned model and recording data; plot values remain those published by the data contract.

## Basis and controls

The owner selected the Turn 4 + Turn 5 VM as the product baseline, and the renderer and plot source are transferred byte-for-byte except for the M1 route/safety adaptations listed in `source-map.csv`. Local Playwright evidence covers anatomical/scientific toggling, camera/view controls, synchronized playback and seeking, plots, responsive layout, and the two visual grounds. The renderer uses bundled assets and does not add remote origins or Tauri capabilities. The plotted table alternative and existing accessibility labels remain available.

The current accepted stack specifies React Three Fiber v9 and Plotly. This proposal requests only an explicit product-specific exception for the named Laboratory modules. It does not silently amend that standard. If accepted, the owner should record the decision in the governing product/architecture authority and link the approval to RES-591 before M1 is considered merge-ready. If declined, this branch remains a source-preserving implementation candidate for owner direction; no rewrite is authorized by this document.
