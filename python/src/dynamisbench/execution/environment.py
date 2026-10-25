"""The explicitly selected, versioned worker environment and its fixed launch vector.

An execution environment is scientific evidence (ADR-009) and is separate from the
application runtime (ADR-018). The domain already identifies an
:class:`~dynamisbench.domain.spec.environment.EnvironmentDefinition`; this module is the
operational half: which adapter implementation that environment offers, what capabilities
it truly advertises, and the *fixed* program, arguments and environment variables a
supervisor will use to start it.

Three rules make that operational half safe rather than merely descriptive:

**The command is a vector, never a shell string.** ``program`` must be absolute and
``arguments`` is a tuple. There is no shell, no glob, no expansion and no string split, so
an argument containing a space, ``&``, ``;`` or a quote is one argument and cannot become
a second command. The program is resolved and checked to be a regular file before launch;
a missing or non-file program is a refusal, not a fallback to ``PATH``.

**The environment is rebuilt, not inherited.** A worker receives an explicit minimal
mapping plus the variables the selected environment declares. ``PATH``, ``PYTHONPATH``,
``LD_PRELOAD``, proxy settings and every ``DYNAMISBENCH_*`` control variable are refused
by name, so neither the desktop session nor an unrelated parent process can change what
the worker imports or which proxy it trusts. Temporary and home directories point at one
per-run scratch directory the supervisor owns.

**Time and log bounds belong to the environment, not to the request.** A ``RunSpec`` may
not ask for a longer timeout or a larger log, because those are properties of the selected
environment's qualification, not of one run's input. The supervisor re-checks both bounds
when it launches.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from dynamisbench.domain.spec.base import DomainModel, keyed_by
from dynamisbench.execution.contracts import (
    MAX_WORKER_LOG_BYTES,
    MAX_WORKER_TIMEOUT_SECONDS,
    MIN_WORKER_TIMEOUT_SECONDS,
    ExecutionError,
    WorkerAdapterIdentity,
)
from dynamisbench.planning.authority import ResolvedEnvironmentRef

__all__ = [
    "FORBIDDEN_WORKER_ENVIRONMENT_VARIABLES",
    "WorkerCommand",
    "WorkerEnvironmentError",
    "WorkerEnvironmentManifest",
    "WorkerEnvironmentVariable",
    "resolved_worker_program",
    "worker_environment",
]

_MAX_PROGRAM_LENGTH: Final = 4096
_MAX_ARGUMENT_LENGTH: Final = 4096
_MAX_ENVIRONMENT_VALUE_LENGTH: Final = 1024
_ENVIRONMENT_NAME_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

FORBIDDEN_WORKER_ENVIRONMENT_VARIABLES: Final = frozenset(
    {
        "ALL_PROXY",
        "BASH_ENV",
        "COMSPEC",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "ENV",
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "NO_PROXY",
        "PATH",
        "PROMPT_COMMAND",
        "PYTHONEXECUTABLE",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "REQUESTS_CA_BUNDLE",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "WINDIR",
    }
)
"""Variable names a worker environment may never declare.

These are not style preferences. ``PATH`` and the ``PYTHON*`` names change what code is
imported; the loader and proxy names change what native code and certificates are trusted;
the locale and time-zone names would make a worker's behaviour depend on an override; the
temporary-directory and Windows-platform names would move a worker's scratch space or its
system DLL search outside the supervised environment. A control name beginning with
``DYNAMISBENCH_`` is reserved separately.
"""

_RESERVED_PREFIX: Final = "DYNAMISBENCH_"
_PYTHON_PREFIX: Final = "PYTHON"


class WorkerEnvironmentError(ExecutionError, ValueError):
    """The selected environment cannot produce a launchable, bounded worker command."""


def _reject_control_characters(value: str, what: str) -> str:
    if any(character == "\x00" or not character.isprintable() for character in value):
        raise ValueError(f"a worker {what} must not contain NUL or control characters")
    return value


class WorkerCommand(DomainModel):
    """The fixed executable vector of one selected environment.

    This is the whole command surface. There is no command string, no shell flag, no
    working-directory field and no per-run argument injection point: a run input cannot
    choose what runs, and the supervisor cannot accidentally hand a string to a shell.
    """

    program: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PROGRAM_LENGTH)]
    arguments: tuple[Annotated[str, StringConstraints(max_length=_MAX_ARGUMENT_LENGTH)], ...] = ()

    @model_validator(mode="after")
    def _the_program_is_an_absolute_vector(self) -> WorkerCommand:
        _reject_control_characters(self.program, "program")
        if not Path(self.program).is_absolute():
            raise ValueError(
                "a worker program must be absolute; a relative program would be resolved "
                "through PATH and would not be the fixed executable the environment names"
            )
        for argument in self.arguments:
            _reject_control_characters(argument, "argument")
        return self


class WorkerEnvironmentVariable(DomainModel):
    """One explicit non-secret variable the selected environment contributes."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    value: Annotated[str, StringConstraints(max_length=_MAX_ENVIRONMENT_VALUE_LENGTH)]

    @model_validator(mode="after")
    def _the_variable_is_admissible(self) -> WorkerEnvironmentVariable:
        if _ENVIRONMENT_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("a worker environment variable name is not a portable name")
        _reject_control_characters(self.value, "environment value")
        if self.name in FORBIDDEN_WORKER_ENVIRONMENT_VARIABLES:
            raise ValueError(
                f"the worker environment variable {self.name!r} is reserved by the supervisor "
                "and may not be declared by an environment"
            )
        if self.name.upper().startswith(_RESERVED_PREFIX):
            raise ValueError(
                f"the worker environment variable {self.name!r} uses the reserved "
                f"{_RESERVED_PREFIX} prefix"
            )
        if self.name.upper().startswith(_PYTHON_PREFIX):
            raise ValueError(
                f"the worker environment variable {self.name!r} uses the reserved "
                f"{_PYTHON_PREFIX} interpreter prefix"
            )
        return self


class WorkerEnvironmentManifest(DomainModel):
    """The operational identity of one explicitly selected execution environment.

    It binds an already-resolved domain environment to exactly one adapter implementation,
    one launch vector, one timeout and one log bound. ``environment`` is a
    :class:`~dynamisbench.planning.authority.ResolvedEnvironmentRef`, so the manifest
    states the environment's version *and* its semantic digest; a manifest for a different
    environment than the RunSpec resolved is refused during preflight rather than used.
    """

    schema_version: Literal[1] = 1
    environment: ResolvedEnvironmentRef
    adapter: WorkerAdapterIdentity
    command: WorkerCommand
    timeout_seconds: Annotated[
        float, Field(ge=MIN_WORKER_TIMEOUT_SECONDS, le=MAX_WORKER_TIMEOUT_SECONDS)
    ]
    max_log_bytes: Annotated[int, Field(gt=0, le=MAX_WORKER_LOG_BYTES)] = MAX_WORKER_LOG_BYTES
    environment_variables: Annotated[tuple[WorkerEnvironmentVariable, ...], keyed_by("name")] = ()


def resolved_worker_program(manifest: WorkerEnvironmentManifest) -> Path:
    """Return the real path of the manifest's program, or refuse to launch anything.

    Resolution is the operational step that turns the declared absolute program into the
    file the operating system will execute. It is deliberately separate from model
    construction: an environment manifest is a value that can be authored and reviewed on
    a machine where the program is not installed, while a launch must prove the file is
    there now.

    :raises WorkerEnvironmentError: if the program is missing, is not a regular file, or
        cannot be resolved. No fallback to ``PATH`` is attempted.
    """
    declared = Path(manifest.command.program)
    try:
        resolved = declared.resolve()
    except (OSError, RuntimeError) as error:
        raise WorkerEnvironmentError(
            f"the selected worker program cannot be resolved: {error}"
        ) from error
    if not resolved.is_file():
        raise WorkerEnvironmentError(
            "the selected worker program is not an existing regular file; a worker is never "
            "resolved through PATH or replaced by a fallback"
        )
    if os.name != "nt" and not os.access(resolved, os.X_OK):
        raise WorkerEnvironmentError("the selected worker program exists but is not executable")
    return resolved


def worker_environment(
    manifest: WorkerEnvironmentManifest,
    *,
    temporary_directory: Path,
    inherited: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the exact environment mapping one worker process receives.

    ``inherited`` is not the process environment; it exists so a test can supply the two
    Windows variables the host requires without making the runtime depend on a global. In
    production the supervisor passes ``os.environ``, and even then only ``SYSTEMROOT`` and
    ``WINDIR`` are read from it. Everything else is either a fixed control value, a
    per-run scratch location, or a variable the selected environment explicitly declared.

    ``PATH`` is deliberately absent. The program is absolute, and a worker is not allowed
    to resolve helper executables through an inherited search path.
    """
    source = os.environ if inherited is None else inherited
    values: dict[str, str] = {
        "DYNAMISBENCH_WORKER_PROTOCOL": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "TZ": "UTC",
    }
    if os.name == "nt":
        system_root = source.get("SYSTEMROOT")
        windows_directory = source.get("WINDIR")
        if system_root:
            values["SYSTEMROOT"] = system_root
        if windows_directory:
            values["WINDIR"] = windows_directory
        values["TEMP"] = str(temporary_directory)
        values["TMP"] = str(temporary_directory)
    else:
        values["HOME"] = str(temporary_directory)
        values["LANG"] = "C.UTF-8"
        values["LC_ALL"] = "C.UTF-8"
        values["TMPDIR"] = str(temporary_directory)
    values.update({variable.name: variable.value for variable in manifest.environment_variables})
    return values
