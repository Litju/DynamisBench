"""Create-if-absent content-addressed store for DB-3.3A execution inputs.

The store lives under the workspace's disposable ``CACHE`` class at ``inputs/``:

```text
<evidence>/cache/inputs/
  objects/sha256/<64 hex>       immutable object bytes
  manifests/<64 hex>.json       canonical InputManifest bytes
  quarantine/<digest>.<nonce>   preserved corrupt bytes, never authoritative
  locks/<digest>.lock           cross-process digest publication lock
  tmp/                          private temporaries, never authoritative
```

Publication is **create-if-absent**, never replace. On POSIX the final name is
created with ``os.link`` and on Windows with a non-replacing ``os.rename``. A
concurrent publisher that loses the race verifies the winner's bytes and reuses
them; an existing object with different bytes is refused and left in place. This is
the difference between a content-addressed store and a last-writer-wins directory.

Visibility, durability and recovery are separate facts:

* a reader sees either no final name or the complete published bytes;
* on POSIX the file and its parent directory are flushed; Windows file flush is
  available but directory fsync is not, so its directory-entry durability is
  explicitly weaker;
* recovery ignores temporaries and re-verifies every final object before reuse.

The store is disposable. Deleting it can never destroy sealed evidence, because
ADR-026 requires the exact inputs to be embedded in the sealed bundle at seal time.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import ValidationError

from dynamisbench.domain.spec.realizations import RealizationDefinition
from dynamisbench.identity import READ_CHUNK_BYTES
from dynamisbench.materialization.errors import (
    MaterializationError,
    MaterializationRefusalCode,
)
from dynamisbench.materialization.manifest import (
    InputManifestDigest,
    canonical_input_manifest_bytes,
    input_manifest_digest,
    parse_input_manifest,
)
from dynamisbench.materialization.schema import (
    MAX_DEFINITION_BYTES,
    MAX_MANIFEST_BYTES,
    DefinitionKind,
    InputManifest,
)
from dynamisbench.workspace import PersistenceClass, Workspace

PublicationKind = Literal["object", "manifest"]


def _is_link(path: Path) -> bool:
    """Whether a path is a symlink, junction or other reparse point."""
    if path.is_symlink():
        return True
    try:
        if path.is_junction():
            return True
    except (AttributeError, OSError):
        pass
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _require_directory(path: Path, *, label: str) -> None:
    """Require an existing real directory, never a link to one."""
    if _is_link(path):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LINK_REFUSED,
            f"the materialization store {label} is a link, not a real directory",
        )
    if not path.is_dir():
        raise MaterializationError(
            MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
            f"the materialization store {label} is not a directory",
        )


def _ensure_directory(path: Path, *, label: str) -> None:
    """Create a store directory if absent, refusing links and non-directories."""
    if path.exists() or _is_link(path):
        _require_directory(path, label=label)
        return
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
            f"the materialization store {label} could not be created",
        ) from error
    _require_directory(path, label=label)


def _hash_file(path: Path, expected_size: int) -> tuple[str, int]:
    """Return the SHA-256 and size of a regular file, refusing links."""
    if _is_link(path):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LINK_REFUSED,
            "a store object is a link, not a regular file",
        )
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_MISSING,
            "a required store object is missing",
        ) from error
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            "a store object could not be inspected",
        ) from error
    if not stat.S_ISREG(info.st_mode):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            "a store object is not a regular file",
        )
    if info.st_size != expected_size:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            "a store object has an unexpected size",
        )
    hasher = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(READ_CHUNK_BYTES):
                hasher.update(chunk)
                total += len(chunk)
                if total > expected_size:
                    raise MaterializationError(
                        MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                        "a store object grew during verification",
                    )
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            "a store object could not be read",
        ) from error
    if total != info.st_size:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            "a store object changed size while it was being verified",
        )
    return hasher.hexdigest(), total


def _read_bounded_regular_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    """Read one regular file through a bounded, no-follow handle.

    The file is inspected before open, opened with the platform's no-follow and
    non-blocking flags where available, checked again by handle, and read at most
    ``max_bytes + 1`` bytes. A FIFO, device, symlink, junction or growing file is
    therefore refused rather than followed or streamed indefinitely.
    """
    if _is_link(path):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LINK_REFUSED,
            f"{label} is a link, not a regular file",
        )
    try:
        before = path.lstat()
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_MISSING,
            f"{label} is missing",
        ) from error
    if not stat.S_ISREG(before.st_mode):
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            f"{label} is not a regular file",
        )
    if before.st_size > max_bytes:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"{label} exceeds the {max_bytes}-byte limit",
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            f"{label} could not be opened as a regular file",
        ) from error
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_size != before.st_size
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                f"{label} changed between inspection and open",
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read(max_bytes + 1)
    except OSError as error:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
            f"{label} could not be read",
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(data) > max_bytes:
        raise MaterializationError(
            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
            f"{label} exceeds the {max_bytes}-byte limit",
        )
    return data


class MaterializationStore:
    """The disposable content-addressed input store of one workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._cache = workspace.location(PersistenceClass.CACHE).path
        self._root = self._cache / "inputs"
        self._objects = self._root / "objects" / "sha256"
        self._manifests = self._root / "manifests"
        self._tmp = self._root / "tmp"
        self._quarantine = self._root / "quarantine"
        self._locks = self._root / "locks"

    @property
    def root(self) -> Path:
        """The absolute, operational store root. It never enters a manifest."""
        return self._root

    def ensure_layout(self) -> None:
        """Create the declared store layout, refusing link substitutions."""
        if self._cache.exists() or _is_link(self._cache):
            _require_directory(self._cache, label="cache location")
        else:
            try:
                self._cache.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise MaterializationError(
                    MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                    "the workspace cache location could not be created",
                ) from error
            _require_directory(self._cache, label="cache location")
        _ensure_directory(self._root, label="root")
        _ensure_directory(self._root / "objects", label="objects parent")
        _ensure_directory(self._objects, label="object directory")
        _ensure_directory(self._manifests, label="manifest directory")
        _ensure_directory(self._tmp, label="temporary directory")
        _ensure_directory(self._quarantine, label="quarantine directory")
        _ensure_directory(self._locks, label="lock directory")

    def _require_existing_layout(self) -> None:
        """Verify the read-side layout without creating or repairing anything.

        A read must not make a workspace look initialized, and a linked intermediate
        directory must not redirect an object or manifest read outside
        ``cache/inputs``. Every directory on the path is checked, not only the final
        file.
        """
        _require_directory(self._cache, label="cache location")
        _require_directory(self._root, label="root")
        _require_directory(self._root / "objects", label="objects parent")
        _require_directory(self._objects, label="object directory")
        _require_directory(self._manifests, label="manifest directory")
        _require_directory(self._tmp, label="temporary directory")

    @contextmanager
    def _digest_lock(self, digest_hex: str) -> Iterator[None]:
        """Hold an exclusive cross-process lock for one content-addressed digest.

        Publication and quarantine both mutate the canonical name. Serializing them
        per digest is what prevents a quarantiner from unlinking an object another
        publisher installed after the first quarantiner removed the old one. The lock
        is an operating-system advisory lock on a private lock file, not an in-memory
        mutex, so it coordinates separate processes using the same store.
        """
        self._require_sha256_hex(digest_hex)
        self.ensure_layout()
        path = self._locks / f"{digest_hex}.lock"
        if _is_link(path):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LINK_REFUSED,
                "a content-addressed lock file is a link",
            )
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as error:
            raise MaterializationError(
                MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                "the content-addressed publication lock could not be opened",
            ) from error
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def object_path(self, digest_hex: str) -> Path:
        """Resolve one object path inside the store.

        The digest is a lowercase SHA-256 hex string. The path is operational; it is
        never stored in a manifest, which records only ``sha256/<hex>``.
        """
        self._require_sha256_hex(digest_hex)
        return self._objects / digest_hex

    def manifest_path(self, digest_hex: str) -> Path:
        """Resolve one manifest path inside the store."""
        self._require_sha256_hex(digest_hex)
        return self._manifests / f"{digest_hex}.json"

    def manifest_locator(self, digest: InputManifestDigest) -> str:
        """The store-relative locator of a manifest, for admission and read models."""
        return f"manifests/{digest.hex}.json"

    @staticmethod
    def _require_sha256_hex(value: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("a store digest must be 64 lowercase hexadecimal characters")

    def _write_temporary(self, data: bytes) -> Path:
        self.ensure_layout()
        descriptor, name = tempfile.mkstemp(prefix=".part-", dir=self._tmp)
        path = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def _publish_temporary(
        self,
        temporary: Path,
        *,
        digest_hex: str,
        expected_size: int,
        kind: PublicationKind,
    ) -> str:
        """Publish one complete temporary with create-if-absent semantics.

        Publication and quarantine share one per-digest cross-process lock. If the
        existing canonical object is corrupt, this publisher quarantines it under the
        lock and refuses; a later publisher can install healthy bytes. A concurrent
        publisher either sees the healthy object and reuses it, or waits for the
        quarantine and publishes next; it never unlinks a newer object.
        """
        final = self.object_path(digest_hex) if kind == "object" else self.manifest_path(digest_hex)
        with self._digest_lock(digest_hex):
            try:
                if os.name == "nt":
                    # Windows rename fails rather than replacing an existing destination.
                    os.rename(temporary, final)
                else:
                    # POSIX rename would replace; link creates the final name only if absent.
                    os.link(temporary, final)
            except FileExistsError:
                try:
                    self._verify_existing(final, digest_hex=digest_hex, expected_size=expected_size)
                except MaterializationError as error:
                    if error.code is not MaterializationRefusalCode.INPUT_OBJECT_CORRUPT:
                        raise
                    self._quarantine_corrupt(final, digest_hex)
                    raise
                temporary.unlink(missing_ok=True)
                return self._publication_key(digest_hex, kind)
            except OSError as error:
                temporary.unlink(missing_ok=True)
                raise MaterializationError(
                    MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                    "the content-addressed object could not be published without replacing an "
                    "existing name",
                ) from error
            else:
                if os.name != "nt":
                    try:
                        temporary.unlink()
                    except OSError:
                        # The final name is already published and verified; a leftover
                        # private temporary is harmless.
                        pass
                self._verify_existing(final, digest_hex=digest_hex, expected_size=expected_size)
                self._fsync_parent(final)
                return self._publication_key(digest_hex, kind)

    @staticmethod
    def _publication_key(digest_hex: str, kind: PublicationKind) -> str:
        return f"sha256/{digest_hex}" if kind == "object" else f"manifests/{digest_hex}.json"

    def _verify_existing(self, path: Path, *, digest_hex: str, expected_size: int) -> None:
        """Verify an existing final name, refusing mismatch without mutating it.

        Quarantine is the caller's decision and is performed under the digest lock.
        """
        observed, size = _hash_file(path, expected_size)
        if observed != digest_hex or size != expected_size:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "an existing content-addressed object has different bytes or size",
            )

    def _quarantine_corrupt(self, path: Path, digest_hex: str) -> None:
        """Move one regular corrupt object into ``quarantine/`` without deleting bytes.

        The caller must hold the digest lock. The move preserves the corrupt bytes for
        diagnosis, removes the canonical name only when it still names the same file,
        and never overwrites an existing quarantine entry. A link, directory or
        unreadable path is left in place and refused; DB-3.3A does not delete, follow
        or silently repair it.
        """
        if _is_link(path):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LINK_REFUSED,
                "a corrupt store object is a link and cannot be quarantined",
            )
        try:
            before = path.lstat()
        except FileNotFoundError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_MISSING,
                "a corrupt store object disappeared before quarantine",
            ) from error
        except OSError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "a corrupt store object could not be inspected for quarantine",
            ) from error
        if not stat.S_ISREG(before.st_mode):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "a corrupt store object is not a regular file and cannot be quarantined",
            )
        _ensure_directory(self._quarantine, label="quarantine directory")
        for _ in range(8):
            destination = self._quarantine / f"{digest_hex}.{secrets.token_hex(8)}"
            try:
                os.link(path, destination)
            except FileExistsError:
                continue
            except OSError as error:
                raise MaterializationError(
                    MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                    "a corrupt store object could not be quarantined",
                ) from error
            try:
                after = path.lstat()
                if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                    destination.unlink(missing_ok=True)
                    raise MaterializationError(
                        MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                        "the canonical store object changed during quarantine; it was not removed",
                    )
                path.unlink()
            except MaterializationError:
                raise
            except OSError as error:
                destination.unlink(missing_ok=True)
                raise MaterializationError(
                    MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                    "a corrupt store object was copied to quarantine but its canonical name "
                    "could not be removed",
                ) from error
            return
        raise MaterializationError(
            MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
            "a corrupt store object could not be assigned a quarantine name",
        )

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        """Flush a POSIX parent directory; Windows directory fsync is unavailable."""
        if os.name == "nt":
            return
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # The object is already visible and verified. A directory flush failure is
            # a durability caveat, not permission to claim a different object identity.
            pass
        finally:
            os.close(descriptor)

    def publish_bytes(
        self,
        data: bytes,
        *,
        expected_sha256: str,
        max_bytes: int,
        kind: PublicationKind = "object",
        mismatch_code: MaterializationRefusalCode = MaterializationRefusalCode.INPUT_SOURCE_CHANGED,
    ) -> str:
        """Publish bytes whose digest is already known, refusing mismatch or oversize.

        The returned value is the store-relative key: ``sha256/<hex>`` for an object
        and ``manifests/<hex>.json`` for a manifest.
        """
        self._require_sha256_hex(expected_sha256)
        if len(data) > max_bytes:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
                f"content is larger than the {max_bytes}-byte limit",
            )
        observed = hashlib.sha256(data).hexdigest()
        if observed != expected_sha256:
            raise MaterializationError(
                mismatch_code,
                "the supplied content does not match the expected SHA-256",
            )
        temporary = self._write_temporary(data)
        try:
            return self._publish_temporary(
                temporary,
                digest_hex=expected_sha256,
                expected_size=len(data),
                kind=kind,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def publish_stream(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str,
        max_bytes: int,
        mismatch_code: MaterializationRefusalCode = MaterializationRefusalCode.INPUT_SOURCE_CHANGED,
    ) -> tuple[str, int]:
        """Copy a stream into a private temporary, hash it, then publish it.

        The source is read once and the **copy** is hashed. There is no
        hash-then-reopen-the-source step: the published bytes are the bytes that were
        hashed, so a source replacement after the read cannot change the object.

        :raises MaterializationError: for an unreadable source, an oversized stream, a
            digest mismatch, or a failed publication.
        """
        self._require_sha256_hex(expected_sha256)
        self.ensure_layout()
        descriptor, name = tempfile.mkstemp(prefix=".part-", dir=self._tmp)
        temporary = Path(name)
        hasher = hashlib.sha256()
        total = 0
        try:
            with os.fdopen(descriptor, "wb") as destination:
                while True:
                    try:
                        chunk = source.read(READ_CHUNK_BYTES)
                    except OSError as error:
                        raise MaterializationError(
                            mismatch_code,
                            "the source content could not be read",
                        ) from error
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise MaterializationError(
                            MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
                            f"content is larger than the {max_bytes}-byte limit",
                        )
                    hasher.update(chunk)
                    try:
                        destination.write(chunk)
                    except OSError as error:
                        raise MaterializationError(
                            MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                            "the copied content could not be written to the store",
                        ) from error
                try:
                    destination.flush()
                    os.fsync(destination.fileno())
                except OSError as error:
                    raise MaterializationError(
                        MaterializationRefusalCode.STORE_PUBLICATION_FAILED,
                        "the copied content could not be flushed to the store",
                    ) from error
            observed = hasher.hexdigest()
            if observed != expected_sha256:
                raise MaterializationError(
                    mismatch_code,
                    "the source content does not match the declared SHA-256",
                )
            key = self._publish_temporary(
                temporary,
                digest_hex=observed,
                expected_size=total,
                kind="object",
            )
            return key, total
        finally:
            temporary.unlink(missing_ok=True)

    def publish_manifest(self, manifest: InputManifest) -> tuple[InputManifestDigest, str]:
        """Publish a canonical manifest and return its digest and store locator."""
        digest = input_manifest_digest(manifest)
        data = canonical_input_manifest_bytes(manifest)
        key = self.publish_bytes(
            data,
            expected_sha256=digest.hex,
            max_bytes=MAX_MANIFEST_BYTES,
            kind="manifest",
            mismatch_code=MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
        )
        return digest, key

    def read_manifest(self, digest: InputManifestDigest) -> InputManifest:
        """Read, parse, canonicality-check and fully verify one stored manifest.

        A manifest is evidence input, not an arbitrary file. It is opened with the
        platform's no-follow flag where available, checked as a regular file before
        and after open, and read through a hard byte ceiling so a FIFO, device or
        growing file cannot block or exhaust the reader.
        """
        path = self.manifest_path(digest.hex)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        self._require_existing_layout()
        if _is_link(path):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LINK_REFUSED,
                "the requested input manifest is a link, not a regular file",
            )
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_MISSING,
                "the requested input manifest is missing",
            ) from error
        except OSError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "the requested input manifest could not be opened as a regular file",
            ) from error
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise MaterializationError(
                    MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                    "the requested input manifest is not a regular file",
                )
            if info.st_size > MAX_MANIFEST_BYTES:
                raise MaterializationError(
                    MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
                    "the requested input manifest exceeds the manifest-byte limit",
                )
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                data = handle.read(MAX_MANIFEST_BYTES + 1)
        except OSError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "the requested input manifest could not be read",
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(data) > MAX_MANIFEST_BYTES:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
                "the requested input manifest exceeds the manifest-byte limit",
            )
        manifest = parse_input_manifest(data)
        observed = input_manifest_digest(manifest)
        if observed != digest:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
                "the stored manifest digest is not the digest of its canonical bytes",
            )
        self.verify_manifest(manifest)
        return manifest

    def verify_manifest(self, manifest: InputManifest) -> None:
        """Re-hash every definition and asset object the manifest names.

        A valid manifest does not prove its objects are present or unchanged. This is
        the read-side counterpart of publication: every final name is re-verified
        before reuse, and a missing or corrupt object is refused.
        """
        self._require_existing_layout()
        for definition in manifest.definitions:
            self._verify_object(definition.object, definition.size_bytes)
        for asset in manifest.assets:
            self._verify_object(asset.object, asset.size_bytes)
        realization_record = next(
            item for item in manifest.definitions if item.kind is DefinitionKind.REALIZATION
        )
        data = _read_bounded_regular_file(
            self.object_path(realization_record.semantic_digest.hex),
            max_bytes=MAX_DEFINITION_BYTES,
            label="the materialized realization object",
        )
        if hashlib.sha256(data).hexdigest() != realization_record.semantic_digest.hex:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "the materialized realization object changed after verification",
            )
        try:
            realization = RealizationDefinition.model_validate_json(data)
        except ValidationError as error:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
                "the materialized realization cannot be validated",
            ) from error
        declared = {(item.asset_id, item.path, item.sha256) for item in realization.assets}
        observed = {
            (item.asset_id, item.logical_path, item.declared_sha256) for item in manifest.assets
        }
        if declared != observed:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
                "the manifest asset set differs from the materialized realization",
            )

    def _verify_object(self, object_key: str, expected_size: int) -> None:
        prefix = "sha256/"
        if not object_key.startswith(prefix):
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH,
                "a manifest names an object with a non-sha256 key",
            )
        digest_hex = object_key[len(prefix) :]
        self._require_sha256_hex(digest_hex)
        path = self.object_path(digest_hex)
        observed, size = _hash_file(path, expected_size)
        if observed != digest_hex or size != expected_size:
            raise MaterializationError(
                MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
                "a materialized object does not match its manifest digest or size",
            )


__all__ = ["MaterializationStore", "PublicationKind"]
