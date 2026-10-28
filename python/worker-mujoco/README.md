# Isolated MuJoCo execution environment

This directory defines the **scientific execution environment** for the RES-550 reference
adapter. It is separate from the application runtime (`python/.venv`) on purpose (ADR-018):
the application API, planner, scientific domain and desktop shell never install or import
MuJoCo.

## Provision

From `python/`:

```text
uv sync --frozen --project worker-mujoco
```

The resulting interpreter is one of:

```text
worker-mujoco/.venv/Scripts/python.exe   # Windows x86-64
worker-mujoco/.venv/bin/python           # Linux x86-64
```

`uv.lock` is the authoritative dependency closure. `mujoco` is exact-pinned in
`pyproject.toml`; the lock file pins NumPy, GLFW and every other transitive package.

The reviewed lockfile hash and the exact `(normalised name, version)` closure are pinned in
`src/dynamisbench/adapters/mujoco/dependencies.py`. On every worker start, the worker reads
the *installed* distribution versions with `importlib.metadata` and refuses a missing, extra
or differently versioned distribution. That check is folded into the existing adapter
`implementation_digest`; it does not add a worker-protocol field. The pinned lockfile hash is
an attestation by the repository and CI, not something the worker can prove from inside its
own environment, and installed wheel file bytes are not authenticated by this check. Regenerate
the pins with `uv run python tools/mujoco_dependency_closure.py --check` from `python/`.

## Fixed worker command

The supervisor starts exactly this vector, with no shell and no per-run program selection:

```text
<worker-python> -I -m dynamisbench.adapters.mujoco
```

`-I` is Python isolated mode: the current directory and user site-packages cannot shadow
imports. The worker's working directory is a supervisor-owned scratch directory, and its
environment is rebuilt by `dynamisbench.execution.environment`.

## Identity qualification interface

The only accepted argument is `--identity`:

```text
<worker-python> -I -m dynamisbench.adapters.mujoco --identity
```

It loads the reviewed model with the real engine, computes the adapter implementation
identity, and writes one canonical JSON object to stdout. The output includes the
`implementation_digest` and the source/model manifest. This is an operational qualification
interface, not part of the worker wire protocol and not reachable from a `RunSpec`.

The production command has **no arguments**. The worker refuses every other argument vector.

Before the production request reaches physics, the worker compares the resolved benchmark,
scenario, realization, system-under-test and environment semantic digests with the reviewed
pins in `reference.py`. Identifiers and versions alone are not sufficient authority: the same
name can be re-pointed at different content. The accepted seed, gravity factor and value,
outcomes and capability sets are checked explicitly as well. A mismatch is a protocol-valid
`failed` response, no MuJoCo physics step is taken, and the supervisor cannot seal it as a
successful execution.

## What is installed

| Component | Constraint |
| --- | --- |
| CPython | `>=3.12,<3.13` (the repository pins `3.12.13` via `.python-version`) |
| MuJoCo | `==3.17.0` |
| `dynamisbench` | editable path dependency on `..` |

The worker's diagnostic records the actual `mujoco.__version__`, Python version and platform
tag; the adapter refuses to run when they do not match the request's adapter identity.

## Model

The reviewed model is
`src/dynamisbench/adapters/mujoco/assets/reference_pendulum.xml` in the main distribution.
It is self-contained (no meshes, textures, includes or absolute paths), so the worker loads
it from package bytes with `mujoco.MjModel.from_xml_string`. Its raw-byte SHA-256 is
`eac679a723ccfebb48ea5ee40692fa6ee38f965772b484b94b827be6b9dbfdfd`.

## Scope limit

This environment qualifies one fixed reference adapter, not arbitrary MuJoCo models. The
accepted RES-549 worker request carries resolved identities, not definition content or asset
bytes; arbitrary model materialization therefore requires a separate, explicitly authorized
evidence/asset-materialization gate.
