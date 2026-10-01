"""RFC 8785 conformance for the canonical-identity boundary (ADR-006).

Every expectation here is transcribed from RFC 8785 itself, not from DynamisBench's
own output, so a change of library - or a broken library - fails this gate instead of
quietly redefining the semantic identity of every validated definition in the project:

* sections 3.2.2 / 3.2.3: the specification's worked example and its canonical form;
* section 3.2.4: the same output as the hexadecimal UTF-8 byte string the
  specification publishes, which is what makes canonical bytes safe to digest;
* section 3.2.3: the property-sorting test data and its required argument order, which
  is UTF-16 code-unit order and therefore differs from both byte order and locale
  order;
* Appendix B: the ECMAScript number-serialisation table, as IEEE 754 bit patterns, so
  the exponent and shortest-round-trip rules are exercised directly;
* Appendix D and E: a number with no JSON form, and JSON strings that carry a subtype;
* sections 3.2.2.2 / 3.2.2.3: string escaping, and the mandatory failure on NaN,
  infinity and lone surrogates.

The whole of the upstream package's suite is deliberately not duplicated; only the
behaviour DynamisBench's identity layer relies on is pinned. In particular the
negative-zero behaviour is asserted here as an *input* to a decision that
:mod:`dynamisbench.identity.semantic` makes explicitly, not merely one it inherits.

Code points are written as ``chr(...)`` rather than as literal characters so that this
file stays pure ASCII and no invisible control character can hide in it.
"""

from __future__ import annotations

import json
import math
import struct
from typing import Any

import pytest

from dynamisbench.identity import CanonicalizationError, canonical_bytes

# RFC 8785 section 3.2.2, the parsed input, verbatim in its source spellings. The
# author wrote 1E30, 4.50, 2e-3 and a 25-digit decimal; the canonical form rounds and
# reformats all of them.
RFC_SECTION_3_2_2_INPUT = json.loads(
    '{"numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],'
    ' "string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
    ' "literals": [null, true, false]}'
)

RFC_SECTION_3_2_3_CANONICAL = (
    b'{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
    b'"string":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
)

RFC_SECTION_3_2_4_HEX = (
    "7b 22 6c 69 74 65 72 61 6c 73 22 3a 5b 6e 75 6c 6c 2c 74 72 "
    "75 65 2c 66 61 6c 73 65 5d 2c 22 6e 75 6d 62 65 72 73 22 3a "
    "5b 33 33 33 33 33 33 33 33 33 2e 33 33 33 33 33 33 33 2c 31 "
    "65 2b 33 30 2c 34 2e 35 2c 30 2e 30 30 32 2c 31 65 2d 32 37 "
    "5d 2c 22 73 74 72 69 6e 67 22 3a 22 e2 82 ac 24 5c 75 30 30 "
    "30 66 5c 6e 41 27 42 5c 22 5c 5c 5c 5c 5c 22 2f 22 7d"
)

# RFC 8785 section 3.2.3: "The following JSON test data can be used for verifying the
# correctness of the sorting scheme in a JCS implementation", followed by the required
# order of the values. The specification writes the property names as JSON escapes.
RFC_SORT_INPUT = {
    chr(codepoint): label
    for codepoint, label in (
        (0x20AC, "Euro Sign"),
        (0x000D, "Carriage Return"),
        (0xFB33, "Hebrew Letter Dalet With Dagesh"),
        (0x0031, "One"),
        (0x1F600, "Emoji: Grinning Face"),
        (0x0080, "Control"),
        (0x00F6, "Latin Small Letter O With Diaeresis"),
    )
}

RFC_SORT_ORDER = (
    "Carriage Return",
    "One",
    "Control",
    "Latin Small Letter O With Diaeresis",
    "Euro Sign",
    "Emoji: Grinning Face",
    "Hebrew Letter Dalet With Dagesh",
)

# RFC 8785 Appendix B, Table 1: "ECMAScript-Compatible JSON Number Serialization
# Samples". The two rows with an empty JSON Representation (NaN, Infinity) are handled
# separately, because the specification requires them to fail rather than serialise.
RFC_APPENDIX_B = (
    ("0000000000000000", "0", "zero"),
    ("8000000000000000", "0", "minus-zero"),
    ("0000000000000001", "5e-324", "min-positive-subnormal"),
    ("8000000000000001", "-5e-324", "min-negative-subnormal"),
    ("7fefffffffffffff", "1.7976931348623157e+308", "max-positive"),
    ("ffefffffffffffff", "-1.7976931348623157e+308", "max-negative"),
    ("4340000000000000", "9007199254740992", "max-positive-integer"),
    ("c340000000000000", "-9007199254740992", "max-negative-integer"),
    ("4430000000000000", "295147905179352830000", "approx-2**68"),
    ("44b52d02c7e14af5", "9.999999999999997e+22", "shortest-of-a"),
    ("44b52d02c7e14af6", "1e+23", "exponent-transition"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23", "exponent-transition-neighbour"),
    ("444b1ae4d6e2ef4e", "999999999999999700000", "large-integer-form-a"),
    ("444b1ae4d6e2ef4f", "999999999999999900000", "large-integer-form-b"),
    ("444b1ae4d6e2ef50", "1e+21", "exponent-transition-1e21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7", "small-a"),
    ("3eb0c6f7a0b5ed8d", "0.000001", "small-b"),
    ("41b3de4355555553", "333333333.3333332", "shortest-round-trip-a"),
    ("41b3de4355555554", "333333333.33333325", "shortest-round-trip-b"),
    ("41b3de4355555555", "333333333.3333333", "shortest-round-trip-c"),
    ("41b3de4355555556", "333333333.3333334", "shortest-round-trip-d"),
    ("41b3de4355555557", "333333333.33333343", "shortest-round-trip-e"),
    ("becbf647612f3696", "-0.0000033333333333333333", "small-negative"),
    ("43143ff3c1cb0959", "1424953923781206.2", "round-to-even"),
)

RFC_APPENDIX_B_IDS = [identifier for _, _, identifier in RFC_APPENDIX_B]

# U+00E9 U+20AC U+1F600 encoded as UTF-8: a two-byte, a three-byte, and a four-byte
# sequence, none of which may be escaped in canonical output.
NON_ASCII_UTF8 = bytes((0xC3, 0xA9, 0xE2, 0x82, 0xAC, 0xF0, 0x9F, 0x98, 0x80))


def _double(bits: str) -> float:
    return struct.unpack(">d", struct.pack(">Q", int(bits, 16)))[0]


def _rejects(value: Any) -> None:
    """Assert that ``value`` has no canonical form at all."""
    with pytest.raises(CanonicalizationError):
        canonical_bytes(value)


def test_section_3_2_3_canonicalises_the_specifications_own_example() -> None:
    assert canonical_bytes(RFC_SECTION_3_2_2_INPUT) == RFC_SECTION_3_2_3_CANONICAL


def test_section_3_2_4_reproduces_the_specified_utf8_byte_string() -> None:
    canonical = canonical_bytes(RFC_SECTION_3_2_2_INPUT)
    assert canonical.hex() == RFC_SECTION_3_2_4_HEX.replace(" ", "")


def test_section_3_2_1_canonical_output_has_no_insignificant_whitespace() -> None:
    canonical = canonical_bytes(RFC_SECTION_3_2_2_INPUT).decode("utf-8")
    assert canonical == canonical.strip()
    assert ": " not in canonical
    assert ", " not in canonical


def test_section_3_2_3_sorts_properties_in_utf16_code_unit_order() -> None:
    """UTF-16 code-unit order is neither byte order nor locale order, which is why the
    specification publishes this particular set of property names."""
    values = json.loads(canonical_bytes(RFC_SORT_INPUT).decode("utf-8"))
    assert tuple(values.values()) == RFC_SORT_ORDER


def test_object_properties_sort_recursively_and_arrays_keep_their_order() -> None:
    assert canonical_bytes({"a": {"d": 1, "b": 2}, "c": [{"f": 1, "e": 2}]}) == (
        b'{"a":{"b":2,"d":1},"c":[{"e":2,"f":1}]}'
    )
    assert canonical_bytes([3, 1, 2]) == b"[3,1,2]"
    assert canonical_bytes(["b", "a"]) == b'["b","a"]'


@pytest.mark.parametrize(("bits", "expected", "identifier"), RFC_APPENDIX_B, ids=RFC_APPENDIX_B_IDS)
def test_appendix_b_number_serialisation(bits: str, expected: str, identifier: str | None) -> None:
    assert canonical_bytes(_double(bits)).decode("ascii") == expected


@pytest.mark.parametrize(
    "value", [math.nan, math.inf, -math.inf], ids=["nan", "positive-infinity", "negative-infinity"]
)
def test_appendix_b_rows_with_no_json_representation_fail_closed(value: float) -> None:
    """RFC 8785 section 3.2.2.3: NaN and Infinity "MUST cause a compliant JCS
    implementation to terminate with an appropriate error"."""
    _rejects(value)


def test_appendix_b_collapses_negative_zero_onto_zero() -> None:
    """The specification's own table maps both IEEE 754 zero bit patterns to ``0``.

    That collapse is what makes negative zero a decision rather than an accident: an
    identity layer that inherits it without stating it has decided nothing. This test
    records only the inherited behaviour, so that a library change would be visible;
    :mod:`dynamisbench.identity.semantic` owns the deliberate decision.
    """
    assert canonical_bytes(_double("8000000000000000")) == canonical_bytes(0.0) == b"0"
    assert canonical_bytes({"v": -0.0}) == b'{"v":0}'


def test_appendix_d_a_number_beyond_the_double_range_fails_closed() -> None:
    """Appendix D's ``1.4e+9999`` is valid JSON *text* but not a valid JSON *number*;
    the specification's own remedy is to carry such a value as a string."""
    _rejects(json.loads("1.4e+9999"))
    assert canonical_bytes({"giantNumber": "1.4e+9999"}) == b'{"giantNumber":"1.4e+9999"}'


def test_appendix_e_a_json_string_keeps_its_subtype_payload_verbatim() -> None:
    """Appendix E: canonicalisation must not reinterpret a string that a schema chose
    to carry a BigInt or DateTime subtype in."""
    value = {"time": "2019-01-28T07:45:10Z", "big": "055", "val": 3.5}
    assert canonical_bytes(value) == b'{"big":"055","time":"2019-01-28T07:45:10Z","val":3.5}'


def test_section_3_2_2_2_escapes_only_the_characters_the_specification_names() -> None:
    assert canonical_bytes({"s": "A'B\"C\\D/E"}) == b'{"s":"A\'B\\"C\\\\D/E"}'
    assert canonical_bytes({"s": "\b\t\n\f\r"}) == b'{"s":"\\b\\t\\n\\f\\r"}'


def test_section_3_2_2_2_uses_lowercase_hexadecimal_for_the_other_control_characters() -> None:
    assert canonical_bytes({"s": chr(0x00) + chr(0x1F)}) == b'{"s":"\\u0000\\u001f"}'


def test_section_3_2_2_2_passes_non_ascii_through_as_utf8_rather_than_escaping_it() -> None:
    assert (
        canonical_bytes({"s": NON_ASCII_UTF8.decode("utf-8")}) == b'{"s":"' + NON_ASCII_UTF8 + b'"}'
    )


def test_section_3_2_2_2_requires_a_lone_surrogate_to_fail_closed() -> None:
    _rejects({"s": chr(0xD800)})


def test_section_3_2_2_1_literals_serialise_exactly_as_named() -> None:
    assert canonical_bytes([None, True, False]) == b"[null,true,false]"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (1, 1.0),
        (-0, 0.0),
        (-0.0, 0.0),
        (9007199254740991, 9007199254740991.0),
        (1e16, 10000000000000000.0),
        (0.1, 1e-1),
    ],
    ids=[
        "integer-and-double",
        "integer-and-negative-zero",
        "negative-zero-and-zero",
        "largest-safe-integer",
        "exponent-and-plain-form",
        "decimal-and-exponent-form",
    ],
)
def test_spellings_of_one_double_serialise_identically(
    first: int | float, second: int | float
) -> None:
    """JSON has exactly one number type, so two spellings of one double are one value
    and must never become two identities."""
    assert canonical_bytes(first) == canonical_bytes(second)


@pytest.mark.parametrize(
    "value", [2**53, -(2**53), 2**53 + 1, 10**30], ids=["2**53", "-2**53", "2**53+1", "10**30"]
)
def test_an_integer_outside_the_safe_integer_range_fails_closed(value: int) -> None:
    _rejects(value)


@pytest.mark.parametrize(
    "key", [1, 2.5, b"k", ("a", "b"), None, True], ids=lambda key: type(key).__name__
)
def test_an_object_key_that_is_not_a_string_fails_closed(key: Any) -> None:
    _rejects({key: "value"})


@pytest.mark.parametrize(
    "value",
    [b"bytes", bytearray(b"bytes"), {1, 2}, frozenset({1}), complex(1, 2), object()],
    ids=["bytes", "bytearray", "set", "frozenset", "complex", "object"],
)
def test_a_value_outside_the_json_type_system_fails_closed(value: Any) -> None:
    """There is no fallback serialisation. An arbitrary Python object has no semantic
    representation that DynamisBench is willing to hash."""
    _rejects(value)


def test_a_value_nested_past_the_recursion_limit_fails_closed_rather_than_crashing() -> None:
    nested: Any = "leaf"
    for _ in range(2000):
        nested = [nested]
    _rejects(nested)


def test_canonicalisation_is_idempotent_through_a_json_round_trip() -> None:
    canonical = canonical_bytes(RFC_SECTION_3_2_2_INPUT)
    assert canonical_bytes(json.loads(canonical.decode("utf-8"))) == canonical
