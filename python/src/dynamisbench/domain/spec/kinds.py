"""The neutral registry of authority kinds: one name, one model, one identity.

Every DynamisBench definition has a *kind* — a stable word that names what a
validated object is without saying where it was read from: ``benchmark``,
``realization``, ``scenario``, ``quantity``, ``metric``, ``reference``, ``sut``,
``environment``, ``study``, ``factor``. This module is the one place that says which
existing Pydantic model a kind validates to, which field carries its human
identity, and whether it has a version at all.

**Why it is domain-owned.** The three consumers are a command line, a workspace
source reader, and an HTTP boundary, and none of them may own this table:

* ``dbench spec validate --kind`` needs to name ten kinds;
* the workspace source-authority reader must decide which model a declared
  directory segment validates to, and must not invent a second mapping;
* the application API must present a validated artifact's identifier and version,
  and must not be the layer that knows which field they live in.

An earlier arrangement put the table in ``cli_support``, which forced the other two
to depend on the command line. That is why this table lives here: the domain owns
the vocabulary, and every layer above it reads it.

**A kind names a model, never an import path.** The mapping is data, written out in
this file, and there is no mechanism by which a caller could supply a dotted path
and have the process import it. A registry that resolved strings to classes is a
code-execution primitive wearing a data structure's clothes.

**The version field is optional because one kind genuinely has none.**
:class:`~dynamisbench.domain.spec.studies.UncertaintyFactorDefinition` is
``factor_id`` and meaning; it has no independent release line, so its identity is
the identifier alone. Every other kind is independently versioned under ADR-002, and
saying so in data rather than in a per-call-site ``if`` is what keeps a fifth
version-less kind from being discovered by inspection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.benchmark import BenchmarkRelease
from dynamisbench.domain.spec.environment import EnvironmentDefinition
from dynamisbench.domain.spec.metrics import MetricDefinition
from dynamisbench.domain.spec.quantities import QuantityDefinition
from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.domain.spec.references import ReferenceDefinition
from dynamisbench.domain.spec.scenarios import ScenarioDefinition
from dynamisbench.domain.spec.studies import StudyDefinition, UncertaintyFactorDefinition
from dynamisbench.domain.spec.sut import SUTDefinition

__all__ = [
    "AUTHORITY_KIND_NAMES",
    "AUTHORITY_KINDS",
    "AuthorityKind",
    "UnknownAuthorityKindError",
    "authority_kind",
]


class UnknownAuthorityKindError(LookupError):
    """A caller named a kind this registry does not define.

    A ``LookupError`` rather than a bare ``KeyError`` so that a boundary reporting
    the refusal cannot accidentally serialise a dictionary lookup, and rather than
    the domain's own error hierarchy because this is a programming error at the
    call site rather than a refused user input.
    """


@dataclass(frozen=True, slots=True)
class AuthorityKind:
    """One kind's validation surface and the location of its nominal identity.

    ``identifier_field`` and ``version_field`` are field names on the validated
    model. They are read here only by layers that already hold a validated model, so
    they cannot be used to reach anything but the identity that model declares.
    ``version_field`` is ``None`` for the one kind that has no version.
    """

    name: str
    model: type[DomainModel]
    identifier_field: str
    version_field: str | None


AUTHORITY_KINDS: Final[Mapping[str, AuthorityKind]] = MappingProxyType(
    {
        "benchmark": AuthorityKind("benchmark", BenchmarkRelease, "benchmark_id", "version"),
        "environment": AuthorityKind(
            "environment", EnvironmentDefinition, "environment_id", "version"
        ),
        "factor": AuthorityKind("factor", UncertaintyFactorDefinition, "factor_id", None),
        "metric": AuthorityKind("metric", MetricDefinition, "metric_id", "version"),
        "quantity": AuthorityKind("quantity", QuantityDefinition, "quantity_id", "version"),
        "realization": AuthorityKind(
            "realization", RealizationDefinition, "realization_id", "version"
        ),
        "reference": AuthorityKind("reference", ReferenceDefinition, "reference_id", "version"),
        "scenario": AuthorityKind("scenario", ScenarioDefinition, "scenario_id", "version"),
        "study": AuthorityKind("study", StudyDefinition, "study_id", "version"),
        "sut": AuthorityKind("sut", SUTDefinition, "sut_id", "version"),
    }
)
"""The complete kind vocabulary, in a read-only mapping.

Sorted by name rather than grouped by concept, so that iterating it produces a
stable order without a caller imposing one, and immutable so that a consumer cannot
add a kind for the duration of one request and make two clients disagree about what
exists. Every key equals its :attr:`AuthorityKind.name`; the table is checked
against that in the qualification suite rather than assumed.
"""


AUTHORITY_KIND_NAMES: Final[tuple[str, ...]] = tuple(AUTHORITY_KINDS)
"""The vocabulary in the same order as :data:`AUTHORITY_KINDS`."""


def authority_kind(name: str) -> AuthorityKind:
    """Return the declared kind called ``name``.

    :raises UnknownAuthorityKindError: for any name this registry does not define. A
        caller may not fall back to a default, because the whole point of a closed
        vocabulary is that a kind nobody declared has no model to validate against.
    """
    try:
        return AUTHORITY_KINDS[name]
    except KeyError:
        raise UnknownAuthorityKindError(f"unknown authority kind: {name!r}") from None
