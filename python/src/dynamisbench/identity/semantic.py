"""The semantic boundary: the meaning of a validated definition, and nothing else.

Everything DynamisBench hashes as *semantic identity* passes through here, and the
order is the whole point:

    validated Pydantic domain object
        -> semantic JSON-compatible representation   (this module)
        -> RFC 8785 canonical bytes                  (dynamisbench.identity.canonical)
        -> SHA-256                                   (dynamisbench.identity.digests)

Only the middle stage is defined here, and its job is narrow: to turn validated
meaning into a JSON-compatible value, and to reject anything that has none.

**Authoring syntax is not meaning.** YAML text, indentation, comments, key order, and
pretty-printing never reach this stage, because a validated domain object has already
discarded them. What *is* part of meaning is preserved exactly:

* **Object property order is irrelevant.** RFC 8785 sorts properties recursively, so
  the order a document was authored in cannot change a digest.
* **Array order is meaning.** This module never reorders a sequence. The domain model
  decides which collections are order-insensitive and it decides it at validation
  time: a keyed collection is stored in canonical key order and rejects duplicate keys,
  so two authorings of one set arrive here already identical. A genuinely ordered
  field — a rotation sequence, a credibility hierarchy, a list of notes, a command
  line — keeps its authored order and keeps its identity with it. Canonicalisation must
  not quietly redefine domain semantics, so the reordering rule lives in the domain layer
  where it is reviewed as domain, not here where it would be invisible.
* **A path is not content.** Nothing here reads the filesystem, the clock, the
  environment, or a random source, so no artifact of the machine that produced a digest
  can enter it. Referenced files are identified by :mod:`dynamisbench.identity.digests`
  over their raw bytes instead.

**Negative zero is decided here, deliberately.** RFC 8785 serialises numbers with the
ECMAScript ``Number::toString`` algorithm, under which ``-0`` and ``0`` are one value
and both serialise as ``0``; the RFC's verified technical errata records the resulting
ambiguity about negative-zero *input*. RES-228 validated that every domain number is a
finite ``float`` and did not decide what the sign of zero means, so the decision falls
to this boundary and is made explicitly rather than inherited:

    Negative zero is not a distinct scientific value anywhere in the DynamisBench
    domain. No field has a sign-of-zero convention; a zero ground reaction force, a
    zero window start, and a zero held factor mean the same thing written with a
    minus sign or without one. ``-0.0`` is therefore *normalised to* ``0.0`` here,
    and two authorings that differ only in the sign of a zero are one meaning with one
    digest.

The alternative — failing closed on ``-0.0`` — was rejected because it would leave a
perfectly valid validated definition with no identity at all. Emitting ``-0`` was
rejected because it is not RFC 8785 and would give two values that compare *equal* in
Python two different digests, breaking the determinism of
``digest(validate(dump(x))) == digest(x)``. The rule is a single explicit predicate
below rather than an incidental property of the serialiser, and
``tests/identity/test_semantic.py`` proves it is ours.

Every other number is either an exact IEEE 754 double or is rejected. There is no
tolerance, no rounding, and no best-effort fallback: a value that has no canonical form
has no identity, and identity that cannot be established is reported rather than
guessed.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from typing import Final

from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.identity.canonical import (
    CanonicalizationError,
    JsonValue,
    canonical_bytes,
)
from dynamisbench.identity.digests import SemanticDigest, semantic_sha256_of_canonical_bytes

SemanticValue = DomainModel | JsonValue
"""What may be given a semantic identity.

Either a validated DynamisBench domain object, or the JSON-compatible normalized
representation this module produces. Arbitrary Python objects are not accepted: there
is no fallback serialisation, because a digest over bytes that were produced by
whatever ``repr`` happened to yield is not an identity.
"""

NEGATIVE_ZERO_IS_NORMALISED: Final = True
"""Records the deliberate rule stated in the module docstring, so it is one line to
test and one line to change if a domain ever acquires a signed-zero convention."""


def _normalise_number(value: float) -> float:
    """Apply the one number rule this layer owns, and reject the rest.

    :raises CanonicalizationError: for a non-finite value, which has no JSON form.
    """
    if not math.isfinite(value):
        raise CanonicalizationError(f"number {value!r} is not finite and has no canonical form")
    if value == 0.0 and NEGATIVE_ZERO_IS_NORMALISED:
        return 0.0
    return value


def _string_keyed_items(value: Mapping[object, object]) -> Iterator[tuple[str, object]]:
    for key, item in value.items():
        if not isinstance(key, str):
            raise CanonicalizationError(
                f"an object of type {type(value).__name__!r} has a "
                f"{type(key).__name__!r} property name; a JSON property name is a string"
            )
        yield key, item


def semantic_representation(value: object) -> JsonValue:
    """Return the JSON-compatible representation of ``value``'s meaning.

    Accepts a validated domain object, or a value already in JSON shape. Sequences
    keep their order; properties keep whatever order they arrive in, because
    canonicalisation sorts them; numbers are checked for finiteness and for the
    negative-zero rule above.

    :raises CanonicalizationError: if any part of ``value`` has no semantic
        representation — an unsupported Python type, a non-``str`` property name, a
        non-finite number, or a lone surrogate.
    """
    if isinstance(value, DomainModel):
        # The validated domain object *is* the semantic representation; YAML and JSON
        # are authoring surfaces over it. A dump in JSON mode turns nominal
        # identifiers into plain strings, enums into their values, and tuples into
        # arrays, which is what makes the tree below uniform. Walking the result rather
        # than assuming it is done here means a future field type that serialises into
        # something JSON cannot express fails closed instead of being hashed blind.
        return semantic_representation(value.model_dump(mode="json"))
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _normalise_number(value)
    if isinstance(value, Mapping):
        return {key: semantic_representation(item) for key, item in _string_keyed_items(value)}
    if isinstance(value, list | tuple):
        return [semantic_representation(item) for item in value]
    raise CanonicalizationError(
        f"a value of type {type(value).__name__!r} has no semantic representation; "
        "semantic identity is computed over validated domain objects and JSON values only"
    )


def canonical_semantic_bytes(value: SemanticValue) -> bytes:
    """Return the RFC 8785 canonical bytes of ``value``'s validated meaning.

    This is the byte string a semantic digest is taken over. It is a function of the
    meaning alone: two definitions that differ only in whitespace, comments, property
    order, or the authoring order of a collection the domain model declared
    order-insensitive produce identical bytes, and two definitions that differ in any
    authoritative way do not.
    """
    return canonical_bytes(semantic_representation(value))


def semantic_sha256(value: SemanticValue) -> SemanticDigest:
    """Return the semantic digest of ``value``: the SHA-256 of its canonical bytes.

    The human identity of a definition — ``BenchmarkId``, ``Version``, ``SUTId`` — is
    not replaced by this value and is not derivable from it. The two travel together:
    an authoritative reference names an artifact for people and states its
    cryptographic identity alongside.
    """
    return semantic_sha256_of_canonical_bytes(canonical_semantic_bytes(value))
