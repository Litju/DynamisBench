"""Benchmark, scenario, realization, SUT, and release invariants (ADR-002)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from dynamisbench.domain.spec.benchmark import (
    CREDIBILITY_LADDER,
    BenchmarkRelease,
    CredibilityLevel,
)
from dynamisbench.domain.spec.capability import Capability
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    RealizationId,
    StudyId,
    SUTId,
)
from dynamisbench.domain.spec.quantities import CanonicalUnit
from dynamisbench.domain.spec.realizations import (
    AssetReference,
    ConfigurationEntry,
    NormalizationTransform,
    RealizationDefinition,
    RealizationQuantityMapping,
)
from dynamisbench.domain.spec.scenarios import (
    EventDefinition,
    QuantityAssignment,
    ScenarioDefinition,
)
from dynamisbench.domain.spec.sut import (
    SUTInterface,
    SUTInterfaceKind,
    SUTKind,
)

from .factories import (
    benchmark_release,
    capability_requirement,
    event,
    quantity_assignment,
    quantity_mapping,
    realization_definition,
    scenario_definition,
    sut_definition,
    sut_provenance,
)

ENGINE_NATIVE_TOKENS = (
    "mjmodel",
    "mjdata",
    "qpos",
    "qvel",
    "qacc",
    "simtk",
    "opensim",
    "statevector",
    "observation_space",
    "gym",
    "actuator",
    "geom_rgba",
)


def test_a_scenario_needs_a_bounded_duration_and_initial_conditions() -> None:
    scenario = scenario_definition()
    assert scenario.duration_s == 2.0
    assert scenario.initial_conditions
    with pytest.raises(ValidationError):
        ScenarioDefinition.model_validate(
            {
                "scenario_id": "sc.loaded-cmj",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "duration_s": 0.0,
                "initial_conditions": [
                    {
                        "quantity": "q.foot.vertical_force",
                        "value": 0.0,
                        "unit": {"expression": "N"},
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        ScenarioDefinition.model_validate(
            {
                "scenario_id": "sc.loaded-cmj",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "duration_s": 1.0,
                "initial_conditions": [],
            }
        )


def test_a_scenario_may_not_assign_the_same_quantity_twice() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ScenarioDefinition.model_validate(
            {
                "scenario_id": "sc.loaded-cmj",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "duration_s": 1.0,
                "initial_conditions": [
                    {
                        "quantity": "q.foot.vertical_force",
                        "value": 0.0,
                        "unit": {"expression": "N"},
                    },
                    {
                        "quantity": "q.foot.vertical_force",
                        "value": 1.0,
                        "unit": {"expression": "N"},
                    },
                ],
            }
        )
    assert "duplicate quantity" in str(excinfo.value)


def test_an_event_expectation_and_tolerance_are_declared_together() -> None:
    assert event("takeoff").tolerance_s == 0.005
    with pytest.raises(ValidationError):
        EventDefinition(event_id="takeoff", label="Takeoff", expected_time_s=0.3)
    with pytest.raises(ValidationError):
        EventDefinition(event_id="takeoff", label="Takeoff", tolerance_s=0.01)
    assert EventDefinition(event_id="takeoff", label="Takeoff").tolerance_s is None


def test_a_scenario_may_not_declare_the_same_event_twice() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ScenarioDefinition.model_validate(
            {
                "scenario_id": "sc.loaded-cmj",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "duration_s": 1.0,
                "initial_conditions": [
                    {
                        "quantity": "q.foot.vertical_force",
                        "value": 0.0,
                        "unit": {"expression": "N"},
                    }
                ],
                "events": [
                    {"event_id": "takeoff", "label": "Takeoff"},
                    {"event_id": "takeoff", "label": "Takeoff again"},
                ],
            }
        )
    assert "duplicate event_id" in str(excinfo.value)


def test_a_system_under_test_is_one_of_the_architectural_kinds() -> None:
    assert {kind.value for kind in SUTKind} == {
        "controller",
        "model",
        "numerical_method",
        "optimizer",
        "complete_system",
    }
    assert sut_definition().kind is SUTKind.CONTROLLER


def test_an_external_sut_must_state_how_it_will_be_identified() -> None:
    with pytest.raises(ValidationError) as excinfo:
        sut_provenance(repository="org/repo", ref="v1", resolved_commit=None)
    assert "resolved commit or a build digest" in str(excinfo.value)
    by_digest = sut_provenance(
        repository=None, ref=None, resolved_commit=None, build_digest="a" * 64
    )
    assert by_digest.build_digest == "a" * 64


def test_a_subprocess_sut_declares_its_command_and_others_do_not() -> None:
    assert sut_definition().interface.command is not None
    with pytest.raises(ValidationError) as excinfo:
        SUTInterface(kind=SUTInterfaceKind.SUBPROCESS)
    assert "must declare its command" in str(excinfo.value)
    for kind in (SUTInterfaceKind.IN_PROCESS, SUTInterfaceKind.BRIDGE):
        assert SUTInterface(kind=kind).command is None
        with pytest.raises(ValidationError) as excinfo:
            SUTInterface(kind=kind, command=("python",))
        assert "must not declare a command" in str(excinfo.value)


def test_a_realization_must_advertise_capabilities_and_bind_to_a_benchmark() -> None:
    realization = realization_definition()
    assert realization.capabilities
    assert realization.quantity_mappings
    assert realization.benchmark.identifier == "db.lcmj20"
    assert realization.engine.engine == "mujoco"
    with pytest.raises(ValidationError):
        RealizationDefinition.model_validate(
            {
                "realization_id": "rl.mujoco.loaded-cmj",
                "version": "1.0.0",
                "label": "label",
                "description": "description",
                "benchmark": {"identifier": "db.lcmj20", "version": "1.0.0"},
                "engine": {
                    "engine": "mujoco",
                    "specifier": {"clauses": [{"comparator": "exact", "version": "3.3.0"}]},
                },
                "capabilities": [],
                "quantity_mappings": [
                    {
                        "quantity": "q.foot.vertical_force",
                        "source": "force_sensor_foot",
                    }
                ],
            }
        )


def test_a_realization_benchmark_reference_is_a_benchmark_and_not_another_concept() -> None:
    payload = realization_definition().model_dump(mode="json")
    assert RealizationDefinition.model_validate(payload).benchmark.identifier == BenchmarkId(
        "db.lcmj20"
    )
    for foreign in (SUTId("sut.baseline-0"), StudyId("study.any"), RealizationId("rl.other")):
        with pytest.raises(ValidationError) as excinfo:
            RealizationDefinition.model_validate(
                {**payload, "benchmark": {"identifier": foreign, "version": "1.0.0"}}
            )
        assert "expected BenchmarkId" in str(excinfo.value)


def test_a_quantity_mapping_names_a_realization_local_source_and_never_an_object() -> None:
    mapping = quantity_mapping()
    assert mapping.source == "force_sensor_foot"
    assert isinstance(mapping.transform, NormalizationTransform)
    assert mapping.quantity == "q.foot.vertical_force"
    for token in ENGINE_NATIVE_TOKENS:
        assert token not in mapping.model_dump_json().lower()


@pytest.mark.parametrize("token", ENGINE_NATIVE_TOKENS)
def test_a_quantity_mapping_cannot_carry_an_engine_native_field(token: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        RealizationQuantityMapping.model_validate(
            {
                "quantity": "q.foot.vertical_force",
                "source": "force_sensor_foot",
                token: [0.0, 0.0],
            }
        )
    assert token in str(excinfo.value)


def test_a_realization_transform_is_named_and_versioned() -> None:
    transform = NormalizationTransform(name="sensor-nearest", version="1.0.0")
    assert transform.name == "sensor-nearest"
    with pytest.raises(ValidationError):
        NormalizationTransform(name="sensor-nearest", version="not-a-version")


def test_a_realization_asset_is_workspace_relative_and_never_absolute() -> None:
    asset = AssetReference(
        asset_id="subject-model",
        path="models/realization/subject.xml",
        description="Subject model.",
    )
    assert asset.sha256 is None
    for bad in ("C:/models/subject.xml", "/models/subject.xml", "../outside/subject.xml"):
        with pytest.raises(ValidationError):
            AssetReference(asset_id="subject-model", path=bad, description="Subject model.")


def test_engine_configuration_stays_a_realization_private_label_and_value() -> None:
    entry = ConfigurationEntry(name="integrator", value="implicitfast")
    assert entry.value == "implicitfast"
    with pytest.raises(ValidationError):
        ConfigurationEntry(name="integrator", value="has space")


def test_a_benchmark_release_embeds_its_own_frozen_authority() -> None:
    release = benchmark_release()
    assert release.quantities and release.scenarios and release.metrics
    assert release.intended_use and release.intended_non_use
    assert release.claim_ceiling
    assert release.credibility_hierarchy
    payload = release.model_dump(mode="json")
    assert payload["quantities"][0]["unit"]["expression"] == release.quantities[0].unit.expression


def test_a_release_needs_quantities_scenarios_and_metrics() -> None:
    base = benchmark_release().model_dump(mode="json")
    for field in ("quantities", "scenarios", "metrics"):
        payload = {**base, field: []}
        with pytest.raises(ValidationError):
            BenchmarkRelease.model_validate(payload)


def test_a_release_rejects_a_duplicate_identifier_inside_itself() -> None:
    base = benchmark_release().model_dump(mode="json")
    for field, key in (
        ("quantities", "quantity_id"),
        ("scenarios", "scenario_id"),
        ("metrics", "metric_id"),
        ("references", "reference_id"),
    ):
        payload = {**base, field: [base[field][0], base[field][0]]}
        with pytest.raises(ValidationError) as excinfo:
            BenchmarkRelease.model_validate(payload)
        assert f"duplicate {key}" in str(excinfo.value)


def test_a_scenario_may_not_assign_an_undeclared_quantity() -> None:
    release = benchmark_release()
    broken = release.model_dump(mode="json")
    broken["scenarios"][0]["initial_conditions"][0]["quantity"] = "q.not-declared"
    with pytest.raises(ValidationError) as excinfo:
        BenchmarkRelease.model_validate(broken)
    assert "which the release does not declare" in str(excinfo.value)


def test_a_scenario_may_not_assign_a_quantity_in_a_contradictory_unit() -> None:
    release = benchmark_release()
    broken = release.model_dump(mode="json")
    broken["scenarios"][0]["initial_conditions"][0]["unit"] = {"expression": "m"}
    with pytest.raises(ValidationError) as excinfo:
        BenchmarkRelease.model_validate(broken)
    assert "but the release declares it in" in str(excinfo.value)


def test_a_scenario_may_assign_a_quantity_in_any_spelling_of_its_canonical_unit() -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    payload["scenarios"][0]["initial_conditions"][0]["unit"] = {"expression": "kg*m/s^2"}
    assert BenchmarkRelease.model_validate(payload).scenarios[0].initial_conditions[0].unit == (
        CanonicalUnit(expression="N")
    )


def test_a_metric_may_not_be_defined_over_an_undeclared_quantity() -> None:
    release = benchmark_release()
    broken = release.model_dump(mode="json")
    broken["metrics"][0]["quantity"] = "q.not-declared"
    with pytest.raises(ValidationError) as excinfo:
        BenchmarkRelease.model_validate(broken)
    assert "which the release does not declare" in str(excinfo.value)


def test_a_reference_may_not_point_at_an_undeclared_scenario() -> None:
    release = benchmark_release()
    broken = release.model_dump(mode="json")
    broken["references"][0]["scenario_id"] = "sc.not-declared"
    with pytest.raises(ValidationError) as excinfo:
        BenchmarkRelease.model_validate(broken)
    assert "which the release does not declare" in str(excinfo.value)


def test_a_release_may_omit_references_only_when_it_declares_none_at_all() -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    assert BenchmarkRelease.model_validate({**payload, "references": []}).references == ()


def test_the_credibility_hierarchy_must_ascend_the_ladder() -> None:
    release = benchmark_release()
    payload = release.model_dump(mode="json")
    payload["credibility_hierarchy"] = [
        CredibilityLevel.COMPLETE_SYSTEM.value,
        CredibilityLevel.UNIT_PROBLEM.value,
    ]
    with pytest.raises(ValidationError) as excinfo:
        BenchmarkRelease.model_validate(payload)
    assert "ascending subsequence" in str(excinfo.value)
    payload["credibility_hierarchy"] = [
        CredibilityLevel.UNIT_PROBLEM.value,
        CredibilityLevel.UNIT_PROBLEM.value,
    ]
    with pytest.raises(ValidationError):
        BenchmarkRelease.model_validate(payload)
    assert [level.value for level in CREDIBILITY_LADDER] == [
        "unit_problem",
        "benchmark_reference_case",
        "subsystem_case",
        "complete_system",
    ]


def test_a_release_never_serialises_an_engine_native_token() -> None:
    payload = benchmark_release().model_dump_json().lower()
    realization_payload = realization_definition().model_dump_json().lower()
    for token in ENGINE_NATIVE_TOKENS:
        assert token not in payload
        assert token not in realization_payload


def test_the_five_adr_002_concepts_have_distinct_identities_across_real_models() -> None:
    release = benchmark_release()
    realization = realization_definition()
    sut = sut_definition()
    assert isinstance(release.benchmark_id, BenchmarkId)
    assert isinstance(realization.realization_id, RealizationId)
    assert isinstance(sut.sut_id, SUTId)
    assert type(release.benchmark_id) is not type(realization.realization_id)
    assert type(realization.realization_id) is not type(sut.sut_id)
    assert type(sut.sut_id) is not type(StudyId("study.any"))


@given(
    quantity_id=st.sampled_from(["q.foot.vertical_force", "q.jump.height"]),
    value=st.floats(allow_nan=False, allow_infinity=False, width=32),
)
def test_an_initial_condition_accepts_any_finite_value_in_the_declared_unit(
    quantity_id: str, value: float
) -> None:
    assignment = quantity_assignment(quantity=quantity_id, value=value)
    assert assignment.value == pytest.approx(value)
    assert isinstance(assignment.unit, CanonicalUnit)
    assert isinstance(assignment, QuantityAssignment)


def test_a_scenario_capability_requirement_is_keyed() -> None:
    scenario = scenario_definition()
    assert scenario.required_capabilities[0].capability is Capability.FORWARD_DYNAMICS
    with pytest.raises(ValidationError) as excinfo:
        ScenarioDefinition.model_validate(
            {
                **scenario_definition().model_dump(mode="json"),
                "required_capabilities": [
                    capability_requirement(Capability.ANALYSIS).model_dump(mode="json"),
                    capability_requirement(Capability.ANALYSIS).model_dump(mode="json"),
                ],
            }
        )
    assert "duplicate capability" in str(excinfo.value)
