# Verification — revision 0.1

READY_FOR_THREE_WEB_CONCEPT_REVIEW

Observed locally: `pnpm --dir design-prototypes build` passes TypeScript and Vite build. Three.js bundle produces a size advisory, not an error. `pnpm --dir design-prototypes test`: 1 passed (41.4 s), one shared journey loops through A, B and C. Actual Edge browser, rendered WebGL canvases, no backend connections.

| Observed journey | A | B | C |
|---|---|---|---|
| Direct route + persistent prototype banner | PASS | PASS | PASS |
| Configuration + seed edit | PASS | PASS | PASS |
| Refused preflight + restore | PASS | PASS | PASS |
| Cancel / failure / timeout / completion | PASS | PASS | PASS |
| Visible WebGL canvas + play/pause + scrub | PASS | PASS | PASS |
| Plot/table switch + selected time | PASS | PASS | PASS |
| Numerical / experimental / UQ views | PASS | PASS | PASS |
| Native evidence inspector | PASS | PASS | PASS |
| Desktop 1280×800 + wide 1440×900 capture | PASS | PASS | PASS |
| 390×844 document overflow check | PASS | PASS | PASS |

Screenshots: concept-{a,b,c}.png, concept-{a,b,c}-wide.png and concept-{a,b,c}-analysis.png. These are actual browser captures.

Implemented but not separately asserted in automated smoke: project dropdown, source/RunSpec details disclosure, unsupported engine and conceptual study refusal, invalid/offline/missing/partial/stale fixture states, camera pointer orbit/zoom, bob click selection, camera reset, reference toggle, canonical/assessment inspector tabs, keyboard-only full journey and forced WebGL-unavailable fallback. These use shared components/adapter across all concepts. Native selects/buttons/range controls support keyboard input; visible focus CSS is provided. No claims of formal accessibility conformance.

Production diff: only design-prototypes/ is added. No production application, CI, backend, accepted scientific fixtures or ADR edits. No simulator results generated. No deployment or Linear completion status mutation. Owner selection remains pending.
