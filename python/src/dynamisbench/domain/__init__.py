"""Scientific and execution domain packages.

``dynamisbench.domain.spec`` owns validated scientific and execution definitions
(BenchmarkRelease, RealizationDefinition, ScenarioDefinition, QuantityDefinition,
MetricDefinition, ReferenceDefinition, SUTDefinition, EnvironmentDefinition,
StudyDefinition, UncertaintyFactorDefinition).

Each of those is an independently identified and versioned domain object (ADR-002).
Engine-native classes never appear in the public domain model (ADR-001). The
definitions themselves arrive with DB-1.2 (RES-228); DB-1.1 provides the boundary.
"""
