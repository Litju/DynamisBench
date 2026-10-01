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

## CI authority (ADR-024)

Full qualification is authoritative only on dedicated self-hosted runners.
`.github/workflows/quality.yml` routes every gate by explicit labels:

| platform role | labels |
| --- | --- |
| Windows x86-64 product/runtime | `[self-hosted, Windows, X64, dynamisbench]` |
| Linux x86-64 core/portability/determinism | `[self-hosted, Linux, X64, dynamisbench]` |

The `dynamisbench` label is what keeps a qualification job off an unrelated project's
self-hosted runner. Do not route to a bare `self-hosted` pool.

* `windows-latest` / `ubuntu-latest` may appear only in `smoke-hosted.yml`, whose
  workflow and job names are marked `NON-AUTHORITATIVE`. A hosted result never
  satisfies a qualification, milestone, release, cross-platform determinism, or
  scientific-evidence gate, whatever its conclusion.
* If a required self-hosted runner is offline, its gate stays queued. That is the
  correct outcome. Do not add a hosted fallback to turn a blocked gate green.
* Only trusted refs reach the persistent runners: pushes to `main`, manual
  `workflow_dispatch`, and pull requests whose head repository is this repository.
  A fork pull request runs the hosted smoke workflow and nothing else.
* `pull_request_target` must not be used here. It checks out untrusted PR head code
  with a privileged token, which is exactly how a public repository's self-hosted
  runners get compromised.
* Runner credentials, workspaces, caches, and toolchains are mutable infrastructure,
  not scientific authority. The `platform-identity` gate publishes the runner
  OS/architecture and toolchain identity as a run artifact instead of trusting
  runner-local state.

`python/tests/test_workflow_authority.py` enforces these rules as a gate, so a
hosted fallback, a dropped label, a removed trust condition, or a reintroduced
`pull_request_target` fails CI rather than waiting for review.

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
