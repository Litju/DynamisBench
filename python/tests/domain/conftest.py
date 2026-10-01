"""Fixtures for the DB-1.2 domain qualification."""

from __future__ import annotations

import pytest

from dynamisbench.domain.spec.environment import EnvironmentDefinition

from .factories import environment_definition


@pytest.fixture
def valid_environment() -> EnvironmentDefinition:
    return environment_definition()
