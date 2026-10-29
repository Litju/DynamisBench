# DynamisBench

DynamisBench is a local-first scientific workbench for verification, validation,
uncertainty quantification (VVUQ), benchmarking, and reproducible comparison of
computational human-movement models, simulator realizations, controllers, and
complete systems.

## Authority

This repository is **not** the architectural authority. The living authority is the
Linear project **P-RES-35 — DynamisBench**:

* Architecture & System Design
* Architecture Decision Register (ADR-001 … ADR-025)
* Locked Tech Stack & Product Runtime
* Engine, SUT & Execution Contracts
* Evidence & Provenance Model
* VVUQ Workflow & Scientific Lifecycle
* Roadmap, Issue Decomposition & Delivery Governance
* Methodological References & Research Basis

Implementation follows that authority. Never treat README text, code comments, or
generated documents as a substitute for it. When implementation contradicts an
accepted decision, stop and amend the decision explicitly — see
[CONTRIBUTING.md](CONTRIBUTING.md).

Repository identity: `Litju/DynamisBench`. The local checkout directory name
(`DynamisSimBench`) is not the project name.

## Platform

Windows x86-64 is the authoritative development, desktop-product, and primary local
execution platform (ADR-023, ADR-012). Linux is a required portability and CI
qualification target.

Windows and Linux environments are never shared: `.venv`, `node_modules`, Cargo
build artifacts, and simulator environments must not be reused across the two.

## Repository layout

```text
python/          Python distribution `dynamisbench`, CLI `dbench`, quality config
  src/dynamisbench/
    domain/spec  planning  execution  adapters
    normalization  evaluation  evidence  query  api
  tests/
apps/workbench/  React 19 + TypeScript + Vite 8 workbench shell (session, typed /api/v1 client, routing)
apps/desktop/    Tauri 2 thin desktop shell (Rust)
.github/         CI quality gates on Windows and Linux
```

Python module boundaries mirror the bounded modules of the architecture authority.
They are created empty in DB-1.1 (RES-227); each carries a docstring stating what it
will own. Scientific implementation begins in DB-1.2 (RES-228).

## Bootstrap on Windows (PowerShell)

```powershell
# Python 3.12 toolchain and locked virtual environment
uv python install 3.12
Push-Location python
uv sync --frozen
Pop-Location

# Python quality gates
Push-Location python
uv sync --frozen
# The MuJoCo adapter runs in a separate locked scientific environment (ADR-018).
uv sync --frozen --project worker-mujoco
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pyright -p pyrightconfig.worker.json
$env:DYNAMISBENCH_MUJOCO_PYTHON = (Resolve-Path .\worker-mujoco\.venv\Scripts\python.exe)
$env:DYNAMISBENCH_REQUIRE_MUJOCO = "1"
uv run pytest
Pop-Location

# Frontend toolchain and quality gates
corepack enable
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run test
pnpm run build

# Browser-grade end-to-end gate (production routes, real secured sidecar)
pnpm --filter @dynamisbench/workbench exec playwright install chromium
pnpm --filter @dynamisbench/workbench run test:e2e

# Tauri desktop shell (thin shell only; no sidecar, no product UI yet)
cargo build --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
```

`pnpm --filter @dynamisbench/desktop run dev` starts the desktop shell against the
Vite dev server. Bundling and packaging are deferred to the packaging gate that the
locked tech stack schedules before v0.1.

## CI

`.github/workflows/quality.yml` is the only qualification workflow (ADR-025). Every
gate runs on both explicit GitHub-hosted images, `windows-2025` and `ubuntu-24.04`:

| Job | Gate |
| --- | --- |
| `platform-identity` | runner image, OS/architecture, commit, and resolved Python/uv/Node/pnpm/Rust/Cargo versions, published as a run artifact |
| `python` | locked `uv sync`, isolated MuJoCo worker environment, Ruff lint + format, both Pyright configurations, pytest with the `ci` Hypothesis profile and the real MuJoCo adapter regressions |
| `frontend` | locked `pnpm install`, `tsc --noEmit`, Vitest, Vite build, pinned Chromium Playwright against a real secured sidecar |
| `desktop` | Rust toolchain, Tauri Linux system deps, workbench build, `cargo build --locked` |

Those four jobs on both images are the eight required ADR-025 qualification gates. The
`python` job additionally publishes the Windows and Linux MuJoCo numerical qualification
receipts, and the separate `mujoco-receipt-comparison` job compares them. That comparison is
deliberately not one of the eight gates and cannot weaken them.

Hosted runs are authoritative for portable software claims: repository code and
deterministic behaviour, canonical identity, CLI/API/frontend behaviour, and desktop
compilation. A claim that genuinely needs hardware, an accelerator, a proprietary or
simulator installation, or an exact declared host requires a purpose-built runner and
says so in its own issue; an unavailable one blocks only that claim.

## Scope of the current baseline

The scientific core — canonical identity, validated domain specs, deterministic
`StudyPlan`/`RunSpec` compilation, workspace, and sealed evidence — plus the
engine-independent execution boundary (versioned worker protocol, fail-closed capability
preflight, isolated subprocess supervision with bounded IPC/logging, timeout, cancellation
and reaping) and the local application boundary (`/api/v1` plus the session-secured
loopback sidecar) exist and are qualified, as does the workbench foundation that consumes
them (volatile desktop session boundary, typed `/api/v1` client, TanStack Query server
state, code-based routes).

RES-550 adds the first real simulator execution: a fixed, self-contained MuJoCo planar
pendulum reference adapter in `python/src/dynamisbench/adapters/mujoco`, run only in the
separate locked environment defined by `python/worker-mujoco`. It advertises only
`forward_dynamics`, is admitted through the accepted `RunSpec → preflight → supervisor`
boundary, and emits a bounded native diagnostic that is not sealed native evidence.
Execution-time engine-version admission supports exact, not-equal and ordered Semantic
Versioning clauses; the `compatible` comparator has no accepted authority definition and is
refused rather than guessed.

The worker is bound to the **exact semantics** of the reference experiment, not only its
identifiers and versions. The reviewed benchmark, scenario, realization, system-under-test
and platform-environment semantic digests are pinned in
`python/src/dynamisbench/adapters/mujoco/reference.py`; their canonical source is
`reference_case.py`, and `tools/mujoco_reference_authority.py --check` reproduces them. The
worker compares every request against those constants before it loads or advances physics, so
a definition that keeps its ID and version but changes duration, initial conditions, solver
configuration, asset digest, SUT or environment content is refused. The accepted seed, factor
target and value, outcomes and capabilities are checked explicitly too.

The adapter implementation identity also binds the **installed dependency closure**. The
reviewed `worker-mujoco/uv.lock` hash and exact package versions are pinned in
`dependencies.py`; the worker verifies the installed distribution versions at runtime and
folds the closure into the existing `implementation_digest` (no new protocol field). The
lockfile hash is attested by the repository/CI, not proven by the runtime check, and wheel
file bytes are not authenticated — see that module for the exact limitation.

`tools/mujoco_qualification_receipt.py` emits one bounded CI qualification receipt per
platform. A receipt is a numerical solution-verification artifact, **not** `native/`,
`canonical/`, `assessment.json` or sealed scientific evidence. `tools/mujoco_receipt_compare.py`
independently checks identity consistency, numerical tolerance compliance and unexpected
platform divergence; it does not require bitwise cross-platform equality.

Explicitly not present yet: arbitrary model/asset materialization for a generic MuJoCo
realization, native→canonical normalization, `assessment.json`, scientific benchmark
acceptance or model validation, a production simulation UI/run command, OpenSim, packaging,
and the scientific workbench surfaces (explorer, artifact inspector, charts, 3D playback).
