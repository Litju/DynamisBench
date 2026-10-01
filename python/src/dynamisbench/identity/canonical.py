"""RFC 8785 canonical JSON bytes.

This module is the whole of DynamisBench's dependence on JSON canonicalisation
(ADR-006). It is deliberately narrow: it accepts a value that is already
JSON-compatible and returns that value's RFC 8785 canonical UTF-8 bytes, or it
fails closed. It knows nothing about the domain model, because the semantic
boundary — deciding what a validated definition *means* — belongs to
:mod:`dynamisbench.identity.semantic` and is established before canonicalisation is
reached. Canonicalisation must never silently redefine domain semantics; in
particular it sorts object properties and never reorders arrays.

The implementation is ``rfc8785``: a pure-Python RFC 8785 implementation with no
runtime dependencies and no compiled extension, so the canonical bytes cannot
depend on a platform-specific native number formatter. It was adopted only after
being evaluated against the specification's own vectors — RFC 8785 sections
3.2.2 to 3.2.4 and the Appendix B number table — which
``tests/identity/test_rfc8785_conformance.py`` reproduces. Writing a second,
locally audited ECMAScript ``Number::toString`` would put the entire semantic
identity of the project behind untested floating-point formatting.
"""

from __future__ import annotations

from collections.abc import Mapping

import rfc8785

type JsonValue = (
    None
    | bool
    | int
    | float
    | str
    | list[JsonValue]
    | tuple[JsonValue, ...]
    | Mapping[str, JsonValue]
)
"""A JSON value in I-JSON shape: the only input this layer accepts.

Sequences are spelled out rather than taken as ``Sequence`` so that ``str`` and
``bytes`` can never be mistaken for a JSON array; ``bytes`` has no JSON
representation at all and must reach canonicalisation as raw asset bytes for
:mod:`dynamisbench.identity.digests` to hash instead.
"""


class CanonicalizationError(ValueError):
    """A value has no RFC 8785 canonical form.

    Canonicalisation fails closed. DynamisBench never falls back to a
    non-canonical or best-effort serialisation, and never returns a digest
    computed over bytes that are not canonical, because such a digest is not an
    identity: it would depend on the serialiser rather than on the meaning.
    """


def canonical_bytes(value: JsonValue) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of ``value``.

    The result is the unique shortest byte string RFC 8785 defines for the value:
    no insignificant whitespace, object properties sorted by UTF-16 code unit
    recursively, array order preserved, ECMAScript number formatting, and
    ``\\b``/``\\t``/``\\n``/``\\f``/``\\r``/``\\uXXXX`` string escaping.

    :raises CanonicalizationError: if the value is not I-JSON, contains a number
        with no JSON form (NaN, infinity, a value outside the IEEE 754 double
        range, or an integer outside the safe-integer range), contains a lone
        surrogate, uses a non-``str`` object key, or nests too deeply.
    """
    try:
        return rfc8785.dumps(value)
    except rfc8785.CanonicalizationError as error:
        raise CanonicalizationError(str(error)) from error
    except RecursionError as error:
        raise CanonicalizationError("value nests too deeply for canonical serialisation") from error
