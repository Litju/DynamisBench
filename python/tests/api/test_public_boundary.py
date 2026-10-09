"""Structural gates on the application API package's boundaries, and its OpenAPI contract.

The claim DB-2.1 makes is that FastAPI is an application adapter and never authority
(ADR-016), that it imports no simulator (ADR-001) and executes no simulation (ADR-017),
and that it serves one versioned namespace a client can generate against. Every one of
those decays silently. An endpoint that needs one extra fact will import the layer that
owns it; a router that grows a convenience will reach for ``pathlib``; a second version
will appear as a literal prefix in a decorator. Nothing functional notices, because the
response is still correct. So these checks sit on the import graph, on the source text and
on a measured import, where an indirect call cannot hide.

What is checked:

* **A closed module set, in three groups.** Five boundary modules, reachable from
  ``import dynamisbench.api``, the two session modules DB-2.2/DB-2.3 add and which are
  reachable only by importing them directly, and the two workspace-reading modules
  DB-2.4 (RES-377) adds. A tenth is a reviewed change rather than a silent one.
* **No simulator, in transit or in source.** The repository-wide isolation gate already
  walks every file; this one names the package, so a regression says which boundary broke.
* **No dependency on a layer that acts.** ``api`` may import the package root, its own
  modules, and the two layers it reads authority *through*: ``workspace``, whose job is
  resolving a reference to a path proved inside its root, and the domain's kind registry.
  It may not import ``execution``, ``adapters``, ``query``, ``evidence``, ``planning``,
  ``normalization`` or ``evaluation`` — each one decides something, and a boundary that
  imported one could start deciding it too. ``identity`` is still forbidden directly: a
  digest in this package's own source is how a read model would start claiming to *be*
  the identity, and the workspace reader is the layer that owns that.
* **A closed direct third-party surface.** ``fastapi``, ``pydantic`` and ``starlette``
  everywhere. FastAPI's and Pydantic's own closures are absent on purpose: they are their
  dependencies, pinned by them, and a gate that listed them could be satisfied by adding
  one directly.
* **Nothing from the future stack, early.** The import must not pull in DuckDB or any
  numerical package, and must not pull in Uvicorn - even though the sidecar module exists
  beside it and ``uvicorn`` is a declared runtime dependency. That is what keeps
  "importing this package starts no server" true by construction rather than by
  convention.
* **A public surface with no authority vocabulary and no control plane.** No exported name
  may mention a credential, a seal, a plan, a run, an execution, a worker, a queue, a
  session, evidence or a manifest — the shapes an API would acquire as soon as it started
  owning the things it is supposed to describe.
* **Read models that are not domain models.** Checked on the MRO, because the failure this
  prevents is a single import line, and it is the one that would make application metadata
  claim to be digested scientific authority.
* **No path ever enters a response.** A route that reached for ``pathlib`` to build a
  logical reference, and a read model that could hold one, are both checked structurally —
  because an absolute path in a response is how a local API becomes a filesystem
  disclosure.
* **A correct OpenAPI document**, served over HTTP and equal to the in-process one, with
  the versioned routes it publishes and typed response models for all of them.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import dynamisbench.api as api
from dynamisbench.api import API_V1_PREFIX, ApiModel, create_app

API_ROOT = Path(api.__file__).resolve().parent

API_MODULES = tuple(sorted(path.name for path in API_ROOT.glob("*.py")))

BOUNDARY_MODULES = (
    "__init__.py",
    "app.py",
    "errors.py",
    "models.py",
    "routing.py",
)
"""The application boundary: the five modules DB-2.1 established, unchanged.

Everything here is reachable by importing ``dynamisbench.api``, so everything here has to stay
as small and as inert as it was.
"""

SESSION_MODULES = (
    "control.py",
    "server.py",
    "session.py",
)
"""The session's own composition, added by DB-2.2 and DB-2.3 and reachable only by importing it
directly.

Three modules, deliberately split. One validates and enforces the session's credential and
origin policy and imports no web server; one binds the socket and runs the server and imports
Uvicorn; one reads the parent's private control channel and imports neither. That split is the
whole reason ``import dynamisbench.api`` still loads no server, and it is why none is in
``__all__``: no advertised name of this package mentions a session, a credential or a control
record.
"""

READER_MODULES = (
    "workspace_registry.py",
    "workspaces.py",
)
"""The workspace-reading surface DB-2.4 (RES-377) adds, reachable only through ``create_app``.

Two modules, and the split between them is the whole reason the boundary survived the change.
``workspace_registry`` holds the application's in-memory map of open workspaces and nothing
else — no scientific type, no filesystem, no validation. ``workspaces`` is the only module in
this package that imports the workspace layer, the domain's kind registry, and the reader that
validates and digests. Keeping them apart means the two concerns "remember which workspaces
this process has open" and "make an HTTP read model of an authority document" are separately
reviewable, and means the measured-import gate can name exactly one module as the reader.

Neither module is in ``__all__``: the API advertises its application surface, and a workspace
route's read models are reached by the routes that publish them.
"""

EXPECTED_MODULES = tuple(sorted((*BOUNDARY_MODULES, *SESSION_MODULES, *READER_MODULES)))
"""The union of the three groups, in the filesystem order the measurement produces."""

FORBIDDEN_ENGINE_MODULES = frozenset(
    {"mujoco", "opensim", "simtk", "gym", "gymnasium", "pybullet", "brax", "dm_control"}
)

FORBIDDEN_FIRST_PARTY = (
    "dynamisbench.adapters",
    "dynamisbench.evaluation",
    "dynamisbench.evidence",
    "dynamisbench.execution",
    "dynamisbench.normalization",
    "dynamisbench.planning",
    "dynamisbench.query",
)
"""Every layer the application boundary may not depend on, directly or in transit.

``execution`` and ``adapters`` are the two ADR-016 and ADR-017 name: the API never runs a
simulation and never speaks an engine's language. The rest are here for the same reason —
each one *decides* something, and an import is how a boundary would start deciding it too.
``evidence`` seals; ``planning`` compiles; ``query`` builds a projection; ``normalization``
and ``evaluation`` derive meaning. None of that is describing.

``workspace``, ``domain`` and ``identity`` are deliberately **not** here, and that is a
reviewed change DB-2.4 (RES-377) makes rather than an oversight. The API now legitimately
reads authority: ``workspace`` resolves a reference to a path proved inside its root,
``domain`` says which model a declared kind validates to, and ``identity`` digests a
validated model. All three are allowed to exactly one module each, and to no other —
``READER_MODULES`` names which. The gate below enforces the narrowing, and

``test_no_digest_reaches_an_api_module_directly`` keeps the identity prohibition in force
for every module in this package except the one reader, because a digest computed in an API
module rather than in the workspace layer is how a read model would start claiming to be
the identity.
"""

ALLOWED_EXTERNAL_SURFACE = frozenset({"fastapi", "pydantic", "starlette"})
"""``starlette`` is present for exactly one import: ``starlette.exceptions.HTTPException``,
which is the class the framework raises for an unmatched path or a wrong method and which
``fastapi.HTTPException`` only subclasses. Importing it from ``fastapi`` would look tidier
and silently leave every 404 and 405 on Starlette's default body.

Nothing else from either closure is permitted directly. FastAPI's and Pydantic's own
dependencies are absent on purpose: they are pinned by their packages, and a gate that
listed them could be satisfied by adding one directly.
"""

SESSION_EXTERNAL_SURFACE = ALLOWED_EXTERNAL_SURFACE | {"uvicorn"}
"""``uvicorn`` is permitted in exactly one module, and that is the reason for the split.

The application boundary must load no server when it is imported - that is what keeps "importing
this package starts nothing" true by construction. The sidecar must import Uvicorn to run one.
Keeping the two apart, and stating the wider surface only for the server, means a module that
reaches for Uvicorn to answer a request still fails here.
"""

READER_ALLOWED_ROOTS = frozenset(
    {"dynamisbench.workspace", "dynamisbench.domain", "dynamisbench.identity"}
)
"""What a reader module may reach that no other module may.

The three layers that answer "what is this authority document". Each is permitted to the two
reader modules only, and the per-module gate below narrows ``identity`` further still: it is
reachable only through the workspace package, never directly. That is what keeps a digest out
of a read model that was not assembled by the layer that owns digests.
"""

FIRST_PARTY = frozenset({"dynamisbench"})

FORBIDDEN_EXPORTS = (
    "auth",
    "benchmark",
    "bundle",
    "credential",
    "duckdb",
    "engine",
    "evidence",
    "execution",
    "manifest",
    "plan",
    "queue",
    "run",
    "seal",
    "session",
    "study",
    "worker",
    "workspace",
)
"""Words that would mean the API had started owning the thing it describes.

Substring matching on the advertised names, so the gate names the risk rather than enumerating
today's violations. ``install_error_contract`` is here on purpose: the error contract is
application surface, and a name like ``workspace_service`` would pass every other gate in this
file. DB-2.4 keeps ``workspace`` in the list and keeps its own read models out of ``__all__``
by importing them from the modules that publish them, so the ban is about the *package's*
surface and not about the existence of workspace routes.
"""

FORBIDDEN_MEASURED_IMPORTS = frozenset(
    {"uvicorn", "duckdb", "numpy", "scipy", "pyarrow", "pandas", "arrow"}
)
"""Present in the project's future, absent from this one.

Asserted rather than assumed so that pulling the scientific or transport stack in early
fails here instead of arriving as a surprise in a sidecar that has to be reinstalled
per environment.
"""

_IMPORT_PROBE = "\n".join(
    [
        "import sys",
        "import dynamisbench.api",
        "print('\\n'.join(sorted(sys.modules)))",
    ]
)


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    roots.discard("__future__")
    return roots


def _imported_first_party(path: Path) -> set[str]:
    """The ``dynamisbench.*`` modules one file imports, as dotted prefixes.

    A ``from dynamisbench import evidence`` is recorded as ``dynamisbench.evidence`` and
    not as ``dynamisbench``: the bare package name would match no forbidden prefix, so
    resolving the imported names is the difference between a gate and a formality.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith("dynamisbench"):
                modules.add(node.module)
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {name for name in modules if name.startswith("dynamisbench")}


def _loaded_module_names() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE], capture_output=True, text=True, check=True
    )
    return set(result.stdout.split())


@pytest.mark.parametrize("filename", API_MODULES)
def test_the_api_package_imports_no_simulator_library(filename: str) -> None:
    assert not _imported_roots(API_ROOT / filename) & FORBIDDEN_ENGINE_MODULES


@pytest.mark.parametrize("filename", API_MODULES)
def test_no_api_module_depends_on_a_layer_that_acts(filename: str) -> None:
    """The measured half of "the API describes, it does not run".

    Read on the source, because a dependency is written down whether or not it is ever
    exercised. The narrowing DB-2.4 makes — that ``workspace``, ``domain`` and ``identity``
    are allowed to the reader modules — is applied here as well as in the measured import
    gate, so a module cannot reach them by being renamed.
    """
    imported = _imported_first_party(API_ROOT / filename)
    allowed = READER_ALLOWED_ROOTS if filename in READER_MODULES else ()
    forbidden = tuple(
        prefix
        for prefix in FORBIDDEN_FIRST_PARTY
        if filename not in READER_MODULES or prefix not in allowed
    )
    offending = sorted(name for name in imported if any(name.startswith(p) for p in forbidden))
    assert offending == [], f"{filename} imports {offending}"


@pytest.mark.parametrize("filename", API_MODULES)
def test_no_digest_reaches_an_api_module_directly(filename: str) -> None:
    """``identity`` is reachable only *through* the workspace, never directly.

    A digest computed inside an API module is the one import that would make a read model
    claim to be scientific identity. The workspace reader is the layer that owns it, so the
    API asks that layer for a digest and takes a value back; it does not compute one.
    """
    imported = _imported_first_party(API_ROOT / filename)
    assert "dynamisbench.identity" not in imported, (
        f"{filename} imports identity directly; a digest must be asked of the workspace layer"
    )


@pytest.mark.parametrize(
    ("filename", "allowed"),
    [
        *((filename, ALLOWED_EXTERNAL_SURFACE) for filename in BOUNDARY_MODULES),
        ("control.py", ALLOWED_EXTERNAL_SURFACE),
        ("session.py", ALLOWED_EXTERNAL_SURFACE),
        ("server.py", SESSION_EXTERNAL_SURFACE),
    ],
)
def test_the_api_package_has_a_closed_external_surface(
    filename: str, allowed: frozenset[str]
) -> None:
    external = _imported_roots(API_ROOT / filename) - FIRST_PARTY - sys.stdlib_module_names
    assert not external - allowed, f"{filename} imports {sorted(external)}"


def test_only_the_server_module_may_import_a_web_server() -> None:
    """Stated on its own because it is the split that matters, not the table above.

    A module that reached for Uvicorn to answer a request would still satisfy a per-module
    table that gave it the wider surface, so the property is pinned directly: exactly one module
    in this package reaches a web server.
    """
    reaching = [
        filename for filename in API_MODULES if _imported_roots(API_ROOT / filename) & {"uvicorn"}
    ]

    assert reaching == ["server.py"]


def test_importing_the_api_package_loads_no_simulator_library() -> None:
    """A direct-import check is not enough: nothing may arrive transitively either."""
    loaded = {name.split(".")[0] for name in _loaded_module_names()}
    assert not loaded & FORBIDDEN_ENGINE_MODULES


def test_importing_the_api_package_loads_no_layer_that_acts() -> None:
    """The measurement that makes "the API describes, it does not run" structural.

    A fresh import of the API package must leave every layer that *decides* something
    unloaded, in transit as well as directly. A process that loaded the evidence or planning
    layer merely to describe the application would carry those modules' cost and their
    module-level work into a sidecar that exists to be thin (Architecture 8).
    """
    loaded = _loaded_module_names()
    acting = tuple(layer for layer in FORBIDDEN_FIRST_PARTY if layer not in READER_ALLOWED_ROOTS)
    assert not {name for name in loaded if any(name.startswith(layer) for layer in acting)}
    assert {name for name in loaded if name.startswith("dynamisbench.api")}


def test_importing_the_api_package_loads_the_boundary_and_nothing_from_the_future() -> None:
    loaded = {name.split(".")[0] for name in _loaded_module_names()}

    assert "fastapi" in loaded, "the API package must actually import the boundary it is for"
    assert not loaded & FORBIDDEN_MEASURED_IMPORTS, sorted(loaded & FORBIDDEN_MEASURED_IMPORTS)


def test_importing_the_api_package_loads_no_session_module() -> None:
    """The session's modules are reached by importing them, never by importing the package.

    This is what makes the two module groups meaningfully different rather than a naming
    convention. Measured on a fresh import, so an indirect arrival — through FastAPI, through
    the routing layer, through anything — fails here as well, and ``FORBIDDEN_MEASURED_IMPORTS``
    stays true: the Uvicorn prohibition above is a property of what the package loads, and this
    is why it still is.
    """
    loaded = _loaded_module_names()
    session = tuple(f"dynamisbench.api.{name.removesuffix('.py')}" for name in SESSION_MODULES)

    assert not {name for name in loaded if name.startswith(session)}


def test_every_advertised_name_exists_and_is_advertised_once() -> None:
    assert len(set(api.__all__)) == len(api.__all__)
    for name in api.__all__:
        assert hasattr(api, name), f"__all__ advertises {name}, which does not exist"


def test_no_exported_type_is_re_defined_outside_the_package() -> None:
    for name in api.__all__:
        value = getattr(api, name)
        if isinstance(value, type):
            assert value.__module__.startswith("dynamisbench.api"), (
                f"{name} is defined in {value.__module__}"
            )


def test_the_public_surface_carries_no_authority_or_control_plane_vocabulary() -> None:
    """What the API would acquire as soon as it started owning what it describes.

    Substring matching on the advertised names, so the gate names the risk rather than
    enumerating today's violations. ``install_error_contract`` is here on purpose: the
    error contract is application surface, and a name like ``workspace_service`` would pass
    every other gate in this file.
    """
    offenders = sorted(
        name for name in api.__all__ if any(word in name.lower() for word in FORBIDDEN_EXPORTS)
    )
    assert offenders == [], offenders


def test_an_exported_read_model_is_not_a_scientific_domain_model() -> None:
    """The separation ADR-016 depends on, checked on the class hierarchy.

    Importing ``DomainModel`` here is safe: this is a gate about what the API package must
    *not* be, so the test may know the domain while the package may not.
    """
    from dynamisbench.domain.spec.base import DomainModel

    models = [
        value
        for value in (getattr(api, name) for name in api.__all__)
        if isinstance(value, type) and issubclass(value, ApiModel)
    ]

    assert models, "the API must publish read models"
    for model in models:
        assert not issubclass(model, DomainModel), (
            f"{model.__name__} is a DomainModel; application metadata must not claim to be "
            "digested scientific authority"
        )


def test_the_module_set_is_the_whole_package() -> None:
    """Named so that adding a tenth is a reviewed change rather than a silent one.

    Stated as three named groups because the modules are not equivalent: five describe the
    application and are reachable from ``import dynamisbench.api``; three belong to the
    desktop session and are reachable only by importing them; and two read the workspace and
    are reachable only through ``create_app``. The groups are asserted disjoint, so a module
    cannot migrate into one of them by being renamed.
    """
    assert API_MODULES == EXPECTED_MODULES
    assert set(BOUNDARY_MODULES) & set(SESSION_MODULES) == set()
    assert set(BOUNDARY_MODULES) & set(READER_MODULES) == set()
    assert set(SESSION_MODULES) & set(READER_MODULES) == set()
    assert len(BOUNDARY_MODULES) + len(SESSION_MODULES) + len(READER_MODULES) == len(
        EXPECTED_MODULES
    )


def _openapi() -> dict[str, Any]:
    return create_app().openapi()


def test_the_openapi_document_publishes_exactly_the_versioned_routes() -> None:
    """Five routes under one namespace, and no verb that publishes itself for free.

    Stated as a closed set, so an unversioned route or a second namespace fails here instead
    of quietly becoming a public interface. The workspace routes read; the one non-GET verb is
    the root-selection operation and nothing else.
    """
    paths = _openapi()["paths"]
    assert sorted(paths) == [
        f"{API_V1_PREFIX}/health",
        f"{API_V1_PREFIX}/info",
        f"{API_V1_PREFIX}/workspaces/open",
        f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts",
        f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts/{{artifact_id}}",
    ]
    for path, operations in paths.items():
        expected = ["post"] if path.endswith("/open") else ["get"]
        assert sorted(operations) == expected, f"{path} publishes {sorted(operations)}"


def test_the_openapi_document_types_every_success_response() -> None:
    """A generated client is only as good as this, so the 200 of each route must name its
    own read model rather than an untyped object."""
    schemas = _openapi()["components"]["schemas"]

    def response_of(path: str, verb: str) -> dict[str, Any]:
        return _openapi()["paths"][path][verb]["responses"]["200"]

    assert response_of(f"{API_V1_PREFIX}/health", "get")["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/HealthResponse")
    assert response_of(f"{API_V1_PREFIX}/info", "get")["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ApplicationInfoResponse")
    assert response_of(f"{API_V1_PREFIX}/workspaces/open", "post")["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/OpenWorkspaceResponse")
    assert response_of(f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts", "get")["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/WorkspaceDiscoveryResponse")
    assert response_of(
        f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/artifacts/{{artifact_id}}", "get"
    )["content"]["application/json"]["schema"]["$ref"].endswith("/ArtifactInspectionResponse")

    assert {
        "HealthResponse",
        "ApplicationInfoResponse",
        "OpenWorkspaceResponse",
        "WorkspaceDiscoveryResponse",
        "ArtifactInspectionResponse",
        "ErrorResponse",
    } <= set(schemas)


def test_the_openapi_document_declares_the_failure_envelope_on_every_route() -> None:
    """A client has to learn the failure shape from the document, not from a wiki page.

    Read through the operation rather than the path, because the workspace routes publish a
    ``post`` and the application routes a ``get``: iterating the document catches a route whose
    documented failures were declared for the wrong verb.
    """
    for path, operations in _openapi()["paths"].items():
        for verb, operation in operations.items():
            responses = operation["responses"]
            assert {"405", "500"} <= set(responses), f"{path} {verb}"
            for status in ("405", "500"):
                assert responses[status]["content"]["application/json"]["schema"]["$ref"].endswith(
                    "/ErrorResponse"
                ), f"{path} {verb} {status}"


def test_the_served_openapi_document_is_the_one_the_factory_produced() -> None:
    """The document is part of the boundary, so it is qualified over HTTP as well as in
    process: a middleware that rewrote it would silently break every generated client."""
    with TestClient(create_app()) as client:
        served = client.get("/openapi.json")

    assert served.status_code == 200
    assert served.json() == _openapi()
