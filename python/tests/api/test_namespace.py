"""The versioned namespace exists and an application can be built from it.

DB-2.1's first qualification gate. It covers the three claims that must hold before any
endpoint semantics exist:

* importing the package starts nothing;
* ``create_app()`` builds an application without touching the machine;
* every route is published under one versioned prefix, derived from one version.

The requests here go through FastAPI's own in-process ``TestClient``, which drives the
ASGI application directly. No listening socket is opened anywhere in this issue: the
server process, its ephemeral port and its session credential belong to the desktop
session (Architecture §8/§13, RES-375), and a test that proved them would be
qualifying the wrong issue.
"""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from dynamisbench import __version__
from dynamisbench.api import (
    API_V1_PREFIX,
    API_VERSION,
    APPLICATION_NAME,
    create_app,
)

_FORBIDDEN_AUDIT_EVENTS = (
    "os.mkdir",
    "os.rename",
    "os.remove",
    "os.rmdir",
    "os.link",
    "os.symlink",
    "os.truncate",
    "os.chmod",
    "os.utime",
    "os.system",
    "os.exec",
    "os.fork",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
    "socket.__new__",
    "socket.bind",
    "socket.connect",
    "socket.listen",
    "subprocess.Popen",
    "tempfile.mkstemp",
    "tempfile.mkdtemp",
)
"""Audit events that mean creating, moving, or connecting to something.

The socket and process entries are the load-bearing ones: a module that binds or dials
on import, or spawns a worker at construction time, would otherwise look identical to a
well-behaved import to every test in this file.

``open`` is deliberately absent — importing a package legitimately reads its own source
— and write intent is audited separately by inspecting the mode.
"""

_CONSTRUCTION_PROBE = "\n".join(
    [
        "import sys",
        "from dynamisbench.api import create_app",
        "observed = []",
        "sys.addaudithook(lambda event, arguments: observed.append((event, arguments)))",
        "create_app()",
        f"forbidden = {_FORBIDDEN_AUDIT_EVENTS!r}",
        "writes = [",
        "    (event, arguments)",
        "    for event, arguments in observed",
        "    if event == 'open' and str(arguments[1])[:1] in {'w', 'a', 'x', '+'}",
        "]",
        "seen = sorted({event for event, _ in observed if event in forbidden})",
        "print('\\n'.join([*seen, *[f'write-open:{m}' for _, a in writes for m in a[1:]]]))",
    ]
)

_IMPORT_PROBE = "\n".join(
    [
        "import sys",
        "observed = []",
        "sys.addaudithook(lambda event, arguments: observed.append((event, arguments)))",
        "import dynamisbench.api",
        f"forbidden = {_FORBIDDEN_AUDIT_EVENTS!r}",
        "writes = sorted(",
        "    {m",
        "     for event, arguments in observed",
        "     if event == 'open'",
        "     for m in str(arguments[1])",
        "     if m in {'w', 'a', 'x', '+'}}",
        ")",
        "seen = sorted({event for event, _ in observed if event in forbidden})",
        "print('\\n'.join([*seen, *writes]))",
    ]
)


def _probe(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=True,
    )


def test_the_package_exports_a_factory_and_one_versioned_prefix() -> None:
    """The namespace is stated once, and the prefix is derived from the version.

    Checked on the value rather than on the source, because the failure this prevents —
    a second version added as a second hand-written prefix — shows up as a public route
    that disagrees with the advertised version, not as a lint error.
    """
    assert API_VERSION == "v1"
    assert API_V1_PREFIX == "/api/v1"
    assert API_V1_PREFIX == f"/api/{API_VERSION}"


def test_creating_an_application_returns_an_application_and_opens_nothing() -> None:
    """The factory's whole contract: one object out, nothing touched on the way.

    The audit hook is installed after every import has finished, so what it observes is
    ``create_app``'s own work and nothing a library did while being loaded.
    """
    result = _probe(_CONSTRUCTION_PROBE)

    assert result.stdout.split() == [], (
        f"create_app() performed forbidden work: {result.stdout.splitlines()}"
    )


def test_creating_an_application_starts_no_thread() -> None:
    """A background thread at construction is how a worker, a pool or a poller sneaks in.

    Measured rather than inspected: FastAPI does not spawn threads itself, so a change
    that did would be invisible in the source of this repository's own modules.
    """
    before = threading.active_count()
    create_app()
    assert threading.active_count() == before


def test_creating_two_applications_produces_the_same_schema() -> None:
    """Construction is a function of the code, not of the moment it was called.

    Compared through the OpenAPI schema rather than through the object identity, because
    two applications are never the same object and what a client depends on is that they
    describe the same interface.
    """
    assert create_app().openapi() == create_app().openapi()


def test_importing_the_package_starts_nothing() -> None:
    """Import is the one thing every other path in this project does first.

    Audited with the hook installed *before* the import, so nothing a library does while
    being loaded escapes it. Reading a package's own source is expected and excluded;
    opening a file for writing, creating a directory, and any socket or process event are
    not.
    """
    result = _probe(_IMPORT_PROBE)

    assert result.stdout.split() == [], (
        f"importing dynamisbench.api performed forbidden work: {result.stdout.splitlines()}"
    )


def test_the_factory_serves_the_versioned_health_route_in_process() -> None:
    with TestClient(create_app()) as client:
        response = client.get(f"{API_V1_PREFIX}/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_the_factory_serves_the_versioned_info_route_in_process() -> None:
    with TestClient(create_app()) as client:
        response = client.get(f"{API_V1_PREFIX}/info")

    assert response.status_code == 200
    assert response.json() == {
        "application": APPLICATION_NAME,
        "version": __version__,
        "api_version": API_VERSION,
    }


def test_the_only_published_paths_are_the_two_versioned_routes() -> None:
    """Every route the application answers lives under ``/api/v1``.

    Read from the OpenAPI document rather than from the internal route objects, because
    the document is the contract a client generates against, and it is the only view of
    the routing table that does not depend on how FastAPI happens to store an included
    router. Stated as a closed set rather than "at least these exist", so adding an
    unversioned route fails here instead of quietly becoming a public interface that no
    client can negotiate.
    """
    paths = set(create_app().openapi()["paths"])

    assert paths == {f"{API_V1_PREFIX}/health", f"{API_V1_PREFIX}/info"}, sorted(paths)


@pytest.mark.parametrize("path", ("/health", "/info", "/api/health", "/api/v2/health"))
def test_no_unversioned_alias_answers(path: str) -> None:
    """Reached through the client rather than the schema, because an alias that FastAPI
    does not publish is still a route a client can call."""
    with TestClient(create_app()) as client:
        assert client.get(path).status_code == 404
