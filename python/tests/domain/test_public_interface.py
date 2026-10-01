"""The public domain interface carries no engine-native type (ADR-001).

The strongest available guarantee is structural rather than textual: every field of
every exported definition is walked and its annotation must resolve to a closed set of
kinds. A ``qpos``, a ``State``, a Gym observation space, an ``Any``, or a bare
``object`` therefore cannot appear in a public domain type without this gate failing,
whatever it is called.
"""

from __future__ import annotations

import types
import typing
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

import dynamisbench.domain.spec as spec
from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.domain.spec.identifiers import Identifier

from .factories import ENGINE_NATIVE_TOKENS
from .test_corpus import exported_models, snake_case

ALLOWED_SCALARS = (str, int, float, bool, type(None))


KEYED_COLLECTIONS = ("quantities", "scenarios", "metrics", "references")


def _is_allowed(annotation: Any) -> bool:
    if annotation is Ellipsis:
        return True
    if isinstance(annotation, typing.TypeVar):
        return annotation.__bound__ is None or _is_allowed(annotation.__bound__)
    if hasattr(annotation, "__metadata__"):
        return _is_allowed(annotation.__origin__)
    origin = get_origin(annotation)
    if origin is typing.Literal:
        return all(isinstance(argument, (str, int, bool)) for argument in get_args(annotation))
    if origin is Union or origin is types.UnionType:
        return all(_is_allowed(argument) for argument in get_args(annotation))
    if origin is tuple:
        return all(_is_allowed(argument) for argument in get_args(annotation))
    if origin is not None:
        return False
    if isinstance(annotation, type):
        if issubclass(annotation, DomainModel):
            return True
        if issubclass(annotation, Identifier):
            return True
        if issubclass(annotation, str) and hasattr(annotation, "__members__"):
            return True
        return annotation in ALLOWED_SCALARS
    return False


@pytest.mark.parametrize("class_name", sorted(exported_models()), ids=sorted(exported_models()))
def test_every_exported_definition_is_frozen_and_forbids_extra_fields(
    class_name: str,
) -> None:
    model = exported_models()[class_name]
    assert model.model_config.get("frozen") is True
    assert model.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("class_name", sorted(exported_models()), ids=sorted(exported_models()))
def test_every_exported_field_has_a_closed_engine_independent_type(class_name: str) -> None:
    model = exported_models()[class_name]
    for field_name, field in model.model_fields.items():
        assert _is_allowed(field.annotation), (
            f"{class_name}.{field_name} is annotated {field.annotation!r}, which is not a "
            "closed set of scalars, string enums, nominal identifiers, or domain models"
        )


@pytest.mark.parametrize("class_name", sorted(exported_models()), ids=sorted(exported_models()))
def test_no_exported_field_or_type_carries_an_engine_native_name(class_name: str) -> None:
    model = exported_models()[class_name]
    haystack = f"{class_name} {' '.join(model.model_fields)}".lower()
    for token in ENGINE_NATIVE_TOKENS:
        assert token not in haystack, f"{class_name} exposes {token!r}"


def test_no_exported_definition_uses_any_object_or_arbitrary_type() -> None:
    for class_name, model in exported_models().items():
        hints = typing.get_type_hints(model)
        for field_name, hint in hints.items():
            rendered = str(hint).lower()
            assert "typing.any" not in rendered, f"{class_name}.{field_name} is Any"
            assert "<class 'object'>" not in rendered, f"{class_name}.{field_name} is object"
            assert "dict[" not in rendered, f"{class_name}.{field_name} is an open mapping"
            assert "callable" not in rendered, f"{class_name}.{field_name} is a callable"


def test_every_exported_definition_is_reachable_from_the_package_root() -> None:
    for class_name in exported_models():
        assert hasattr(spec, class_name)
        assert class_name in spec.__all__


def test_the_public_surface_declares_no_module_level_engine_import() -> None:
    for value in vars(spec).values():
        if isinstance(value, type) and issubclass(value, BaseModel):
            assert value.__module__.startswith("dynamisbench.domain.spec")


def test_every_required_concept_is_a_distinct_exported_type() -> None:
    from .test_corpus import REQUIRED_CONCEPTS

    models = exported_models()
    for concept in REQUIRED_CONCEPTS:
        assert concept in models, f"{concept} is not an exported definition"
        assert snake_case(concept) in {snake_case(name) for name in models}
