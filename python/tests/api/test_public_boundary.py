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

* **A closed module set, in two groups.** Five boundary modules, reachable from
  ``import dynamisbench.api``, and the two session modules DB-2.2 adds, reachable only by
  importing them directly. An eighth is a reviewed change rather than a silent one.
* **No simulator, in transit or in source.** The repository-wide isolation gate already
  walks every file; this one names the package, so a regression says which boundary broke.
* **No dependency on any scientific layer.** ``api`` may import the package root and its
  own modules. It may not import ``execution``, ``adapters``, ``query``, ``evidence``,
  ``workspace``, ``planning``, ``domain``, ``normalization`` or ``evaluation`` — measured on
  a fresh import as well as on the source, because a transitive arrival would make the API
  process depend on a layer it is supposed to describe. This is the gate that makes
  "FastAPI is not authority" structural rather than aspirational.
* **A closed direct third-party surface.** ``fastapi``, ``pydantic`` and ``starlette``
  everywhere, and ``uvicorn`` in ``server.py`` alone. FastAPI's and Pydantic's own closures are
  absent on purpose: they are their dependencies, pinned by them, and a gate that listed them
  could be satisfied by adding one directly.
* **Nothing from the future stack, early.** The import must not pull in DuckDB or any numerical
  package, and must not pull in Uvicorn - even though the sidecar module exists beside it and
  ``uvicorn`` is a declared runtime dependency. That is what keeps "importing this package
  starts no server" true by construction rather than by convention.
* **A public surface with no authority vocabulary and no control plane.** No exported name
  may mention a benchmark, workspace, evidence, seal, plan, run, execution, worker, queue,
  session or credential — the shapes an API would acquire as soon as it started owning the
  things it is supposed to describe.
* **Read models that are not domain models.** Checked on the MRO, because the failure this
  prevents is a single import line, and it is the one that would make application metadata
  claim to be digested scientific authority.
* **A correct OpenAPI document**, served over HTTP and equal to the in-process one, with
  exactly the two versioned routes and typed response models for both.
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
    "server.py",
    "session.py",
)
"""The session's own composition, added by DB-2.2 and reachable only by importing it directly.

Two modules, deliberately split. One validates and enforces the session's credential and origin
policy and imports no web server; one binds the socket and runs the server and imports Uvicorn.
That split is the whole reason ``import dynamisbench.api`` still loads no server, and it is why
neither is in ``__all__``: no advertised name of this package mentions a session or a credential.
"""

EXPECTED_MODULES = BOUNDARY_MODULES + SESSION_MODULES

FORBIDDEN_ENGINE_MODULES = frozenset(
    {"mujoco", "opensim", "simtk", "gym", "gymnasium", "pybullet", "brax", "dm_control"}
)

FORBIDDEN_FIRST_PARTY = (
    "dynamisbench.adapters",
    "dynamisbench.domain",
    "dynamisbench.evaluation",
    "dynamisbench.evidence",
    "dynamisbench.execution",
    "dynamisbench.identity",
    "dynamisbench.normalization",
    "dynamisbench.planning",
    "dynamisbench.query",
    "dynamisbench.workspace",
)
"""Every layer the application boundary may not depend on.

``execution`` and ``adapters`` are the two named by ADR-016 and ADR-017: the API never
runs a simulation and never speaks an engine's language. The rest are here for the same
reason — each one owns scientific meaning that an HTTP response must not restate, and an
import is how a response would start doing that. ``identity`` is included because a
digest in a response body is how an application metadata field would start looking like a
scientific identity.
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
"""Words that would mean the API had started owning the thing it describes."""

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
def test_no_api_module_depends_on_a_scientific_layer(filename: str) -> None:
    imported = _imported_first_party(API_ROOT / filename)
    offending = sorted(
        name
        for name in imported
        if any(name.startswith(forbidden) for forbidden in FORBIDDEN_FIRST_PARTY)
    )
    assert offending == [], f"{filename} imports {offending}"


@pytest.mark.parametrize(
    ("filename", "allowed"),
    [
        *((filename, ALLOWED_EXTERNAL_SURFACE) for filename in BOUNDARY_MODULES),
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


def test_importing_the_api_package_loads_no_scientific_layer() -> None:
    """The measurement that makes "FastAPI is not authority" structural.

    A fresh import of the API package must leave every other DynamisBench layer unloaded,
    in transit as well as directly. A process that loaded the evidence or planning layer
    merely to describe the application would carry those modules' cost, their module-level
    work and their dependencies into a sidecar that exists to be thin (Architecture 8).
    """
    loaded = _loaded_module_names()

    assert not {
        name for name in loaded if any(name.startswith(layer) for layer in FORBIDDEN_FIRST_PARTY)
    }
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
    """Named so that adding an eighth is a reviewed change rather than a silent one.

    Stated as two named groups because the modules are not equivalent: five describe the
    application and are reachable from ``import dynamisbench.api``, and two belong to the
    desktop session and are not.
    """
    assert API_MODULES == EXPECTED_MODULES
    assert set(BOUNDARY_MODULES) & set(SESSION_MODULES) == set()


def _openapi() -> dict[str, Any]:
    return create_app().openapi()


def test_the_openapi_document_publishes_exactly_the_two_versioned_routes() -> None:
    paths = _openapi()["paths"]

    assert sorted(paths) == [f"{API_V1_PREFIX}/health", f"{API_V1_PREFIX}/info"]
    for operations in paths.values():
        assert sorted(operations) == ["get"], "no verb may be published without a reason to"


def test_the_openapi_document_types_both_success_responses() -> None:
    """A generated client is only as good as this, so the 200 of each route must name its
    own read model rather than an untyped object."""
    schemas = _openapi()["components"]["schemas"]

    health = _openapi()["paths"][f"{API_V1_PREFIX}/health"]["get"]["responses"]["200"]
    info = _openapi()["paths"][f"{API_V1_PREFIX}/info"]["get"]["responses"]["200"]

    assert health["content"]["application/json"]["schema"]["$ref"].endswith("/HealthResponse")
    assert info["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ApplicationInfoResponse"
    )
    assert {"HealthResponse", "ApplicationInfoResponse", "ErrorResponse"} <= set(schemas)


def test_the_openapi_document_declares_the_failure_envelope_on_both_routes() -> None:
    """A client has to learn the failure shape from the document, not from a wiki page."""
    for path, operations in _openapi()["paths"].items():
        responses = operations["get"]["responses"]

        assert {"405", "500"} <= set(responses), path
        for status in ("405", "500"):
            assert responses[status]["content"]["application/json"]["schema"]["$ref"].endswith(
                "/ErrorResponse"
            ), f"{path} {status}"


def test_the_served_openapi_document_is_the_one_the_factory_produced() -> None:
    """The document is part of the boundary, so it is qualified over HTTP as well as in
    process: a middleware that rewrote it would silently break every generated client."""
    with TestClient(create_app()) as client:
        served = client.get("/openapi.json")

    assert served.status_code == 200
    assert served.json() == _openapi()
