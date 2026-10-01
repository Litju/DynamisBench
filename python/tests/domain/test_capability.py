"""Capability vocabulary and environment requirement invariants (ADR-003, ADR-018)."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import Field, TypeAdapter, ValidationError

from dynamisbench.domain.spec.base import DomainModel, keyed_by
from dynamisbench.domain.spec.capability import (
    Capability,
    CapabilityDeclaration,
    CapabilityRequirement,
    EngineBinding,
)
from dynamisbench.domain.spec.environment import (
    ComponentKind,
    EnvironmentDefinition,
    EnvironmentRequirement,
)
from dynamisbench.domain.spec.identifiers import BenchmarkId, EnvironmentId, RealizationId

from .factories import AT_LEAST, EXACT, capability_declaration, capability_requirement, specifier

EXPECTED_CAPABILITY_FAMILIES = {
    "forward_dynamics",
    "interactive_dynamics",
    "state_snapshot",
    "analysis",
    "inverse_dynamics",
    "trajectory_optimization",
}

ENGINE_WORDS = ("mujoco", "opensim", "simtk", "gym", "gymnasium", "mjmodel", "mjdata", "osim")


class _Declarations(DomainModel):
    capabilities: Annotated[
        tuple[CapabilityDeclaration, ...], keyed_by("capability"), Field(min_length=1)
    ]


class _Requirements(DomainModel):
    required: Annotated[
        tuple[CapabilityRequirement, ...], keyed_by("capability"), Field(min_length=1)
    ]


class _EnvironmentRequirements(DomainModel):
    requirements: Annotated[
        tuple[EnvironmentRequirement, ...], keyed_by("component"), Field(min_length=1)
    ]


def test_the_capability_vocabulary_covers_every_accepted_family() -> None:
    assert {capability.value for capability in Capability} == EXPECTED_CAPABILITY_FAMILIES


def test_capability_vocabulary_is_engine_independent() -> None:
    for capability in Capability:
        for engine_word in ENGINE_WORDS:
            assert engine_word not in capability.value


def test_capability_declaration_and_requirement_stay_distinct_concepts() -> None:
    declaration = capability_declaration(Capability.FORWARD_DYNAMICS)
    requirement = capability_requirement(Capability.FORWARD_DYNAMICS)
    assert isinstance(declaration, CapabilityDeclaration)
    assert isinstance(requirement, CapabilityRequirement)
    assert not isinstance(requirement, CapabilityDeclaration)
    assert "limitations" in declaration.model_dump_json()
    assert "limitations" not in requirement.model_dump_json()
    assert "essential" in requirement.model_dump_json()
    assert "essential" not in declaration.model_dump_json()


def test_a_capability_requirement_needs_a_rationale() -> None:
    with pytest.raises(ValidationError):
        CapabilityRequirement(capability=Capability.ANALYSIS, rationale="   ")


def test_capabilities_are_a_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Capability).validate_python("teleport")


def test_capability_declarations_are_keyed_and_canonically_ordered() -> None:
    ordered = _Declarations(
        capabilities=(
            capability_declaration(Capability.STATE_SNAPSHOT),
            capability_declaration(Capability.ANALYSIS),
        )
    )
    assert [item.capability for item in ordered.capabilities] == [
        Capability.ANALYSIS,
        Capability.STATE_SNAPSHOT,
    ]
    with pytest.raises(ValidationError) as excinfo:
        _Declarations(
            capabilities=(
                capability_declaration(Capability.ANALYSIS),
                capability_declaration(Capability.ANALYSIS),
            )
        )
    assert "duplicate capability" in str(excinfo.value)


def test_capability_requirements_are_keyed_by_capability() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _Requirements(
            required=(
                capability_requirement(Capability.ANALYSIS),
                capability_requirement(Capability.ANALYSIS, essential=False),
            )
        )
    assert "duplicate capability" in str(excinfo.value)

    optional = _Requirements(
        required=(capability_requirement(Capability.ANALYSIS, essential=False),)
    )
    assert optional.required[0].essential is False


def test_a_definition_must_advertise_at_least_one_capability() -> None:
    with pytest.raises(ValidationError):
        _Declarations(capabilities=())


def test_engine_binding_names_an_engine_without_constructing_one() -> None:
    binding = EngineBinding(engine="mujoco", specifier=specifier((EXACT, "3.3.0")))
    assert binding.model_dump_json() == (
        '{"engine":"mujoco","specifier":{"clauses":[{"comparator":"exact","version":"3.3.0"}]},'
        '"notes":null}'
    )
    with pytest.raises(ValidationError):
        EngineBinding(engine="MuJoCo 3", specifier=specifier((EXACT, "3.3.0")))
    with pytest.raises(ValidationError):
        EngineBinding(engine="mujoco", specifier=specifier())


def test_an_environment_must_declare_at_least_one_requirement(
    valid_environment: EnvironmentDefinition,
) -> None:
    assert valid_environment.requirements
    with pytest.raises(ValidationError):
        _EnvironmentRequirements(requirements=())


def test_a_component_may_only_be_constrained_once() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _EnvironmentRequirements(
            requirements=(
                EnvironmentRequirement(
                    component="mujoco",
                    kind=ComponentKind.ENGINE,
                    specifier=specifier((EXACT, "3.3.0")),
                ),
                EnvironmentRequirement(
                    component="mujoco",
                    kind=ComponentKind.ENGINE,
                    specifier=specifier((EXACT, "3.2.0")),
                ),
            )
        )
    assert "duplicate component" in str(excinfo.value)


def test_environment_requirements_are_stored_in_canonical_order() -> None:
    requirements = _EnvironmentRequirements(
        requirements=(
            EnvironmentRequirement(
                component="python",
                kind=ComponentKind.RUNTIME,
                specifier=specifier((AT_LEAST, "3.12")),
            ),
            EnvironmentRequirement(
                component="mujoco",
                kind=ComponentKind.ENGINE,
                specifier=specifier((AT_LEAST, "3.0")),
            ),
        )
    )
    assert [item.component for item in requirements.requirements] == ["mujoco", "python"]


def test_environment_identity_is_not_a_benchmark_or_realization_identity() -> None:
    class _Model(DomainModel):
        environment_id: EnvironmentId

    assert _Model.model_validate({"environment_id": "env.mujoco.x86-64"}).environment_id == (
        "env.mujoco.x86-64"
    )
    with pytest.raises(ValidationError):
        _Model.model_validate({"environment_id": BenchmarkId("db.lcmj20")})
    with pytest.raises(ValidationError):
        _Model.model_validate({"environment_id": RealizationId("mujoco.mujoco-v3")})


def test_unknown_engine_native_fields_fail_closed() -> None:
    with pytest.raises(ValidationError) as excinfo:
        EnvironmentDefinition.model_validate(
            {
                "environment_id": "env.mujoco.x86-64",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "requirements": [
                    {
                        "component": "mujoco",
                        "kind": "engine",
                        "specifier": {"clauses": [{"comparator": "exact", "version": "3.3.0"}]},
                    }
                ],
                "qpos": [0.0, 0.0],
            }
        )
    assert "qpos" in str(excinfo.value)
