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

## CI authority (ADR-025)

Portable software qualification is authoritative on ephemeral GitHub-hosted runners.
`.github/workflows/quality.yml` is the only qualification workflow, and every gate
runs on both explicit, pinned images:

| platform role | image |
| --- | --- |
| Windows x86-64 product/runtime | `windows-2025` |
| Linux x86-64 core/portability/determinism | `ubuntu-24.04` |

A hosted result on these images satisfies a qualification, milestone, release,
cross-platform determinism, or scientific-evidence gate. There is no second,
"non-authoritative" hosted workflow, because the only reason one existed was that
the authoritative workflow could not run fork code.

* Pin the image. `-latest` is rejected: a result that cannot be tied to a named
  runner image cannot be interpreted later. `python/tests/test_workflow_authority.py`
  resolves each job's matrix and admits only the two approved images.
* Do not route a portable gate to `self-hosted`. A self-hosted runner is not a
  higher-authority tier; it is introduced only when a specific claim genuinely
  needs hardware, an accelerator, a proprietary or simulator installation, a
  licensed asset, or an exact declared execution host — and that issue must say so.
  An unavailable special-purpose runner blocks only that claim; it must never leave
  unrelated portable software unfinished, and it must never grow a hosted or
  self-hosted fallback that turns a blocked gate green.
* Fork pull requests may run this matrix. The hosted runners are ephemeral and
  isolated, which is exactly why that is acceptable, so no
  `pull_request.head.repo.full_name` trust gate belongs in a portable job. The
  price is that the token stays `contents: read`, no secret is referenced, and
  checkout must not persist credentials into a tree that fork code now controls.
* `pull_request_target` must not be used here. It checks out untrusted PR head code
  with a privileged token.
* Runner images, caches, workspaces, and toolchains are mutable infrastructure, not
  scientific authority. The `platform-identity` gate publishes the runner image,
  OS/architecture, commit, and resolved Python/uv/Node/pnpm/Rust/Cargo versions as a
  run artifact, and it is the only gate that publishes one.

`python/tests/test_workflow_authority.py` enforces these rules as a gate, so an
unapproved image, a dropped platform, a reintroduced `self-hosted` route, a widened
permission, a tolerated failure, or a `pull_request_target` fails CI rather than
waiting for review.

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
