"""Engine-independent execution capability vocabulary.

ADR-003 requires capability contracts rather than a universal ``reset()/step()``
abstraction. A realization advertises the capabilities it can provide; a scenario
or study declares the capabilities it needs. Planning fails before execution when
requirements cannot be satisfied, so this module carries vocabulary and validation
only — no adapter and no runtime execution.
"""

from __future__ import annotations

from enum import StrEnum

from dynamisbench.domain.spec.base import DomainModel, ShortText
from dynamisbench.domain.spec.identifiers import Name, VersionSpecifier


class Capability(StrEnum):
    """The capability families accepted by the engine/SUT execution contracts.

    The families mirror ``ForwardDynamicsBackend``, ``InteractiveDynamicsBackend``,
    ``StateSnapshotBackend``, ``AnalysisBackend``, ``InverseDynamicsBackend``, and
    ``TrajectoryOptimizationBackend``. They describe what an engine can do, never
    how it is called, so no engine-native call signature can leak into the model.
    """

    FORWARD_DYNAMICS = "forward_dynamics"
    INTERACTIVE_DYNAMICS = "interactive_dynamics"
    STATE_SNAPSHOT = "state_snapshot"
    ANALYSIS = "analysis"
    INVERSE_DYNAMICS = "inverse_dynamics"
    TRAJECTORY_OPTIMIZATION = "trajectory_optimization"


class CapabilityDeclaration(DomainModel):
    """A capability a realization advertises, with its stated limits.

    ``limitations`` records what the advertisement does *not* cover so that a
    requirement can be judged against a declared boundary instead of an assumption.
    """

    capability: Capability
    summary: ShortText
    limitations: tuple[ShortText, ...] = ()


class CapabilityRequirement(DomainModel):
    """A capability a scenario or study needs from whatever realises it.

    ``essential`` distinguishes a capability the study cannot proceed without from
    one it merely prefers. Either way the rationale must be stated, so a
    requirement is never an unexplained flag.
    """

    capability: Capability
    essential: bool = True
    rationale: ShortText


class EngineBinding(DomainModel):
    """The engine a realization is bound to.

    The engine is named by an identifier and a version constraint, never by an
    engine object, so this binding stays engine-independent (ADR-001). Capability
    advertisements, not engine identity, carry the scientific compatibility
    question.
    """

    engine: Name
    specifier: VersionSpecifier
    notes: ShortText | None = None
