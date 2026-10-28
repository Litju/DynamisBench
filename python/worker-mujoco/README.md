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
