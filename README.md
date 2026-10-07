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
apps/workbench/  React 19 + TypeScript + Vite 8 workbench placeholder
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
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
Pop-Location

# Frontend toolchain and quality gates
corepack enable
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run test
pnpm run build

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
| `python` | locked `uv sync`, Ruff lint + format, Pyright, pytest with the `ci` Hypothesis profile |
| `frontend` | locked `pnpm install`, `tsc --noEmit`, Vitest, Vite build |
| `desktop` | Rust toolchain, Tauri Linux system deps, workbench build, `cargo build --locked` |

Hosted runs are authoritative for portable software claims: repository code and
deterministic behaviour, canonical identity, CLI/API/frontend behaviour, and desktop
compilation. A claim that genuinely needs hardware, an accelerator, a proprietary or
simulator installation, or an exact declared host requires a purpose-built runner and
says so in its own issue; an unavailable one blocks only that claim.

## Scope of the current baseline

The scientific core — canonical identity, validated domain specs, deterministic
`StudyPlan`/`RunSpec` compilation, workspace, and sealed evidence — and the local
application boundary (`/api/v1` plus the session-secured loopback sidecar) exist and
are qualified. Explicitly not present yet: simulator libraries, numerical simulation,
execution environments, database or control-plane services, product UI, and packaging.
