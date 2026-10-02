"""Structural gates on the planning package's boundaries.

Planning claims to be a pure compiler. A claim like that decays silently — one convenience
import of ``pathlib`` here, one ``datetime`` call there — and no functional test notices,
because the plan it produces is still correct. These checks are therefore on the *import
graph* and the *source text*, where they cannot be defeated by an indirect call, and on a
measured subprocess import, where a transitive dependency cannot hide.

What is checked:

* **Purity (Architecture, ``planning``; VVUQ Workflow, Determinism).** No clock, no
  environment, no random source, no filesystem, no subprocess, no network. The planner is a
  function of its arguments, and ``os`` and ``pathlib`` are absent from that list because the
  planner has no legitimate reason to touch either — unlike the evidence package, whose whole
  job is hashing bytes and renaming directories.
* **No sampling.** ``random``, ``statistics`` and every numerical package are absent, because
  M1 does not sample and an accidental import would make a plan depend on a random source.
* **Hashing belongs to one module.** The fingerprint is a distinct identity, so exactly one
  module may hash, and it must reach for the existing algorithm vocabulary rather than
  declaring its own.
* **The boundary it sits on.** ``planning`` may import ``domain.spec`` and ``identity``, and
  nothing else first-party. In particular it must not import ``evidence`` or ``workspace``: a
  plan that could create a staging bundle or resolve a filesystem path would be executing
  rather than compiling, and run identity belongs to the execution lifecycle.
* **A closed external surface.** ``pydantic`` and ``rfc8785`` remain the entire third-party
  surface, so a new dependency would be a visible event rather than a surprise.
* **A closed module set.** Six modules, and adding a seventh is a reviewed decision.
* **No service, registry or container.** ADR-004 forbids an authoritative control plane, so
  the public surface is checked for the shapes that would reintroduce one.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import dynamisbench.planning as planning
from dynamisbench.identity import DigestAlgorithm
from tests.planning.compiler import PACKAGE_PARENT

PLANNING_ROOT = Path(planning.__file__).resolve().parent

PLANNING_MODULES = tuple(sorted(path.name for path in PLANNING_ROOT.glob("*.py")))

EXPECTED_MODULES = (
    "__init__.py",
    "authority.py",
    "compatibility.py",
    "errors.py",
    "factors.py",
    "plan.py",
    "runspec.py",
)

FORBIDDEN_ENGINE_MODULES = frozenset(
    {"mujoco", "opensim", "simtk", "gym", "gymnasium", "pybullet", "brax", "dm_control"}
)

FORBIDDEN_IN_PLANNING = frozenset(
    {
        "asyncio",
        "getpass",
        "multiprocessing",
        "os",
        "pathlib",
        "platform",
        "random",
        "secrets",
        "shutil",
        "socket",
        "statistics",
        "subprocess",
        "tempfile",
        "time",
        "urllib",
        "uuid",
        "zoneinfo",
    }
)
"""Modules whose use could put machine state, the clock, or a random source into a plan.

``pathlib`` and ``os`` are the important ones here. The evidence layer is allowed them
because it must hash files and rename directories; the planner is not allowed them at all,
because a planner that could reach a path is a planner that could be re-pointed by whatever
happens to be on disk, which is exactly the mutable workspace lookup the architecture
forbids in planning.
"""

FORBIDDEN_SAMPLING_MODULES = frozenset(
    {"numpy", "scipy", "salib", "sklearn", "pandas", "jax", "torch"}
)
"""No sampling stack, because RES-232 does not sample (VVUQ Workflow, Factors)."""

ALLOWED_EXTERNAL_SURFACE = frozenset({"pydantic", "rfc8785"})
"""Everything third-party the planning package may import *directly*.

``pydantic_core`` and ``typing_extensions`` are absent because they are Pydantic's own
dependencies, arriving when Pydantic arrives and pinned by it; a project gate that listed
them would be a gate that could be satisfied by adding them directly.
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

Measured, not assumed, so a new transitive dependency shows up as a failing gate rather than
as a surprise.
"""

FIRST_PARTY = frozenset({"dynamisbench"})

EXPECTED_FIRST_PARTY = ("dynamisbench.domain.spec", "dynamisbench.identity")
"""The two layers planning is built on, and nothing else.

``domain.spec`` is the validated authority it compiles and ``identity`` is the canonical
semantic boundary it hashes over. Anything else first-party would mean planning had started
to depend on a layer that sits beside it rather than beneath it.
"""

FORBIDDEN_AUDIT_EVENTS = (
    "open",
    "os.mkdir",
    "os.rename",
    "os.remove",
    "os.rmdir",
    "os.listdir",
    "os.scandir",
    "os.stat",
    "shutil.copyfile",
    "subprocess.Popen",
    "socket.connect",
    "tempfile.mkstemp",
)

_IMPORT_PROBE = "\n".join(
    [
        "import sys",
        "import dynamisbench.planning",
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


def _loaded_module_names() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE], capture_output=True, text=True, check=True
    )
    return set(result.stdout.split())


@pytest.mark.parametrize("filename", PLANNING_MODULES)
def test_the_planning_package_imports_no_simulator_library(filename: str) -> None:
    assert not _imported_roots(PLANNING_ROOT / filename) & FORBIDDEN_ENGINE_MODULES


@pytest.mark.parametrize("filename", PLANNING_MODULES)
def test_no_planning_module_reaches_the_clock_the_filesystem_or_a_random_source(
    filename: str,
) -> None:
    """A value from any of these could reach an execution fingerprint and change it."""
    roots = _imported_roots(PLANNING_ROOT / filename)
    assert not roots & FORBIDDEN_IN_PLANNING
    assert not roots & FORBIDDEN_SAMPLING_MODULES


@pytest.mark.parametrize("filename", PLANNING_MODULES)
def test_the_planning_package_has_a_closed_external_surface(filename: str) -> None:
    external = _imported_roots(PLANNING_ROOT / filename) - FIRST_PARTY - sys.stdlib_module_names
    assert not external - ALLOWED_EXTERNAL_SURFACE, f"{filename} imports {sorted(external)}"


def test_planning_depends_only_on_domain_and_identity() -> None:
    """It is built on the validated definitions and the identity boundary, and on nothing
    else. In particular it must not reach ``evidence`` or ``workspace``."""
    for filename in PLANNING_MODULES:
        first_party = {
            name
            for name in _imported_first_party(PLANNING_ROOT / filename)
            if not name.startswith("dynamisbench.planning")
        }
        unexpected = {
            name
            for name in first_party
            if not any(name.startswith(expected) for expected in EXPECTED_FIRST_PARTY)
        }
        assert not unexpected, f"{filename} imports {sorted(unexpected)}"


def test_planning_cannot_create_or_seal_evidence() -> None:
    """A planner that could open a staging bundle would be executing, not compiling.

    Checked on the import graph so it cannot be defeated by an indirect call, and on the
    public surface so no caller can reach evidence through the package either.
    """
    offenders = {
        path.name: sorted(
            name
            for name in _imported_first_party(path)
            if name.startswith(("dynamisbench.evidence", "dynamisbench.execution"))
        )
        for path in sorted(PLANNING_ROOT.glob("*.py"))
    }
    assert not {name: modules for name, modules in offenders.items() if modules}


def test_the_package_offers_no_run_identity() -> None:
    """Run identity belongs to the execution lifecycle, not to deterministic plan identity."""
    forbidden = ("run_id", "staging", "bundle", "seal", "manifest", "checksum")
    offenders = [
        name for name in planning.__all__ if any(word in name.lower() for word in forbidden)
    ]
    assert not offenders, f"the planning package exports {offenders}"


def test_the_package_offers_no_service_repository_or_container() -> None:
    """The architecture forbids an authoritative control plane; a service object with hidden
    global state is how one creeps back in."""
    forbidden = ("Service", "Repository", "Store", "Container", "Registry", "Manager", "Factory")
    offenders = [name for name in planning.__all__ if name.endswith(forbidden)]
    assert not offenders, f"the planning package exports {offenders}"


def test_the_package_offers_no_way_to_execute_or_write() -> None:
    forbidden = (
        "execute",
        "submit",
        "enqueue",
        "spawn",
        "launch",
        "start",
        "install",
        "write",
        "save",
        "dump",
    )
    offenders = [
        name for name in planning.__all__ if any(word in name.lower() for word in forbidden)
    ]
    assert not offenders, f"the planning package exports {offenders}"


def test_the_planning_context_offers_no_way_to_mutate_or_add() -> None:
    """It is a value object, not a store. A mutator would make a plan depend on what was
    looked up before it, which is the mutable lookup the architecture forbids here."""
    forbidden = ("add", "register", "put", "update", "append", "load", "fetch", "get_or_create")
    offenders = [
        name
        for name in dir(planning.PlanningContext)
        if not name.startswith("_") and name in forbidden
    ]
    assert not offenders, f"PlanningContext exposes {offenders}"


def test_the_planning_context_resolves_and_looks_up_and_offers_nothing_else() -> None:
    """Six resolution methods, and nothing else of its own.

    What is *not* asserted is the absence of Pydantic's inherited surface: a model always
    carries ``model_dump`` and friends. What is asserted is that this class defines no method
    beyond resolution, so a later edit cannot add a mutation, a registration or a lazy load
    without failing here.
    """
    import inspect

    declared = {
        name
        for name, value in vars(planning.PlanningContext).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }

    assert declared == {
        "quantity_of",
        "resolve_benchmark",
        "resolve_environment",
        "resolve_realization",
        "resolve_system_under_test",
        "scenario_of",
    }, sorted(declared)


def test_exactly_one_planning_module_hashes_and_it_names_the_existing_algorithm() -> None:
    """The fingerprint is a distinct identity, so there is exactly one place that hashes, and
    it takes the algorithm name from the existing vocabulary."""
    hashing = {
        filename
        for filename in PLANNING_MODULES
        if "hashlib" in _imported_roots(PLANNING_ROOT / filename)
    }
    assert hashing == {"runspec.py"}, f"only runspec.py may hash, found {sorted(hashing)}"
    imported = _imported_first_party(PLANNING_ROOT / "runspec.py")
    assert any(name.startswith("dynamisbench.identity") for name in imported), sorted(imported)
    assert planning.ExecutionFingerprint(hex="0" * 64).algorithm is DigestAlgorithm.SHA256


def test_importing_the_planning_package_loads_no_simulator_library() -> None:
    """A direct-import check is not enough: nothing may arrive transitively either."""
    loaded = {name.split(".")[0] for name in _loaded_module_names()}
    assert not loaded & FORBIDDEN_ENGINE_MODULES


def test_importing_the_planning_package_loads_exactly_the_declared_dependencies() -> None:
    """Includes Pydantic's own closure, because that is what a real import genuinely pulls
    in; what matters is that the set is exactly this and not one item longer."""
    top_level = {name.split(".")[0] for name in _loaded_module_names()}
    third_party = {
        name
        for name in top_level
        if not name.startswith(("dynamisbench", "_", "encodings"))
        and name not in sys.stdlib_module_names
    }
    assert third_party == MEASURED_EXTERNAL_SURFACE, sorted(third_party)


def test_importing_the_planning_package_loads_no_evidence_or_workspace_layer() -> None:
    """The same measurement for the boundary the compiler must not cross, including in
    transit: nothing may pull either in behind planning."""
    loaded = _loaded_module_names()

    assert not {name for name in loaded if name.startswith("dynamisbench.evidence")}
    assert not {name for name in loaded if name.startswith("dynamisbench.workspace")}


def test_every_advertised_name_exists_and_is_advertised_once() -> None:
    assert len(set(planning.__all__)) == len(planning.__all__)
    for name in planning.__all__:
        assert hasattr(planning, name), f"__all__ advertises {name}, which does not exist"


def test_no_exported_type_is_re_defined_outside_the_package() -> None:
    """A type offered under ``dynamisbench.planning`` must live there, so its identity surface
    cannot drift into an unrelated module by accident."""
    for name in planning.__all__:
        value = getattr(planning, name)
        if isinstance(value, type):
            assert value.__module__.startswith("dynamisbench.planning"), (
                f"{name} is defined in {value.__module__}"
            )


def test_the_six_modules_are_the_whole_package() -> None:
    """Named so that adding a seventh is a reviewed change rather than a silent one."""
    assert PLANNING_MODULES == EXPECTED_MODULES


def _compile_probe() -> str:
    """A subprocess program that compiles one plan and reports audited side effects.

    The audit hook is installed *after* every import has happened, so what it observes is
    the compiler's own work and nothing a library did while being loaded. That is the
    distinction that makes this test worth running: the import-graph gates cover what the
    planner *declares*, and this covers what it actually *does*.
    """
    return "\n".join(
        [
            "import sys",
            f"sys.path.insert(0, {str(PACKAGE_PARENT)!r})",
            "from tests.planning.compiler import compile_plan, single_run_study",
            "from tests.planning.factor_factories import factor_case",
            "compile_plan(single_run_study(replicates=3, seeds=(7, 11)), None,"
            " factor_cases=(factor_case(),))",
            "observed = []",
            "sys.addaudithook(lambda event, arguments: observed.append(event))",
            "compile_plan(single_run_study(replicates=3, seeds=(7, 11)), None,"
            " factor_cases=(factor_case(),))",
            f"forbidden = {FORBIDDEN_AUDIT_EVENTS!r}",
            "print('\\\\n'.join(sorted(set(observed) & set(forbidden))))",
        ]
    )


def test_compiling_a_plan_touches_no_file_and_starts_no_process() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _compile_probe()], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", (
        "compiling a plan performed filesystem, process or socket work: "
        f"{result.stdout.strip().splitlines()}"
    )


def test_compiling_a_plan_creates_no_directory_and_writes_no_file() -> None:
    """The filesystem half of the same claim, seen from a real directory: ``.staging`` and
    ``runs/`` must not appear because a plan was compiled."""
    with tempfile.TemporaryDirectory() as root:
        before = sorted(path.name for path in Path(root).iterdir())
        previous = os.getcwd()
        try:
            os.chdir(root)
            result = subprocess.run(
                [sys.executable, "-c", _compile_probe()],
                capture_output=True,
                text=True,
                check=True,
                cwd=root,
            )
        finally:
            os.chdir(previous)

        assert sorted(path.name for path in Path(root).iterdir()) == before
        assert result.stdout.strip() == ""
