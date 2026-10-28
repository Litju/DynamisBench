"""Independent inspection of the reference model, adapter identity and declared scope.

These tests do not trust the adapter's declarations. They parse the MJCF bytes, recompute
the implementation digest from the reported source manifest, and check that the planned
realization, environment, study and RunSpec agree with the physical case the tests
independently describe.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from dynamisbench.adapters.mujoco import reference
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.environment import ComponentKind
from dynamisbench.domain.spec.identifiers import SEMVER_PATTERN, Comparator
from dynamisbench.identity import canonical_semantic_bytes
from tests.execution.mujoco.support import (
    COM_DISTANCE_M,
    COM_INERTIA_KG_M2,
    DURATION_S,
    GRAVITY_M_S2,
    INITIAL_ANGLE_RAD,
    INITIAL_ANGULAR_VELOCITY_RAD_S,
    MASS_KG,
    MODEL_SOURCE_PATH,
    TIMESTEP_S,
    ExecutionFixture,
)


def _floats(value: str) -> tuple[float, ...]:
    return tuple(float(item) for item in value.split())


def _model_root() -> ElementTree.Element:
    return ElementTree.fromstring(reference.model_bytes())


def test_the_model_bytes_are_the_reviewed_content() -> None:
    content = reference.model_bytes()

    assert hashlib.sha256(content).hexdigest() == reference.MODEL_SHA256
    assert b"<include" not in content
    assert b"file=" not in content
    assert b"<mesh" not in content
    assert b"<texture" not in content
    assert b"<geom" not in content
    assert b"<actuator" not in content
    assert b"<contact" not in content


def test_the_model_xml_states_the_independent_physical_case() -> None:
    root = _model_root()
    assert root.tag == "mujoco"
    assert root.attrib["model"] == "dynamisbench-reference-pendulum"

    option = root.find("option")
    assert option is not None
    assert float(option.attrib["timestep"]) == TIMESTEP_S
    assert option.attrib["integrator"] == "RK4"
    assert option.attrib["solver"] == "Newton"
    assert int(option.attrib["iterations"]) == 100
    assert float(option.attrib["tolerance"]) == 1e-12
    assert _floats(option.attrib["gravity"]) == (0.0, 0.0, -GRAVITY_M_S2)

    bodies = root.findall("./worldbody/body")
    assert len(bodies) == 1
    body = bodies[0]
    assert body.attrib["name"] == "pendulum"
    assert _floats(body.attrib["pos"]) == (0.0, 0.0, 0.0)

    joints = body.findall("joint")
    assert len(joints) == 1
    joint = joints[0]
    assert joint.attrib["name"] == "hinge"
    assert joint.attrib["type"] == "hinge"
    assert _floats(joint.attrib["axis"]) == (0.0, 1.0, 0.0)
    assert _floats(joint.attrib["pos"]) == (0.0, 0.0, 0.0)
    assert joint.attrib["limited"] == "false"
    assert float(joint.attrib["damping"]) == 0.0
    assert float(joint.attrib["armature"]) == 0.0
    assert float(joint.attrib["frictionloss"]) == 0.0

    inertial = body.find("inertial")
    assert inertial is not None
    assert _floats(inertial.attrib["pos"]) == (0.0, 0.0, -COM_DISTANCE_M)
    assert float(inertial.attrib["mass"]) == MASS_KG
    assert _floats(inertial.attrib["diaginertia"]) == (
        COM_INERTIA_KG_M2,
        COM_INERTIA_KG_M2,
        COM_INERTIA_KG_M2,
    )

    assert len(body.findall("site")) == 1
    assert body.find("geom") is None
    assert body.find("freejoint") is None


def test_the_planned_realization_binds_the_reviewed_model_and_scope(
    mujoco_fixture: ExecutionFixture,
) -> None:
    fixture = mujoco_fixture
    asset = fixture.realization.assets[0]

    assert asset.path == MODEL_SOURCE_PATH
    assert asset.sha256 == reference.MODEL_SHA256
    assert fixture.realization.engine.engine == "mujoco"
    assert fixture.realization.engine.specifier.clauses[0].comparator is Comparator.EXACT
    assert fixture.realization.engine.specifier.clauses[0].version == reference_engine_version(
        fixture
    )
    assert tuple(declaration.capability for declaration in fixture.realization.capabilities) == (
        Capability.FORWARD_DYNAMICS,
    )

    configuration = {entry.name: entry.value for entry in fixture.realization.engine_configuration}
    assert configuration["timestep"] == str(TIMESTEP_S)
    assert configuration["integrator"] == "RK4"
    assert configuration["solver"] == "Newton"
    assert configuration["iterations"] == "100"
    assert configuration["tolerance"] == "1e-12"
    assert configuration["duration"] == str(DURATION_S)
    assert configuration["initial-angle"] == str(INITIAL_ANGLE_RAD)
    assert configuration["initial-angular-velocity"] == str(INITIAL_ANGULAR_VELOCITY_RAD_S)
    assert configuration["gravity"] == str(GRAVITY_M_S2)
    assert configuration["precision"] == "float64"
    assert configuration["seed-policy"] == "no-stochastic-process"

    assert fixture.study.replicates == 1
    assert fixture.study.seeds == (0,)
    assert fixture.study.outcomes == (reference.OUTCOME,)
    assert fixture.run.spec.seed == 0
    assert fixture.run.spec.outcomes == (reference.OUTCOME,)
    assert fixture.run.spec.factors[0].value == GRAVITY_M_S2
    assert fixture.run.spec.factors[0].unit.expression == reference.GRAVITY_UNIT


def reference_engine_version(fixture: ExecutionFixture) -> str:
    """Read the engine version from the selected environment's independent requirement."""
    engine = next(
        requirement
        for requirement in fixture.environment.requirements
        if requirement.kind is ComponentKind.ENGINE
    )
    clause = engine.specifier.clauses[0]
    assert clause.comparator is Comparator.EXACT
    return clause.version


def test_the_selected_environment_is_exactly_pinned(
    mujoco_fixture: ExecutionFixture, mujoco_identity: dict
) -> None:
    fixture = mujoco_fixture
    requirements = {
        requirement.component: requirement for requirement in fixture.environment.requirements
    }

    engine = requirements["mujoco"]
    assert engine.kind is ComponentKind.ENGINE
    assert engine.specifier.clauses[0].comparator is Comparator.EXACT
    assert engine.specifier.clauses[0].version == mujoco_identity["engine_version"]

    python = requirements["python"]
    assert python.kind is ComponentKind.RUNTIME
    assert python.specifier.clauses[0].comparator is Comparator.EXACT
    assert python.specifier.clauses[0].version == mujoco_identity["python_version"]

    assert fixture.environment.environment_id == (
        f"env.mujoco.reference.{mujoco_identity['platform']}"
    )
    assert fixture.run.spec.environment.identifier == fixture.environment.environment_id


def test_the_worker_identity_is_recomputable_from_its_reported_manifest(
    mujoco_identity: dict,
) -> None:
    identity = mujoco_identity
    payload = {key: value for key, value in identity.items() if key != "implementation_digest"}
    recomputed = hashlib.sha256(canonical_semantic_bytes(payload)).hexdigest()

    assert recomputed == identity["implementation_digest"]
    assert payload["schema"] == reference.IMPLEMENTATION_IDENTITY_SCHEMA
    assert payload["adapter_id"] == reference.ADAPTER_ID
    assert payload["adapter_version"] == reference.ADAPTER_VERSION
    assert payload["engine"] == "mujoco"
    assert payload["protocol_version"] == 1
    assert payload["capabilities"] == ["forward_dynamics"]
    assert payload["model_sha256"] == reference.MODEL_SHA256

    package_root = Path(reference.__file__).resolve().parent
    reported_paths = {entry["path"] for entry in identity["source_manifest"]}
    assert reported_paths == set(reference.ADAPTER_SOURCE_FILES)
    assert "qualification.py" not in reported_paths
    for entry in identity["source_manifest"]:
        content = (package_root / entry["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]


def test_the_engine_version_is_a_semver_and_the_adapter_scope_is_narrow(
    mujoco_identity: dict,
) -> None:
    import re

    assert re.fullmatch(SEMVER_PATTERN, mujoco_identity["engine_version"])
    assert mujoco_identity["capabilities"] == ["forward_dynamics"]
    assert set(mujoco_identity["capabilities"]).isdisjoint(
        {
            Capability.INTERACTIVE_DYNAMICS.value,
            Capability.STATE_SNAPSHOT.value,
            Capability.ANALYSIS.value,
            Capability.INVERSE_DYNAMICS.value,
            Capability.TRAJECTORY_OPTIMIZATION.value,
        }
    )
