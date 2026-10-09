"""Application runtime state: one registry of open workspaces, per application.

This module is where the API remembers which workspaces it has opened and which artifacts
it has handed out, and it is deliberately *not* authority in any sense. Every entry here can
be discarded without losing anything:

* the :class:`Workspace` object is a validated pair of roots, so reopening the same two
  directories reconstructs it exactly — the same resolved paths, the same declared locations,
  the same everything;
* an artifact identifier maps to a locator, so rediscovery mints it again for a file that is
  still there. The identifier is not content; it is a handle to a re-read.

That is what makes restarting the sidecar harmless: a new process starts with an empty
registry, every identifier it once handed out stops working, and reopening the same workspace
produces the same authority with fresh identifiers and identical digests. The API is a
*description* of the workspace, not a store of it, and the two cannot be confused here
because there is nothing here a reload of the workspace could not replace.

**Identifiers carry no information.** A workspace identifier and an artifact identifier are
both opaque random tokens minted from the standard library's cryptographic source. They
contain no workspace name, no root, no drive letter, no reference and no path, and a client
cannot compute one. There is nothing to leak and nothing to guess: a token that is not in
this registry is not a workspace, whatever it resembles.

**The registry is application state, so it is thread-safe.** FastAPI runs sync handlers in a
thread pool, so two requests can read and mutate this map concurrently. Every mutation and
every lookup happens under one lock; the filesystem work a request does after taking its
locator happens outside it, so a slow disk cannot block a registration.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Final

from dynamisbench.workspace import Workspace, open_workspace
from dynamisbench.workspace.source_authority import SourceLocator

__all__ = [
    "ARTIFACT_ID_BYTES",
    "WORKSPACE_ID_BYTES",
    "RegisteredWorkspace",
    "WorkspaceNotFoundError",
    "WorkspaceRegistration",
    "WorkspaceRegistry",
]


WORKSPACE_ID_BYTES: Final = 24
"""The entropy of a workspace identifier: 24 random bytes, 32 URL-safe characters.

URL-safe because an identifier travels in a URL path, and 192 bits because it must be far past
the point where guessing one is a disk-space problem rather than a security one. Module level
and named, rather than inline, because the property a qualification gate asserts is
"identifiers are opaque and unpredictable" and that has to be a fact a gate can point at.
"""

ARTIFACT_ID_BYTES: Final = 24
"""The entropy of an artifact identifier.

The same shape and the same reasoning as a workspace identifier. An artifact identifier is
additionally scoped to one registered workspace, so a token minted for one workspace is not
merely random but is also looked up only in the workspace the request named.
"""


class WorkspaceNotFoundError(LookupError):
    """A client named a workspace or an artifact this application has not handed out.

    Raised for an identifier this registry did not mint, and never for one that is present
    but "wrong" in some other way — there is no diagnostic that distinguishes those, because
    the distinction would be what tells a caller which identifiers are real. An identifier
    from a previous application instance arrives here for the same reason: it is an unknown
    identifier now, and that is the entire restart guarantee.
    """


def _opaque_id(entropy_bytes: int) -> str:
    """One unguessable identifier, from the standard library's cryptographic source.

    ``secrets.token_urlsafe`` rather than a counter or a UUID: a counter would let a client
    enumerate the store, and a UUID's version and variant nibbles are structural bits an
    unguessable token does not have. The token carries no meaning of any kind, which is the
    whole point — it cannot be parsed, and it cannot be checked against anything but this
    registry.
    """
    return secrets.token_urlsafe(entropy_bytes)


@dataclass(frozen=True, slots=True)
class RegisteredWorkspace:
    """One open workspace, plus the artifact handles this application has handed out for it.

    ``locators`` maps an opaque artifact identifier to the place a document is filed, and
    ``references`` is the reverse mapping so that rediscovering the same document yields the
    same identifier again. Keeping locator-to-identifier stable during one application process
    is a convenience for clients, not a claim about the workspace: the mapping is memory, and
    it is rebuilt from discovery.

    Deliberately absent: any validated domain object, any digest, any content. Those are
    recomputed from the file on every inspection, which is what makes API memory disposable. A
    cache of them would answer a question about the workspace whose answer had already become
    false — and the file changing underneath is the normal case, because a repository is
    edited while the application runs.
    """

    workspace: Workspace
    lock: threading.Lock = field(default_factory=threading.Lock)
    locators: dict[str, SourceLocator] = field(default_factory=dict)
    references: dict[SourceLocator, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkspaceRegistration:
    """What a successful open hands back: the identifier to use, and the workspace.

    ``reused`` reports whether the same pair of roots was already open, rather than a second
    workspace having been created. The application does not open a workspace twice: it hands
    out the same identifier, so one workspace is one identifier for the life of the process.
    """

    identifier: str
    workspace: Workspace
    reused: bool


def _root_key(workspace: Workspace) -> tuple[str, str, str]:
    """The normalised identity of a workspace, as a key.

    Both roots came back resolved from :func:`open_workspace`, so this is the *normalised*
    pair — which is what "the same workspace" has to mean. Two different spellings of one
    directory are one workspace, because both normalised to the same resolved path before this
    key was built.
    """
    return (
        str(workspace.source_root),
        str(workspace.evidence_root),
        str(workspace.user_state_root) if workspace.user_state_root is not None else "",
    )


class WorkspaceRegistry:
    """The complete set of workspaces this application currently has open.

    One instance per application instance, created empty in :func:`create_app` and reachable
    from ``app.state``. It is never serialised, never persisted and never shared between
    processes, because it is application runtime state and nothing else.

    Three properties are load-bearing, and each is enforced rather than described:

    * **registration is explicit.** :meth:`open` calls :func:`open_workspace`, which reads
      two directories and changes nothing. It never calls ``initialize_workspace``, so
      opening a workspace that does not exist cannot be the thing that creates it.
    * **the same workspace is the same identifier.** Re-opening a pair of roots that is
      already open returns the existing identifier, because a client that opens one
      workspace twice should not end up with two identifiers describing it.
    * **lookup is total.** :meth:`registration` raises :class:`WorkspaceNotFoundError` for
      any identifier this registry did not mint, with no fallback, so a caller cannot
      manufacture a workspace by naming one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._registrations: dict[str, RegisteredWorkspace] = {}
        self._by_roots: dict[tuple[str, str, str], str] = {}

    def open(self, source_root: str, evidence_root: str) -> WorkspaceRegistration:
        """Open an existing workspace and register it, returning the identifier to use.

        :func:`open_workspace` is called before the lock is taken, so the roots are validated
        first and a refusal leaves the registry untouched — a root that cannot be opened must
        not be half-registered either.

        :raises WorkspaceRootError: if either root is missing, is not a directory, or the two
            resolve to the same directory. The route translates this into a bounded refusal
            that never echoes the rejected path.
        """
        workspace = open_workspace(source_root, evidence_root)
        key = _root_key(workspace)
        with self._lock:
            existing = self._by_roots.get(key)
            if existing is not None:
                registered = self._registrations[existing]
                return WorkspaceRegistration(
                    identifier=existing, workspace=registered.workspace, reused=True
                )
            identifier = _opaque_id(WORKSPACE_ID_BYTES)
            while identifier in self._registrations:  # pragma: no cover - 192 bits
                identifier = _opaque_id(WORKSPACE_ID_BYTES)
            self._registrations[identifier] = RegisteredWorkspace(workspace=workspace)
            self._by_roots[key] = identifier
            return WorkspaceRegistration(identifier=identifier, workspace=workspace, reused=False)

    def registration(self, identifier: str) -> RegisteredWorkspace:
        """Return the registration for ``identifier``, or refuse.

        :raises WorkspaceNotFoundError: for any identifier this registry did not mint.
        """
        with self._lock:
            registered = self._registrations.get(identifier)
        if registered is None:
            raise WorkspaceNotFoundError("no workspace is registered under that identifier")
        return registered

    def artifact(self, identifier: str, artifact_id: str) -> tuple[Workspace, SourceLocator]:
        """Return the workspace and the locator one artifact identifier names.

        The locator is the only thing the caller may open, and it is obtained through the
        workspace rather than returned here — a caller cannot ask this registry for a path, so
        there is no route by which a client-supplied string becomes one.

        :raises WorkspaceNotFoundError: for an unknown workspace identifier and, by the same
            route, for an artifact identifier this *workspace* did not mint. Both are one
            refusal with one message, so a client cannot tell whether it guessed a workspace
            identifier or borrowed an artifact identifier from another workspace.
        """
        registered = self.registration(identifier)
        locator = self.locate(registered, artifact_id)
        if locator is None:
            raise WorkspaceNotFoundError("no artifact is registered under that identifier")
        return registered.workspace, locator

    @staticmethod
    def locate(registered: RegisteredWorkspace, artifact_id: str) -> SourceLocator | None:
        """The locator a registered workspace's artifact identifier names, or ``None``.

        A static method so a caller that already holds a registration does not have to route
        back through :meth:`artifact` to find its locators. ``None`` is the answer for an
        identifier this workspace did not mint, which is how cross-workspace misuse is
        answered: the artifact is unknown *here*, and nothing is said about where it lives.
        """
        with registered.lock:
            return registered.locators.get(artifact_id)

    def record_discovery(
        self, identifier: str, locators: tuple[SourceLocator, ...]
    ) -> tuple[str, ...]:
        """Mint or reuse the artifact identifier for each located document, in order.

        Called with the result of a discovery walk. A locator already seen in this process
        keeps the identifier it had; a new one is minted. The mapping is memory only, so a
        file that has since been deleted still holds an identifier — and inspecting that
        identifier then fails as a bounded read error rather than returning stale content,
        because the locator names a workspace reference and not a cached answer.
        """
        registered = self.registration(identifier)
        with registered.lock:
            minted: list[str] = []
            for locator in locators:
                artifact_id = registered.references.get(locator)
                if artifact_id is None:
                    artifact_id = _opaque_id(ARTIFACT_ID_BYTES)
                    while artifact_id in registered.locators:  # pragma: no cover - 192 bits
                        artifact_id = _opaque_id(ARTIFACT_ID_BYTES)
                    registered.references[locator] = artifact_id
                    registered.locators[artifact_id] = locator
                minted.append(artifact_id)
            return tuple(minted)

    def forget(self, identifier: str) -> None:
        """Drop one workspace registration, or do nothing when it is not registered.

        Published because the registry is disposable and a caller should be able to say so.
        Nothing scientific is lost: the workspace still exists on disk, and a later open
        reconstructs it with a fresh identifier.
        """
        with self._lock:
            self._by_roots = {
                key: value for key, value in self._by_roots.items() if value != identifier
            }
            self._registrations.pop(identifier, None)

    def identifiers(self) -> frozenset[str]:
        """Every workspace identifier currently registered.

        Published so a qualification gate can assert the restart property against a public
        fact rather than against the registry's internals: a second application instance
        starts with an empty registry and therefore with none of these.
        """
        with self._lock:
            return frozenset(self._registrations)
