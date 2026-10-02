"""Exact reference resolution: a human reference plus the content it resolved to.

``domain.spec`` states references as a nominal identifier and a version
(:class:`~dynamisbench.domain.spec.identifiers.VersionedRef`). That is the right
authoring form and the wrong execution form: an identifier and a version name an
*artifact*, and an artifact can be amended in place. A plan may not be allowed to
discover at run time that the artifact moved, so planning resolves every reference
against the definitions it was handed and binds the result to
:func:`~dynamisbench.identity.semantic_sha256` of that exact definition's meaning.

The resolved form is therefore deliberately two things at once —

    ``ResolvedRef`` — the human reference *and* the semantic digest,

and there is no third form. In particular there is no "resolved by identifier
alone" form, no ``latest``, and no fallback: resolution returns either exactly one
definition with the stated identifier *and* version, or an error.

The catalog is a value object. :class:`PlanningContext` is built from the
definitions the caller already holds, is frozen, and holds no registry, no
repository, no cache, and no lookup that can change between two calls with the same
argument. Two identical calls therefore resolve to identical digests, which is the
property every later stage of planning depends on (ADR-004: authority is artifacts,
not a control plane).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from pydantic import field_validator

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.identifiers import (
    BenchmarkId,
    BenchmarkRef,
    EnvironmentId,
    EnvironmentRef,
    Identifier,
    QuantityId,
    RealizationId,
    RealizationRef,
    ScenarioId,
    StudyId,
    SUTId,
    SUTRef,
    Version,
    VersionedRef,
)
from dynamisbench.domain.spec.quantities import QuantityDefinition
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition
from dynamisbench.domain.spec.sut import SUTDefinition
from dynamisbench.identity import SemanticDigest, semantic_sha256
from dynamisbench.planning.errors import AuthorityResolutionError

DefinitionT = TypeVar("DefinitionT", bound=DomainModel)
IdentifierT = TypeVar("IdentifierT", bound=Identifier)


class ResolvedRef[IdentifierT: Identifier](DomainModel):
    """A human reference bound to the exact content identity it resolved to.

    Both halves travel together and neither replaces the other. The identifier and
    version are what a person reads and what an artifact is *named*; the semantic
    digest is what proves the named artifact is the one that was resolved. An
    authoritative reference therefore states ``identifier``, ``version`` and
    ``semantic_digest`` side by side, exactly as :mod:`dynamisbench.identity`
    requires.

    The identifier type parameter keeps the concepts apart: a ``ResolvedRef[SUTId]``
    cannot be supplied where a ``ResolvedRef[RealizationId]`` is required, so
    resolution cannot quietly reinterpret one authority as another (ADR-002).
    """

    identifier: IdentifierT
    version: Version
    semantic_digest: SemanticDigest


ResolvedBenchmarkRef = ResolvedRef[BenchmarkId]
ResolvedRealizationRef = ResolvedRef[RealizationId]
ResolvedSUTRef = ResolvedRef[SUTId]
ResolvedEnvironmentRef = ResolvedRef[EnvironmentId]
ResolvedScenarioRef = ResolvedRef[ScenarioId]
ResolvedQuantityRef = ResolvedRef[QuantityId]
ResolvedStudyRef = ResolvedRef[StudyId]
"""The resolved references this package produces, one per independently versioned concept."""


class ResolvedAuthority[DefinitionT: DomainModel, IdentifierT: Identifier](DomainModel):
    """One validated definition together with its exact content identity.

    Resolution has to hand back two things at once: the definition, because the
    planner reads its scenarios, capabilities, units and mappings; and the resolved
    reference, because the plan must record *what it read* rather than trust that
    the caller still holds the same object later.
    """

    definition: DefinitionT
    reference: ResolvedRef[IdentifierT]


def _index_by_identity[DefinitionT: DomainModel, IdentifierT: Identifier](
    definitions: Iterable[DefinitionT],
    *,
    identifier_of: Callable[[DefinitionT], IdentifierT],
    version_of: Callable[[DefinitionT], Version],
    concept: str,
) -> tuple[DefinitionT, ...]:
    """Reject duplicate ``(identifier, version)`` pairs and impose canonical order.

    The canonical order is by identifier then version *as strings*. It is
    deliberately not Semantic Versioning precedence: the domain deliberately defines
    no precedence, and inventing one for ordering would give plans an ordering rule
    the authority never stated. Every collection the domain model declares keyed is
    already canonicalised by :func:`~dynamisbench.domain.spec.base.keyed_by`, and the
    catalog follows the same rule for the same reason: two authorings of one catalog
    must be indistinguishable here too.
    """

    indexed: dict[tuple[str, str], DefinitionT] = {}
    for definition in definitions:
        key = (str(identifier_of(definition)), str(version_of(definition)))
        if key in indexed:
            raise ValueError(
                f"the planning context supplies {concept} {key[0]} version {key[1]} twice; "
                "every reference must resolve to exactly one definition"
            )
        indexed[key] = definition
    return tuple(indexed[key] for key in sorted(indexed))


def _resolve_reference[DefinitionT: DomainModel, IdentifierT: Identifier](
    definitions: tuple[DefinitionT, ...],
    reference: VersionedRef[IdentifierT],
    *,
    identifier_of: Callable[[DefinitionT], IdentifierT],
    version_of: Callable[[DefinitionT], Version],
    concept: str,
) -> DefinitionT:
    """Resolve one versioned reference to exactly one definition, or refuse.

    The refusals are kept apart in the message because they are different mistakes:
    the context supplies no such concept at all, or supplies the identifier only at
    other versions. Neither may fall back to "the closest version" — that is how a
    plan silently drifts onto authority the study never named.
    """

    same_identifier = [
        definition
        for definition in definitions
        if identifier_of(definition) == reference.identifier
    ]
    if not same_identifier:
        raise AuthorityResolutionError(
            f"the study references {concept} {reference.identifier!r} version "
            f"{reference.version}, and the planning context supplies no {concept} with "
            "that identifier"
        )
    matching = [
        definition for definition in same_identifier if version_of(definition) == reference.version
    ]
    if not matching:
        available = sorted(str(version_of(item)) for item in same_identifier)
        raise AuthorityResolutionError(
            f"the study references {concept} {reference.identifier!r} version "
            f"{reference.version}, and the planning context supplies only version(s) "
            f"{available}; there is no implicit latest-version resolution"
        )
    if len(matching) != 1:
        raise AuthorityResolutionError(
            f"{concept} {reference.identifier!r} version {reference.version} resolved to "
            f"{len(matching)} definitions; exactly one is required"
        )
    return matching[0]


def _resolve_nested[DefinitionT: DomainModel, IdentifierT: Identifier](
    definitions: tuple[DefinitionT, ...],
    identifier: IdentifierT,
    *,
    identifier_of: Callable[[DefinitionT], IdentifierT],
    concept: str,
) -> DefinitionT:
    """Resolve a definition embedded in one benchmark release, or refuse.

    Scenarios and quantities have no independent catalog: they are embedded in the
    frozen release, which is exactly why a release can be trusted to be one
    artifact (VVUQ Workflow, Benchmark release). The release passed here is the exact
    one a plan is compiling, so the lookup cannot reach a different release.
    """

    matching = [item for item in definitions if identifier_of(item) == identifier]
    if not matching:
        raise AuthorityResolutionError(
            f"{concept} {identifier!r} is not declared by the benchmark release this plan is "
            "compiling, so it has no canonical unit, capability or coverage authority here"
        )
    if len(matching) != 1:
        raise AuthorityResolutionError(
            f"{concept} {identifier!r} resolved to {len(matching)} definitions inside one "
            "benchmark release; exactly one is required"
        )
    return matching[0]


class PlanningContext(DomainModel):
    """The immutable catalog of validated definitions a plan is compiled against.

    This is a value, not a store. It is constructed from the definitions the caller
    already has, it is frozen, it holds nothing that was not passed to it, and it
    offers no way to add, mutate, or observe what has been read. There is
    deliberately no registry service, no repository, and no container: the
    architecture forbids an authoritative control plane, and the only reason a plan
    needs to see more than one definition is that a study names more than one.

    A study may consume several versions of the same concept over its life, so the
    catalog is keyed by ``(identifier, version)`` rather than by identifier. Two
    definitions sharing both are refused at construction: duplicate authority makes
    the catalog's meaning ambiguous, and ambiguity is resolved by refusing rather than
    by picking one.

    The canonical order and the duplicate rule live in the field validators, so they
    apply once and at construction no matter how a catalog is built: a catalog supplied
    in one order and the same catalog supplied in another are one catalog.
    """

    benchmarks: tuple[BenchmarkRelease, ...] = ()
    realizations: tuple[RealizationDefinition, ...] = ()
    systems_under_test: tuple[SUTDefinition, ...] = ()
    environments: tuple[EnvironmentDefinition, ...] = ()

    @field_validator("benchmarks")
    @classmethod
    def _catalogue_benchmarks(
        cls, value: tuple[BenchmarkRelease, ...]
    ) -> tuple[BenchmarkRelease, ...]:
        return _index_by_identity(
            value,
            identifier_of=lambda release: release.benchmark_id,
            version_of=lambda release: release.version,
            concept="benchmark release",
        )

    @field_validator("realizations")
    @classmethod
    def _catalogue_realizations(
        cls, value: tuple[RealizationDefinition, ...]
    ) -> tuple[RealizationDefinition, ...]:
        return _index_by_identity(
            value,
            identifier_of=lambda definition: definition.realization_id,
            version_of=lambda definition: definition.version,
            concept="realization",
        )

    @field_validator("systems_under_test")
    @classmethod
    def _catalogue_systems_under_test(
        cls, value: tuple[SUTDefinition, ...]
    ) -> tuple[SUTDefinition, ...]:
        return _index_by_identity(
            value,
            identifier_of=lambda definition: definition.sut_id,
            version_of=lambda definition: definition.version,
            concept="system under test",
        )

    @field_validator("environments")
    @classmethod
    def _catalogue_environments(
        cls, value: tuple[EnvironmentDefinition, ...]
    ) -> tuple[EnvironmentDefinition, ...]:
        return _index_by_identity(
            value,
            identifier_of=lambda definition: definition.environment_id,
            version_of=lambda definition: definition.version,
            concept="execution environment",
        )

    def resolve_benchmark(
        self, reference: BenchmarkRef
    ) -> ResolvedAuthority[BenchmarkRelease, BenchmarkId]:
        """Resolve one benchmark release reference to its exact definition and digest."""
        definition = _resolve_reference(
            self.benchmarks,
            reference,
            identifier_of=lambda release: release.benchmark_id,
            version_of=lambda release: release.version,
            concept="benchmark release",
        )
        return ResolvedAuthority[BenchmarkRelease, BenchmarkId](
            definition=definition,
            reference=ResolvedBenchmarkRef(
                identifier=reference.identifier,
                version=reference.version,
                semantic_digest=semantic_sha256(definition),
            ),
        )

    def resolve_realization(
        self, reference: RealizationRef
    ) -> ResolvedAuthority[RealizationDefinition, RealizationId]:
        """Resolve one realization reference to its exact definition and digest."""
        definition = _resolve_reference(
            self.realizations,
            reference,
            identifier_of=lambda item: item.realization_id,
            version_of=lambda item: item.version,
            concept="realization",
        )
        return ResolvedAuthority[RealizationDefinition, RealizationId](
            definition=definition,
            reference=ResolvedRealizationRef(
                identifier=reference.identifier,
                version=reference.version,
                semantic_digest=semantic_sha256(definition),
            ),
        )

    def resolve_system_under_test(
        self, reference: SUTRef
    ) -> ResolvedAuthority[SUTDefinition, SUTId]:
        """Resolve one system-under-test reference to its exact definition and digest."""
        definition = _resolve_reference(
            self.systems_under_test,
            reference,
            identifier_of=lambda item: item.sut_id,
            version_of=lambda item: item.version,
            concept="system under test",
        )
        return ResolvedAuthority[SUTDefinition, SUTId](
            definition=definition,
            reference=ResolvedSUTRef(
                identifier=reference.identifier,
                version=reference.version,
                semantic_digest=semantic_sha256(definition),
            ),
        )

    def resolve_environment(
        self, reference: EnvironmentRef
    ) -> ResolvedAuthority[EnvironmentDefinition, EnvironmentId]:
        """Resolve one environment reference to its exact definition and digest."""
        definition = _resolve_reference(
            self.environments,
            reference,
            identifier_of=lambda item: item.environment_id,
            version_of=lambda item: item.version,
            concept="execution environment",
        )
        return ResolvedAuthority[EnvironmentDefinition, EnvironmentId](
            definition=definition,
            reference=ResolvedEnvironmentRef(
                identifier=reference.identifier,
                version=reference.version,
                semantic_digest=semantic_sha256(definition),
            ),
        )

    def scenario_of(
        self, benchmark: BenchmarkRelease, scenario_id: ScenarioId
    ) -> ResolvedAuthority[ScenarioDefinition, ScenarioId]:
        """Resolve one scenario inside an already-resolved benchmark release.

        The release declares its scenarios through
        :func:`~dynamisbench.domain.spec.base.keyed_by`, which stores them in canonical
        identifier order and refuses duplicate keys. Planning therefore relies on that
        order instead of re-sorting: a second sorting rule here would be a second
        definition of an order the domain already owns.
        """

        definition = _resolve_nested(
            benchmark.scenarios,
            scenario_id,
            identifier_of=lambda scenario: scenario.scenario_id,
            concept="scenario",
        )
        return ResolvedAuthority[ScenarioDefinition, ScenarioId](
            definition=definition,
            reference=ResolvedScenarioRef(
                identifier=scenario_id,
                version=definition.version,
                semantic_digest=semantic_sha256(definition),
            ),
        )

    def quantity_of(
        self, benchmark: BenchmarkRelease, quantity_id: QuantityId
    ) -> ResolvedAuthority[QuantityDefinition, QuantityId]:
        """Resolve one canonical quantity inside an already-resolved benchmark release."""
        definition = _resolve_nested(
            benchmark.quantities,
            quantity_id,
            identifier_of=lambda quantity: quantity.quantity_id,
            concept="canonical quantity",
        )
        return ResolvedAuthority[QuantityDefinition, QuantityId](
            definition=definition,
            reference=ResolvedQuantityRef(
                identifier=quantity_id,
                version=definition.version,
                semantic_digest=semantic_sha256(definition),
            ),
        )
