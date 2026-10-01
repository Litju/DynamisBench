# Contributing to DynamisBench

## Authority first

Linear project **P-RES-35 — DynamisBench** holds the architecture, the ADR register,
and the scientific methodology. Those documents are the authority. This repository
implements them; it does not restate or redefine them.

Never create a local architecture, ADR, or specification document that competes with
the Linear authority. Link to the authority instead.

## Contradictions stop the work

If an issue cannot be completed without violating an accepted ADR or specification:

1. stop that implementation path;
2. report the concrete conflict;
3. propose an ADR amendment or supersession;
4. migrate evidence/schema/runtime only after the authority is updated.

Coding agents do not author architecture authority.

## Commit discipline

* One independently completed and qualified achievement per commit.
* Do not combine unrelated Linear issues into one commit.
* Do not mark an issue Done before its qualification evidence exists.
* A software-test PASS is never scientific validation.

## Platform discipline (ADR-023)

Windows x86-64 owns the working tree. Do not bootstrap or run the normal workflow
through WSL, `/mnt/c`, or other Linux tooling against this checkout.

Do not share `.venv`, `node_modules`, Cargo target state, or simulator environments
between Windows and Linux. Linux CI resolves its own platform environment.

## Quality gates

A change is qualified only when, on both Windows and Linux:

```powershell
Push-Location python; uv sync --frozen; uv run ruff check .; uv run ruff format --check .; uv run pyright; uv run pytest; Pop-Location
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run test
pnpm run build
```

Touching `apps/desktop/src-tauri` additionally requires
`cargo build --locked --manifest-path apps/desktop/src-tauri/Cargo.toml`.

Lockfiles (`python/uv.lock`, `pnpm-lock.yaml`,
`apps/desktop/src-tauri/Cargo.lock`) are committed and must stay in sync with the
manifests.
