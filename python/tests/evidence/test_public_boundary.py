"""Structural gates on the evidence package's boundaries.

Four properties are checked here rather than trusted, because each of them would let the
package rot in a way no functional test would notice:

* **Simulator independence (ADR-001).** The evidence layer is part of the engine-independent
  scientific core, so no engine-native library may be reachable from it. The repository-wide
  isolation gate already walks every source file; this gate names the package, so a regression
  says which boundary broke.

* **No clock in a seal.** The evidence package legitimately reads the *filesystem* — it has
  to hash files and rename directories — but it must not read the clock, the environment, or
  any random source, because a value from any of those could reach a manifest and change a
  scientific identity. ``recovery.py`` is the module under real pressure here: it classifies
  "abandoned" staging, and the whole design of that module is that it does not use time. The
  check is on the import graph, so it cannot be defeated by an indirect call.

* **The boundary against the two layers it sits on.** ``evidence`` may import ``identity`` and
  ``workspace``, because it is built on them. Neither may import ``evidence``, and ``evidence``
  must not reach back into anything that could turn a relative path back into an unrestricted
  filesystem path. In particular ``workspace`` must never import ``identity``: that separation
  is what makes it structurally impossible for an absolute path to reach a semantic digest, and
  RES-230 proved it, so RES-231 must not quietly undo it.

* **A closed external surface.** ``pydantic`` and ``rfc8785`` remain the entire third-party
  surface of the scientific core. A third dependency in the evidence layer would change what
  the evidence digest of every run in the project depends on, and has to be a visible event.

* **A closed module set.** The package is six modules and that is a reviewable fact; adding a
  seventh is a design decision rather than an accident.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import dynamisbench.evidence as evidence
from dynamisbench.evidence import staging
from dynamisbench.evidence import staging as staged_module

EVIDENCE_ROOT = Path(evidence.__file__).resolve().parent

EVIDENCE_MODULES = tuple(sorted(path.name for path in EVIDENCE_ROOT.glob("*.py")))

EXPECTED_MODULES = (
    "__init__.py",
    "bundle.py",
    "manifest.py",
    "recovery.py",
    "sealed.py",
    "staging.py",
)

FORBIDDEN_ENGINE_MODULES = frozenset(
    {"mujoco", "opensim", "simtk", "gym", "gymnasium", "pybullet", "brax", "dm_control"}
)

FORBIDDEN_IN_EVIDENCE = frozenset(
    {
        "datetime",
        "getpass",
        "platform",
        "random",
        "secrets",
        "socket",
        "time",
        "timeit",
        "uuid",
        "zoneinfo",
    }
)
"""Modules whose use could put machine state or non-determinism into a seal.

``os`` and ``pathlib`` are deliberately *absent*. The evidence layer is supposed to touch the
filesystem — hashing bytes and renaming a directory is the whole job — and it gets the paths it
touches from the workspace resolver rather than from an environment variable or a clock.
``hashlib`` is absent too: hashing arrives through ``dynamisbench.identity``, which owns the
digest algorithm vocabulary, so a second place that could name an algorithm is a second place
where the algorithm could change silently.
"""

ALLOWED_EXTERNAL_SURFACE = frozenset({"pydantic", "rfc8785"})
"""Everything third-party the evidence package may import *directly*.

``pydantic_core`` and ``typing_extensions`` are absent because they are Pydantic's own
dependencies rather than dependencies of this project: they arrive when Pydantic arrives, they
are pinned by it, and a project gate that listed them would be a gate that could be satisfied by
adding them directly. The direct-import surface is what this project chooses, and that is the
thing that has to stay visible.
"""

MEASURED_EXTERNAL_SURFACE = frozenset(
    {
        "annotated_types",
        "pydantic",
        "pydantic_core",
        "rfc8785",
        "typing_extensions",
        "typing_inspection",
    }
)
"""Everything a fresh import of the package actually loads from outside the standard library.

Measured, not assumed, so a new transitive dependency shows up as a failing gate rather than as
a surprise. Each entry is a declared dependency or a dependency of one, which is what
``ALLOWED_EXTERNAL_SURFACE`` plus Pydantic's own closure should produce and nothing more.
"""

FIRST_PARTY = frozenset({"dynamisbench"})

_IMPORT_PROBE = "\n".join(
    [
        "import sys",
        "import dynamisbench.evidence",
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
    """The ``dynamisbench.*`` modules one file imports, as dotted prefixes."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {name for name in modules if name.startswith("dynamisbench")}


@pytest.mark.parametrize("filename", EVIDENCE_MODULES)
def test_the_evidence_package_imports_no_simulator_library(filename: str) -> None:
    assert not _imported_roots(EVIDENCE_ROOT / filename) & FORBIDDEN_ENGINE_MODULES


@pytest.mark.parametrize("filename", EVIDENCE_MODULES)
def test_no_evidence_module_reads_the_clock_the_environment_or_a_random_source(
    filename: str,
) -> None:
    """A value from any of these could reach a manifest and change a scientific identity."""
    assert not _imported_roots(EVIDENCE_ROOT / filename) & FORBIDDEN_IN_EVIDENCE


@pytest.mark.parametrize("filename", EVIDENCE_MODULES)
def test_the_evidence_package_has_a_closed_external_surface(filename: str) -> None:
    external = _imported_roots(EVIDENCE_ROOT / filename) - FIRST_PARTY - sys.stdlib_module_names
    assert not external - ALLOWED_EXTERNAL_SURFACE, f"{filename} imports {sorted(external)}"


def test_evidence_digests_arrive_through_the_identity_layer() -> None:
    """Hashing is the identity layer's job; a second place naming an algorithm could change it."""
    hashing_modules = {
        filename
        for filename in EVIDENCE_MODULES
        if "hashlib" in _imported_roots(EVIDENCE_ROOT / filename)
    }
    assert hashing_modules == {"manifest.py"}, (
        f"only manifest.py may hash raw canonical bytes, found {sorted(hashing_modules)}"
    )
    assert "dynamisbench.identity.digests" in _imported_first_party(EVIDENCE_ROOT / "manifest.py")


@pytest.mark.parametrize(
    "filename", ("bundle.py", "manifest.py", "sealed.py", "staging.py", "recovery.py")
)
def test_the_evidence_modules_depend_only_on_the_two_layers_beneath_them(filename: str) -> None:
    """``identity`` and ``workspace`` are what RES-231 is built on, plus its own modules and
    the validated primitives it borrows.

    ``domain.spec`` is permitted for exactly two things — the project's own identifier pattern
    and digest hex form, and the frozen/forbid-unknown model base — both of which are shared
    vocabulary rather than a dependency on domain behaviour. The manifest reusing
    ``DomainModel`` is deliberate: a manifest is frozen, validated scientific authority, which
    is exactly what that base means, and declaring a second frozen base would be a second
    definition of the same property.
    """
    imported = _imported_first_party(EVIDENCE_ROOT / filename)
    unexpected = {
        name
        for name in imported
        if not name.startswith(
            ("dynamisbench.evidence", "dynamisbench.identity", "dynamisbench.workspace")
        )
        and "dynamisbench.domain.spec" not in name
    }
    assert not unexpected, f"{filename} imports {sorted(unexpected)}"


def test_the_evidence_layer_does_not_reach_into_domain_behaviour() -> None:
    """The two borrowed ``domain.spec`` modules are vocabulary, not a dependency on the domain.

    RES-231 must not require any RES-228 or RES-232 behaviour to seal a bundle, and an import of
    a domain *model* would make sealing depend on the scientific definitions being present.
    """
    borrowed = {
        name
        for filename in EVIDENCE_MODULES
        for name in _imported_first_party(EVIDENCE_ROOT / filename)
        if "dynamisbench.domain.spec" in name
    }
    assert borrowed <= {
        "dynamisbench.domain.spec.base",
        "dynamisbench.domain.spec.identifiers",
    }, sorted(borrowed)


def test_the_workspace_layer_never_imports_the_evidence_layer() -> None:
    """The direction that matters: evidence may sit on workspace, never the reverse.

    RES-230 established that ``workspace`` cannot reach ``identity``, which is what makes it
    structurally impossible for an absolute path to enter a semantic digest. This gate keeps
    ``evidence`` on the same side of that line, and would fail if the dependency were ever
    quietly inverted to break a circular import.
    """
    workspace_root = Path(staged_module.__file__).parent.parent / "workspace"
    offenders = {
        path.name
        for path in sorted(workspace_root.glob("*.py"))
        if any(name.startswith("dynamisbench.evidence") for name in _imported_first_party(path))
    }
    assert not offenders, f"the workspace layer imports the evidence layer: {sorted(offenders)}"


def test_the_evidence_layer_does_not_reach_past_the_workspace_for_paths() -> None:
    """Path resolution is the workspace's job; evidence may only tighten what it accepts.

    Checked on the module that would be the natural place to break this. If the evidence layer
    ever imported ``os.path.realpath``, ``glob``, ``fnmatch`` or ``PurePath`` to resolve a path
    of its own, it would be a second resolver and every containment guarantee RES-230 makes
    would stop being the single one.
    """
    assert "posixpath" not in _imported_roots(EVIDENCE_ROOT / "staging.py")
    assert "fnmatch" not in _imported_roots(EVIDENCE_ROOT / "bundle.py")


def test_importing_the_evidence_package_loads_no_simulator_library() -> None:
    """A direct-import check is not enough: nothing may arrive in transitively either."""
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE], capture_output=True, text=True, check=True
    )
    loaded = {name.split(".")[0] for name in result.stdout.split()}
    assert not loaded & FORBIDDEN_ENGINE_MODULES


def test_importing_the_evidence_package_loads_exactly_the_declared_dependencies() -> None:
    """The surface is measured rather than asserted, so a new transitive dependency fails here.

    Includes Pydantic's own closure, because that is what a real import genuinely pulls in; what
    matters is that the set is exactly this and not one item longer.
    """
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE], capture_output=True, text=True, check=True
    )
    top_level = {name.split(".")[0] for name in result.stdout.split()}
    third_party = {
        name
        for name in top_level
        if not name.startswith(("dynamisbench", "_", "encodings"))
        and name not in sys.stdlib_module_names
    }
    assert third_party == MEASURED_EXTERNAL_SURFACE, sorted(third_party)


def test_every_advertised_name_exists_and_is_advertised_once() -> None:
    assert len(set(evidence.__all__)) == len(evidence.__all__)
    for name in evidence.__all__:
        assert hasattr(evidence, name), f"__all__ advertises {name}, which does not exist"


def test_no_exported_type_is_re_defined_outside_the_package() -> None:
    """A type offered under ``dynamisbench.evidence`` must live there, so its identity surface
    cannot drift into an unrelated module by accident."""
    for name in evidence.__all__:
        value = getattr(evidence, name)
        if isinstance(value, type):
            assert value.__module__.startswith("dynamisbench.evidence"), (
                f"{name} is defined in {value.__module__}"
            )


def test_the_six_modules_are_the_whole_package() -> None:
    """Named so that adding a seventh is a reviewed change rather than a silent one."""
    assert EVIDENCE_MODULES == EXPECTED_MODULES


def test_the_package_offers_no_way_to_delete_a_bundle() -> None:
    """Immutability is lifecycle discipline, and the public surface must not offer the
    alternative: no service object, no repository, and nothing that removes evidence."""
    forbidden_exports = (
        "delete",
        "remove",
        "unlink",
        "rmtree",
        "cleanup",
        "purge",
        "discard",
        "prune",
        "wipe",
    )
    offenders = [
        name for name in evidence.__all__ if any(word in name.lower() for word in forbidden_exports)
    ]
    assert not offenders, f"the evidence package exports {offenders}"


def test_the_package_offers_no_service_repository_or_container() -> None:
    """The architecture forbids an authoritative control plane; a service class with hidden
    global state is how one creeps back in."""
    forbidden = ("Service", "Repository", "Store", "Container", "Registry", "Manager", "Factory")
    offenders = [name for name in evidence.__all__ if name.endswith(forbidden)]
    assert not offenders, f"the evidence package exports {offenders}"


def test_staging_exposes_no_delete_method() -> None:
    """An abandoned staging bundle is incomplete work whose fate is a scientific decision, so
    the handle that writes into one must not be able to remove it."""
    forbidden_exports = ("delete", "remove", "unlink", "discard", "cleanup", "purge")
    offenders = [
        name
        for name in dir(staging.StagingBundle)
        if not name.startswith("_") and any(word in name.lower() for word in forbidden_exports)
    ]
    assert not offenders, f"StagingBundle exposes {offenders}"


def test_every_public_entry_point_that_locates_a_bundle_goes_through_the_workspace() -> None:
    """Bundle verification, discovery and staging all resolve through RES-230's resolver.

    Checked on the signature rather than trusted: an entry point either takes a ``Workspace``,
    or takes a ``StagingBundle`` — which carries one, and was itself created through the
    resolver. Taking both is the safest of the three, because a caller cannot then finalize a
    bundle against a *different* workspace than the one it lives in.
    """
    import inspect

    locating = [
        name
        for name in evidence.__all__
        if name.startswith(("verify", "discover", "create_", "finalize"))
        and callable(getattr(evidence, name))
    ]
    assert locating
    for name in locating:
        parameters = inspect.signature(getattr(evidence, name)).parameters
        annotations = {str(annotation) for annotation in parameters.values()}
        assert "workspace" in parameters or any("StagingBundle" in a for a in annotations), (
            f"{name} reaches a bundle without a workspace: {list(parameters)}"
        )
