"""Determinism of the compiler: equal arguments produce equal plans, byte for byte.

Determinism is the one property every later stage depends on. If the same validated study
and the same validated authority can compile to two different plans, then nothing a run
records about itself is comparable with anything, and the execution fingerprint stops being
an identity.

Each test attacks one specific way determinism could leak in — the caller's input order, the
working directory, the Python hash seed, the interpreter, a recompiled model — rather than
asserting the general property once and hoping.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dynamisbench.identity import canonical_semantic_bytes
from dynamisbench.planning import StudyPlan
from tests.domain import factories as domain
from tests.planning.compiler import PACKAGE_PARENT, compile_plan, plan_of, single_run_study
from tests.planning.factor_factories import factor_case, multi_axis_study, wide_world
from tests.planning.factories import World, default_world

WIDE_STUDY = multi_axis_study(replicates=2, seeds=(7, 11))
WIDE_CASES = (factor_case("case-a"), factor_case("case-b", stiffness=1.1))


def canonical(plan: StudyPlan) -> bytes:
    """The one canonical byte string a whole plan is compared by."""
    return canonical_semantic_bytes(plan)


def wide_plan() -> StudyPlan:
    return plan_of(WIDE_STUDY, wide_world(), factor_cases=WIDE_CASES)


def test_the_same_arguments_produce_a_byte_identical_plan() -> None:
    assert canonical(wide_plan()) == canonical(wide_plan())


def test_the_same_arguments_produce_identical_fingerprints_in_identical_order() -> None:
    first, second = wide_plan(), wide_plan()

    assert [run.fingerprint.hex for run in first.runs] == [
        run.fingerprint.hex for run in second.runs
    ]
    assert [run.ordinal for run in first.runs] == [run.ordinal for run in second.runs]


def test_a_reordered_catalog_produces_the_same_plan() -> None:
    world = wide_world()
    reversed_world = World(
        benchmarks=tuple(reversed(world.benchmarks)),
        realizations=tuple(reversed(world.realizations)),
        systems_under_test=tuple(reversed(world.systems_under_test)),
        environments=tuple(reversed(world.environments)),
    )

    assert canonical(wide_plan()) == canonical(
        plan_of(WIDE_STUDY, reversed_world, factor_cases=tuple(reversed(WIDE_CASES)))
    )


def test_reordered_study_collections_produce_the_same_plan() -> None:
    """The domain declares its keyed collections order-insensitive, so authoring order cannot
    reach the plan at all. Authoring the same study from reordered collections proves it at
    the boundary rather than trusting the validator."""
    forward = domain.study_definition(
        factors=(domain.uncertainty_factor(), domain.controlled_factor())
    )
    backward = domain.study_definition(
        factors=(domain.controlled_factor(), domain.uncertainty_factor())
    )

    assert canonical(plan_of(forward, default_world(), factor_cases=(factor_case(),))) == canonical(
        plan_of(backward, default_world(), factor_cases=(factor_case(),))
    )


def test_reversing_the_authoring_order_of_a_benchmark_release_changes_nothing() -> None:
    scenarios = (
        domain.scenario_definition("sc.a"),
        domain.scenario_definition("sc.b"),
        domain.scenario_definition("sc.c"),
    )
    forward = domain.benchmark_release(scenarios=scenarios, references=())
    backward = domain.benchmark_release(scenarios=tuple(reversed(scenarios)), references=())
    base = default_world()

    def plan_for(release):
        world = World(
            benchmarks=(release,),
            realizations=base.realizations,
            systems_under_test=base.systems_under_test,
            environments=base.environments,
        )
        return plan_of(single_run_study(), world, factor_cases=(factor_case(),))

    assert plan_for(forward) == plan_for(backward)
    assert [run.spec.scenario.identifier for run in plan_for(forward).runs] == [
        "sc.a",
        "sc.b",
        "sc.c",
    ]


def test_two_plans_from_one_context_are_equal() -> None:
    """There is no hidden registry, so there is nothing for a second compile to read."""
    assert plan_of(WIDE_STUDY, wide_world(), factor_cases=WIDE_CASES) == plan_of(
        WIDE_STUDY, wide_world(), factor_cases=WIDE_CASES
    )


def test_recompiling_a_validated_definition_does_not_change_the_plan() -> None:
    """Two model instances of the same meaning are the same authority."""
    world = wide_world()
    recompiled = World(
        benchmarks=tuple(
            type(release).model_validate(release.model_dump()) for release in world.benchmarks
        ),
        realizations=tuple(
            type(item).model_validate(item.model_dump()) for item in world.realizations
        ),
        systems_under_test=tuple(
            type(item).model_validate(item.model_dump()) for item in world.systems_under_test
        ),
        environments=tuple(
            type(item).model_validate(item.model_dump()) for item in world.environments
        ),
    )

    assert canonical(plan_of(WIDE_STUDY, world, factor_cases=WIDE_CASES)) == canonical(
        plan_of(WIDE_STUDY, recompiled, factor_cases=WIDE_CASES)
    )


_PROBE = "\n".join(
    [
        "import sys",
        f"sys.path.insert(0, {str(PACKAGE_PARENT)!r})",
        "import hashlib",
        "from tests.planning.compiler import plan_of",
        "from tests.planning.factor_factories import factor_case, multi_axis_study, wide_world",
        "from dynamisbench.identity import canonical_semantic_bytes",
        "from dynamisbench.planning import run_spec_fingerprint",
        "study = multi_axis_study(replicates=2, seeds=(7, 11))",
        "plan = plan_of(study, wide_world(),",
        "               factor_cases=(factor_case('case-a'),",
        "                            factor_case('case-b', stiffness=1.1)))",
        "print(hashlib.sha256(canonical_semantic_bytes(plan)).hexdigest())",
        "print(','.join(run_spec_fingerprint(run.spec).hex for run in plan.runs))",
    ]
)


def _probe(*, cwd: str | None = None, hash_seed: str | None = None) -> list[str]:
    environment = dict(os.environ)
    environment.pop("PYTHONHASHSEED", None)
    if hash_seed is not None:
        environment["PYTHONHASHSEED"] = hash_seed
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env=environment,
    )
    return result.stdout.split()


def test_the_python_hash_seed_does_not_change_a_plan_or_a_fingerprint() -> None:
    """Python randomises ``str`` hashing per process unless told otherwise. A plan that reached
    a set or a dict iteration order anywhere would therefore differ between two interpreters,
    which is why this is measured across processes rather than inside one."""
    first = _probe(hash_seed="0")
    second = _probe(hash_seed="12345")
    third = _probe(hash_seed="random")

    assert first == second == third
    assert len(first) == 2, first


def test_the_working_directory_does_not_change_a_plan_or_a_fingerprint() -> None:
    """A plan is compiled from validated objects, not from anything on disk, so where the
    compiler runs is not part of the execution's identity."""
    with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as there:
        assert _probe(cwd=here) == _probe(cwd=there)


def test_a_second_interpreter_reproduces_the_plan_byte_for_byte() -> None:
    assert _probe() == _probe()


def test_no_absolute_path_reaches_the_canonical_plan_bytes() -> None:
    """The plan names authority, never a location. Asserted on the bytes rather than on the
    fields, because a path could reach them through a nested digest."""
    rendered = canonical(compile_plan(single_run_study(replicates=2, seeds=(7, 11)))).decode(
        "utf-8"
    )

    assert str(Path.cwd()) not in rendered
    assert str(Path.home()) not in rendered
    assert os.path.expanduser("~") not in rendered
    assert "staging" not in rendered
    assert "runs/" not in rendered


def test_the_study_identifier_and_prose_are_absent_from_the_canonical_spec_bytes() -> None:
    """The plan names its study; a RunSpec does not."""
    subject = single_run_study(
        research_question="Why does the load change apex height?",
        analysis_plan="Report a half-range across seeds.",
    )
    plan = compile_plan(subject)

    rendered = canonical_semantic_bytes(plan.runs[0].spec).decode("utf-8")

    assert "Why does the load change apex height?" not in rendered
    assert "half-range across seeds" not in rendered
    assert "research_question" not in rendered
    assert "analysis_plan" not in rendered


def test_the_planning_package_imports_standalone() -> None:
    """Importing the package must consult no workspace and read no authority: a caller that
    wants a plan supplies the definitions, and importing the package is how it obtains the
    compiler."""
    import dynamisbench.planning as package

    program = "\n".join(
        [
            "import dynamisbench.planning as package",
            "print(len(package.__all__))",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )

    assert int(result.stdout.strip()) == len(package.__all__)
