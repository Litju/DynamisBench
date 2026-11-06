# M1 compatibility modifications

Base: protected main a24152305b60b7a7a6605666b95ba56149a4bc62. Candidate-to-integrated hunks are in compatibility-diffs.patch; source/main/after SHA-256 values and exact reasons are in source-map.csv.

## VM files modified at the application boundary

| Repository path | Reason |
|---|---|
| .github/workflows/quality.yml | Add a focused columnar cold-import and sidecar-start regression step inside the existing Python job; keep the eight required contexts and permissions unchanged. |
| README.md | Document the M1 read-only VM route, true availability limits, dataset claim ceiling, and deferred execution qualification. |
| apps/workbench/e2e/laboratory.spec.ts | Add real-sidecar E2E assertion that the read-only evidence claim is visible with the original Laboratory route. |
| apps/workbench/e2e/production-design.spec.ts | Assert the M1 workspace-unavailable state, no /studies or /runs requests, and capture the workspace-bound Study folio. |
| apps/workbench/src/laboratory/data.tsx | Disable workspace run queries while the M1 capability constant is false; packaged diagnostic data remains readable. |
| apps/workbench/src/laboratory/folio-record.tsx | Replace the M2 worker reproduction command and unbounded provenance claim with a manifest-only, read-only statement because M1 does not integrate that worker. |
| apps/workbench/src/laboratory/folio-study.tsx | Keep the original Study workflow source but gate it behind the false M1 capability and show an honest unavailable state. |
| apps/workbench/src/laboratory/laboratory-page.test.tsx | Assert the unavailable workspace workflow and no live API calls, plus the read-only evidence claim. |
| apps/workbench/src/workbench/laboratory.tsx | Bridge the preserved workspace source-inspection shell to the original VM Laboratory route and report workspace-run unavailability; no fake run/evidence. |
| pnpm-lock.yaml | Resolve and lock the exact VM Three.js, type, and bundled EB Garamond/IBM Plex dependencies. |
| python/pyproject.toml | Declare NumPy explicitly at runtime for the locked NumPy/PyArrow Arrow stack used by the Laboratory API. |
| python/src/dynamisbench/api/app.py | Mount only the GET-only packaged Laboratory router under the existing API v1 composition and security boundary. |
| python/src/dynamisbench/api/server.py | Preload the columnar stack on the sidecar main thread before binding/readiness; fail startup closed on import failure. |
| python/tests/api/test_namespace.py | Add only the five read-only Laboratory GET routes to the repository's closed route allowlist. |
| python/tests/api/test_public_boundary.py | Add the static Laboratory publisher and typed read models to the API boundary checks; preserve the closed route/module contract. |
| python/tests/api/test_sidecar_cold_start.py | Keep M1 cold-start/concurrent diagnostic reads; dynamically skip only sealed-run tests requiring the deferred M2 pipeline. |
| python/tests/laboratory/test_figure.py | Keep the figure integrity/geometry checks; dynamically skip only the M2 figure-regeneration tool when it is not integrated. |
| python/tests/laboratory/test_laboratory.py | Keep packaged dataset/read-only API checks; skip only tests requiring M2 squat anthropometry/criteria authority. |
| python/tests/transport/test_columnar.py | Run the lazy-import composition check against modules present in M1; retain concurrency, failure, and import-boundary checks. |
| python/uv.lock | Lock the direct runtime NumPy dependency to match pyproject.toml. |

## M1-only additions

| Repository path | Reason |
|---|---|
| apps/workbench/src/laboratory/m1-capabilities.ts | New frozen capability flag is false in M1 and provides the exact availability message; workspace study/run calls remain unreachable until the production execution authority is accepted. |
| python/tests/api/test_laboratory_routes.py | New route test covers existing session authentication, pinned diagnostic responses, payload bounds, read-only verbs, and 404 for workspace study/run endpoints. |
