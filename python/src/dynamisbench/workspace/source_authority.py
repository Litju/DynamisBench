"""Reading version-controlled source authority: the category/kind contract, a strict
JSON/YAML loader, and the semantic identity of what was read.

A workspace knows *where* authority lives. This module is the part that knows *what*
a file found there is, and it is deliberately the only door between the two. The chain
is fixed and every link is load-bearing:

    explicit roots -> Workspace -> declared category -> declared kind directory
    -> root-scoped logical reference -> strict JSON/YAML parse -> existing domain model
    -> semantic_sha256(validated model)

Nothing short-circuits it. Model type comes from the declared directory segment, never
from the keys a document happens to contain and never from its file name, so a file
called ``metric.yaml`` under ``benchmarks/scenario/`` is a scenario that fails to
validate rather than a metric that happens to work. The semantic digest is taken over
the validated model, so it is a function of meaning alone: authoring whitespace,
comments, key order, and the absolute path of the file are all absent from it by
construction, which is what makes a relocated workspace produce identical digests.

**Authoring syntax is not meaning, so the loader fails closed on ambiguity.** A
scientific document with two keys of the same name has two readings, and which one a
parser keeps is an accident of implementation rather than a decision anybody made. So
duplicate keys are refused in JSON and in YAML alike, multi-document YAML is refused,
custom or unsafe tags are refused, a non-object root is refused, and nothing is
normalised to make it parse. Eight mebibytes is the ceiling on one document: large
enough for any of these definitions written by hand, small enough that a workspace
cannot make the reader allocate without bound.

**Diagnostics are a closed vocabulary.** Every refusal names one of nine codes and
carries a fixed message, a bounded field location, and — for a schema failure — the
Pydantic error category. No rejected value, no absolute path, and no exception text
ever reaches a diagnostic, because the process that produces them holds a local
repository and a reader that could print what it rejected could print a secret.

This module reaches the domain and the identity pipeline, and that is a deliberate
exception to the workspace package's other rule. The other modules resolve locations
and must never reach a hash, so that a path cannot be fed to one by an innocent
convenience method. Here the hash is taken over a validated model that was read from
a path that had already been proved inside its root; a location is never an argument
to anything in this module except :meth:`Workspace.resolve_source`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import yaml
from pydantic import ValidationError

from dynamisbench.domain.spec import AuthorityKind, authority_kind
from dynamisbench.domain.spec.base import DomainModel
from dynamisbench.identity import SemanticDigest, semantic_sha256
from dynamisbench.workspace.authority import PathScopeError, SourceCategory
from dynamisbench.workspace.workspace import Workspace, source_category_segments

__all__ = [
    "AUTHORING_SUFFIXES",
    "CATEGORY_KINDS",
    "diagnostic",
    "MAX_AUTHORING_DOCUMENT_BYTES",
    "MAX_DISCOVERY_ISSUES",
    "MAX_SCHEMA_DIAGNOSTICS",
    "AuthoringFormat",
    "DiagnosticCode",
    "SemanticIdentity",
    "SourceAuthorityError",
    "SourceDiagnostic",
    "SourceInspection",
    "SourceLocator",
    "document_identity",
    "format_of_suffix",
    "kind_for_segments",
    "validate_document",
]


MAX_AUTHORING_DOCUMENT_BYTES: Final = 8 * 1024 * 1024
"""The largest authoring document this reader will look at.

Every kind of definition in the domain is a human-authored document of a few hundred
lines at most; a study with a large factor grid is still kilobytes. Eight mebibytes is
two to three orders of magnitude above any of them and therefore costs nothing, while
it caps what a hostile or accidental file in a workspace can make a reader allocate.
The bound is checked against the bytes actually read, not against a stat, so a file
cannot grow past it between the two.
"""


class AuthoringFormat(StrEnum):
    """The serialisations an authoring document may be written in.

    Both are *authoring* surfaces. What a document means is the validated domain model
    it produces, and its identity is that model's semantic digest — which is why the
    same definition written as JSON and as YAML has one digest and not two.

    ``YAML`` covers both ``.yaml`` and ``.yml``: they are the same format, and which
    spelling a workspace author chose is not scientific meaning.
    """

    JSON = "json"
    YAML = "yaml"


AUTHORING_SUFFIXES: Final[Mapping[str, AuthoringFormat]] = MappingProxyType(
    {
        ".json": AuthoringFormat.JSON,
        ".yaml": AuthoringFormat.YAML,
        ".yml": AuthoringFormat.YAML,
    }
)
"""The only suffixes that are source-authority candidates.

An exhaustive mapping rather than a test against a tuple of names, because the same
table decides which files are read at all: a file whose suffix is not in it is not an
authoring document, so it is reported as a misplaced entry and never opened. Assets
that live beside a definition belong to a realization, which references them by
workspace-relative path and digests their bytes separately.
"""


def format_of_suffix(suffix: str) -> AuthoringFormat | None:
    """Return the authoring format a file name's suffix declares, or ``None``."""
    return AUTHORING_SUFFIXES.get(suffix.lower())


CATEGORY_KINDS: Final[Mapping[SourceCategory, tuple[str, ...]]] = MappingProxyType(
    {
        SourceCategory.BENCHMARKS: ("benchmark", "scenario"),
        SourceCategory.REALIZATIONS: ("realization", "sut", "environment"),
        SourceCategory.STUDIES: ("study", "factor"),
        SourceCategory.REFERENCES: ("reference",),
        SourceCategory.SCHEMAS: ("quantity", "metric"),
    }
)
"""The declared layout: which kinds live under which source category.

A kind is named by the first directory below its category, and this table is where
that statement lives. It is a second use of the domain's kind names, deliberately: the
domain owns *what a kind is*, and this table owns *where a kind is filed*, and a
workspace is free to change the second without redefining the first. The qualification
suite checks that the two agree — every kind appears exactly once across the five
categories, and every declared directory is a kind the domain knows.

The order within a category is the discovery order, so it is fixed here rather than
being derived from a filesystem listing, which has none.
"""


class DiagnosticCode(StrEnum):
    """The closed vocabulary of ways a source-authority read can fail.

    Closed because a client branches on these values, and the set grows only by a
    decision recorded here. Every member describes what happened to *this read*, never
    what the document contained: ``parse_error`` says the bytes were not a document,
    not which bytes they were.
    """

    UNSUPPORTED_ENTRY = "unsupported_entry"
    """A file whose suffix declares no authoring format, or sits outside a kind."""

    TOO_LARGE = "too_large"
    """The document exceeds :data:`MAX_AUTHORING_DOCUMENT_BYTES`."""

    INVALID_UTF8 = "invalid_utf8"
    """The bytes are not UTF-8, so their text is undefined."""

    PARSE_ERROR = "parse_error"
    """The bytes are not one well-formed JSON or YAML document."""

    DUPLICATE_KEY = "duplicate_key"
    """A mapping declares the same key twice, so its meaning is ambiguous."""

    EXPECTED_OBJECT = "expected_object"
    """The document root is not a mapping, so it cannot be a definition."""

    SCHEMA_VALIDATION = "schema_validation"
    """The mapping is well formed and does not satisfy the declared model."""

    PATH_SCOPE_VIOLATION = "path_scope_violation"
    """The entry resolves outside the authorised source root, so it was not read."""

    READ_ERROR = "read_error"
    """The bytes could not be obtained from an otherwise authorised location."""


_MESSAGES: Final[Mapping[DiagnosticCode, str]] = MappingProxyType(
    {
        DiagnosticCode.UNSUPPORTED_ENTRY: "This entry is not a source-authority document.",
        DiagnosticCode.TOO_LARGE: "This document is larger than an authoring document may be.",
        DiagnosticCode.INVALID_UTF8: "This document is not valid UTF-8 text.",
        DiagnosticCode.PARSE_ERROR: "This document could not be parsed as one authoring document.",
        DiagnosticCode.DUPLICATE_KEY: "This document declares the same mapping key twice.",
        DiagnosticCode.EXPECTED_OBJECT: "This document does not have an object at its root.",
        DiagnosticCode.SCHEMA_VALIDATION: "This document does not satisfy its declared definition.",
        DiagnosticCode.PATH_SCOPE_VIOLATION: "This entry is outside the authorised source root.",
        DiagnosticCode.READ_ERROR: "This entry could not be read.",
    }
)
"""One fixed message per code, so a diagnostic cannot be made to say anything new.

The message is chosen by the code and nothing else. That is what keeps rejected input,
absolute paths, and exception text out of a diagnostic by construction rather than by
review: there is no parameter through which they could be passed.
"""


MAX_SCHEMA_DIAGNOSTICS: Final = 3
"""The most schema failures one document reports.

A definition that fails three times is already told what is wrong with it, and a
document engineered to fail a thousand ways would otherwise turn one bounded answer
into an unbounded list.
"""


MAX_DISCOVERY_ISSUES: Final = 32
"""The most structural issues one discovery reports.

Discovery walks a whole workspace, so a single mistake — a category directory copied
from the wrong project — could otherwise produce one issue per file. The walk stops
collecting at this count and the summary says so, rather than truncating silently.
"""


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    """One bounded reason a document is not valid authority.

    ``location`` is a dotted path within the document (``quantities.0.dimension``) and
    ``category`` is a Pydantic error type for a schema failure. Both are structural
    names drawn from the document's own field names, which is why they are safe to
    publish and why no value is: the name of the field that was wrong is a fact about
    the *definition's shape*, and the wrong value is the author's data.
    """

    code: DiagnosticCode
    message: str
    location: str | None = None
    category: str | None = None


def diagnostic(
    code: DiagnosticCode, *, location: str | None = None, category: str | None = None
) -> SourceDiagnostic:
    """Build a diagnostic whose text is the one fixed message for its code.

    Public, because two modules refuse the same ways and both must be unable to write
    their own prose into a finding. There is no parameter for a message: a diagnostic
    says which of nine things happened, and that is all it may say.
    """
    return SourceDiagnostic(
        code=code, message=_MESSAGES[code], location=location, category=category
    )


class SourceAuthorityError(Exception):
    """One source document could not be read as valid authority.

    Carries the bounded diagnostics rather than a prose message, because the callers
    that matter — discovery, inspection, and an HTTP read model — all want to publish
    the reasons and none of them wants to parse a sentence. The diagnostics are the
    whole contract; the exception is how a failure travels.
    """

    def __init__(self, diagnostics: Sequence[SourceDiagnostic]) -> None:
        super().__init__("the source document is not valid authority")
        self.diagnostics = tuple(diagnostics)


class _DuplicateKeyError(ValueError):
    """Internal marker for a repeated mapping key, carrying nothing from the document."""


class _StrictSafeLoader(yaml.SafeLoader):
    """A safe YAML loader that refuses a repeated mapping key.

    ``SafeLoader`` already refuses arbitrary Python object construction and custom
    tags, which is what keeps authoring from being code execution. The one thing it
    does *not* do is notice a repeated key: it keeps the last one, silently. For a
    scientific document that is the worst available outcome, because the file still
    validates and the value the author wrote first has vanished.

    ``construct_mapping`` is the single point every mapping passes through, including
    those nested inside sequences, so overriding it here covers the whole document
    rather than only its root.
    """

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise _DuplicateKeyError
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _scan_yaml_events(text: str) -> tuple[int, bool]:
    """Count YAML documents in ``text`` and report whether it uses an anchor alias.

    One scan, two questions, and neither answer needs the document to be
    *constructed* — which is the point. A count greater than one means the file
    describes several documents and a loader that silently kept the first would be
    reading a file the author did not write. An alias means the text contains an
    anchor whose expansion can be exponential in the size of the file, so an eight
    mebibyte document could still ask for an unbounded amount of memory; refusing the
    alias costs a YAML feature that has no meaning in a definition.
    """
    documents = 0
    aliases = False
    try:
        for event in yaml.parse(text):
            if isinstance(event, yaml.DocumentStartEvent):
                documents += 1
            elif isinstance(event, yaml.AliasEvent):
                aliases = True
    except yaml.YAMLError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.PARSE_ERROR)]) from error
    return documents, aliases


def _decode(raw: bytes) -> str:
    """Decode authoring bytes as strict UTF-8.

    Strict, so a document carrying bytes that are not text is refused rather than
    decoded with replacement characters. A ``U+FFFD`` in place of an invalid byte
    would otherwise validate as ordinary text and put a character the author never
    wrote into a semantic digest.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.INVALID_UTF8)]) from error


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that refuses a repeated key instead of keeping the last.

    This is the JSON counterpart of :class:`_StrictSafeLoader`, and the reason is the
    same. ``json`` silently resolves a duplicate by last-one-wins, so an authoring
    file could state one value and validate as another without anything reporting the
    disagreement.
    """
    mapping: dict[str, Any] = {}
    for key, value in pairs:
        if key in mapping:
            raise _DuplicateKeyError
        mapping[key] = value
    return mapping


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except _DuplicateKeyError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.DUPLICATE_KEY)]) from error
    except json.JSONDecodeError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.PARSE_ERROR)]) from error


def _parse_yaml(text: str) -> Any:
    documents, aliases = _scan_yaml_events(text)
    if aliases:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.PARSE_ERROR)])
    if documents > 1:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.PARSE_ERROR)])
    loader = _StrictSafeLoader(text)
    try:
        return loader.get_single_data()
    except _DuplicateKeyError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.DUPLICATE_KEY)]) from error
    except yaml.YAMLError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.PARSE_ERROR)]) from error
    finally:
        loader.dispose()


def parse_document(raw: bytes, authoring_format: AuthoringFormat) -> dict[str, Any]:
    """Parse authoring bytes into the mapping at the document root.

    Strict in both formats: UTF-8 only, one document, no duplicate keys, no unsafe or
    custom tags, and a mapping at the root. Everything that fails raises
    :class:`SourceAuthorityError` carrying one bounded diagnostic, so there is no path
    through this function that returns something ambiguous and no rejection that
    reports what was rejected.

    :raises SourceAuthorityError: for input that is not one unambiguous UTF-8 mapping.
    """
    if len(raw) > MAX_AUTHORING_DOCUMENT_BYTES:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.TOO_LARGE)])

    text = _decode(raw)
    if authoring_format is AuthoringFormat.JSON:
        parsed = _parse_json(text)
    else:
        parsed = _parse_yaml(text)

    if not isinstance(parsed, dict):
        raise SourceAuthorityError([diagnostic(DiagnosticCode.EXPECTED_OBJECT)])
    return parsed


def read_document_bytes(path: Path) -> bytes:
    """Read one document's bytes under a hard ceiling.

    Reads at most one byte more than the ceiling and reports the excess, rather than
    stat'ing first: the two can disagree, and a file that grew in between must still
    be refused. A refusal here is :data:`DiagnosticCode.READ_ERROR`, which is a
    statement about the filesystem and never about the document.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_AUTHORING_DOCUMENT_BYTES + 1)
    except OSError as error:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.READ_ERROR)]) from error
    if len(raw) > MAX_AUTHORING_DOCUMENT_BYTES:
        raise SourceAuthorityError([diagnostic(DiagnosticCode.TOO_LARGE)])
    return raw


def _bounded_location(error: Mapping[str, Any]) -> str | None:
    """The field path of a Pydantic error, or ``None`` for one at the root.

    Built from the error's location tuple and truncated, because an index into a
    pathological collection is the only part of it that can grow without bound.
    """
    parts = [str(part) for part in error.get("loc", ())]
    location = ".".join(parts) if parts else None
    if location is not None and len(location) > 256:
        location = location[:256]
    return location


def validate_document(kind: AuthorityKind, document: Mapping[str, Any]) -> DomainModel:
    """Validate one parsed document against the model its declared kind names.

    :raises SourceAuthorityError: with at most :data:`MAX_SCHEMA_DIAGNOSTICS` schema
        diagnostics, each carrying the field location and the Pydantic error category.
        The rejected value never appears: Pydantic's own message would quote it, and
        this boundary must not.
    """
    try:
        return kind.model.model_validate(document)
    except ValidationError as error:
        reported = [
            diagnostic(
                DiagnosticCode.SCHEMA_VALIDATION,
                location=_bounded_location(entry),
                category=str(entry.get("type", ""))[:64] or None,
            )
            for entry in error.errors()[:MAX_SCHEMA_DIAGNOSTICS]
        ]
        raise SourceAuthorityError(
            reported or [diagnostic(DiagnosticCode.SCHEMA_VALIDATION)]
        ) from error


@dataclass(frozen=True, slots=True)
class SemanticIdentity:
    """The human identity and the semantic digest of one validated definition.

    Both travel together and neither replaces the other, exactly as ADR-006 states: a
    digest supplements an identifier and is never a name. The digest is computed over
    the validated model's canonical bytes, so it is stable across relocation, authoring
    format, and formatting.
    """

    identifier: str
    version: str | None
    digest: SemanticDigest


def document_identity(kind: AuthorityKind, model: DomainModel) -> SemanticIdentity:
    """Read a validated model's declared identity and hash its meaning.

    The one place in the workspace package where a hash is taken, and it is taken over
    an object that validation has already produced. No path, file name, category, or
    reference is an argument here, so none of them can reach the digest.
    """
    return SemanticIdentity(
        identifier=str(getattr(model, kind.identifier_field)),
        version=None if kind.version_field is None else str(getattr(model, kind.version_field)),
        digest=semantic_sha256(model),
    )


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """Where one authority document is filed, in portable terms only.

    ``segments`` is the reference relative to the category, and ``logical_reference``
    is the same reference prefixed with the category's own directory name — which is
    what a client is shown, and what is identical in two workspaces at different
    absolute roots. Neither form carries a machine-specific character: no drive, no
    leading separator, no root directory name.
    """

    category: SourceCategory
    kind: str
    segments: tuple[str, ...]

    @property
    def logical_reference(self) -> str:
        """The portable name of this document within the source root."""
        return "/".join((*source_category_segments(self.category), *self.segments))

    @property
    def category_reference(self) -> str:
        """The reference :meth:`Workspace.resolve_source` is given."""
        return "/".join(self.segments)

    @property
    def suffix(self) -> str:
        """The file name suffix this document was found under."""
        return f".{self.segments[-1].rsplit('.', 1)[-1]}" if "." in self.segments[-1] else ""

    @property
    def authoring_format(self) -> AuthoringFormat | None:
        """The authoring format this document's suffix declares."""
        return format_of_suffix(self.suffix)


@dataclass(frozen=True, slots=True)
class SourceInspection:
    """What one authority document is, as read just now.

    ``valid`` is the whole statement: when it is true the identity and digest describe
    validated meaning; when it is false all three are ``None`` and the diagnostics say
    why. There is deliberately no state in which an invalid document has a digest —
    a hash of content that did not validate is an identity for something that is not
    authority.

    ``content`` is the validated model's JSON-mode read model and exists only for a
    valid document. It is produced per inspection and is never retained by a caller:
    the API re-reads on every request precisely so that memory cannot stand in for
    the file.
    """

    locator: SourceLocator
    authoring_format: AuthoringFormat
    valid: bool
    identity: SemanticIdentity | None = None
    content: dict[str, Any] | None = None
    diagnostics: tuple[SourceDiagnostic, ...] = ()

    @property
    def kind(self) -> str:
        """The declared kind of this document."""
        return self.locator.kind


def kind_for_segments(category: SourceCategory, segments: Sequence[str]) -> str | None:
    """Return the kind the first directory below ``category`` declares.

    ``None`` when there is no first directory, or when it is not one this category
    declares. The two cases are the same to a caller: there is no kind here, so there
    is no model to validate against and the entry must be reported rather than guessed.
    """
    if not segments:
        return None
    first = segments[0]
    return first if first in CATEGORY_KINDS[category] else None


def resolve_locator(workspace: Workspace, locator: SourceLocator) -> Path:
    """Resolve a locator to a path proved inside the source root.

    Every file this module opens comes through here. A directory walk produces a path
    the filesystem vouched for; this produces a path *the workspace* vouched for, and
    a link pointing outside the root is refused rather than followed.

    :raises PathScopeError: if the locator would resolve outside the authorised root.
    """
    return workspace.resolve_source(locator.category, locator.category_reference)


def inspect_locator(workspace: Workspace, locator: SourceLocator) -> SourceInspection:
    """Read, validate, and identify one located document, now.

    Resolution, then a fresh bounded read, then a fresh parse, then validation, then
    the digest of the validated model — in that order, every time it is called. Nothing
    is memoised here or by any caller, so an edit to the file is visible to the next
    inspection and a stale answer cannot survive one.

    Resolution comes first and before the file name is even looked at, because it is
    the question that matters more: a locator naming something outside its root is a
    scope violation whatever the file is called, and answering "unsupported entry" for
    it would understate what was refused.
    """
    authoring_format = locator.authoring_format
    try:
        path = resolve_locator(workspace, locator)
    except PathScopeError:
        return SourceInspection(
            locator=locator,
            authoring_format=authoring_format or AuthoringFormat.JSON,
            valid=False,
            diagnostics=(diagnostic(DiagnosticCode.PATH_SCOPE_VIOLATION),),
        )

    if authoring_format is None:
        return SourceInspection(
            locator=locator,
            authoring_format=AuthoringFormat.JSON,
            valid=False,
            diagnostics=(diagnostic(DiagnosticCode.UNSUPPORTED_ENTRY),),
        )

    try:
        document = parse_document(read_document_bytes(path), authoring_format)
        kind = authority_kind(locator.kind)
        model = validate_document(kind, document)
    except SourceAuthorityError as error:
        return SourceInspection(
            locator=locator,
            authoring_format=authoring_format,
            valid=False,
            diagnostics=error.diagnostics,
        )

    return SourceInspection(
        locator=locator,
        authoring_format=authoring_format,
        valid=True,
        identity=document_identity(kind, model),
        content=model.model_dump(mode="json"),
    )
