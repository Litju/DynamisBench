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
from pydantic import ValidationError as PydanticValidationError

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
        "ALLUSERSPROFILE",
        "APPDATA",
        "APPINIT_DLLS",
        "BASH_ENV",
        "BASHOPTS",
        "CDPATH",
        "CLASSPATH",
        "COMMONPROGRAMFILES",
        "COMSPEC",
        "CORECLR_ENABLE_PROFILING",
        "CORECLR_PROFILER",
        "CORECLR_PROFILER_PATH",
        "COR_ENABLE_PROFILING",
        "COR_PROFILER",
        "COR_PROFILER_PATH",
        "DOTNET_ADDITIONAL_DEPS",
        "DOTNET_ROOT",
        "DOTNET_SHARED_STORE",
        "DOTNET_STARTUP_HOOKS",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "ENV",
        "GCONV_PATH",
        "GDK_PIXBUF_MODULE_FILE",
        "GLIBC_TUNABLES",
        "GLOBIGNORE",
        "GTK_MODULES",
        "GTK_PATH",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOSTALIASES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "IFS",
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "LANG",
        "LC_ALL",
        "LD_AUDIT",
        "LD_DEBUG",
        "LD_DEBUG_OUTPUT",
        "LD_DYNAMIC_WEAK",
        "LD_LIBRARY_PATH",
        "LD_ORIGIN_PATH",
        "LD_PRELOAD",
        "LD_PROFILE",
        "LD_SHOW_AUXV",
        "LD_USE_LOAD_BIAS",
        "LD_VERBOSE",
        "LOCALAPPDATA",
        "LOCPATH",
        "MALLOC_CHECK_",
        "MALLOC_PERTURB_",
        "MALLOC_TRACE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_OPTIONS",
        "NODE_PATH",
        "NO_PROXY",
        "NLSPATH",
        "PATH",
        "PATHEXT",
        "PERL5LIB",
        "PERL5OPT",
        "PERLLIB",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROMPT_COMMAND",
        "PS4",
        "PSMODULEPATH",
        "PYTHONEXECUTABLE",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "REQUESTS_CA_BUNDLE",
        "RES_OPTIONS",
        "RUBYLIB",
        "RUBYOPT",
        "SHELL",
        "SHELLOPTS",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TERMCAP",
        "TERMINFO",
        "TERMINFO_DIRS",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "WINDIR",
        "_JAVA_OPTIONS",
    }
)
"""Variable names a worker environment may never declare.

These are not style preferences. ``PATH`` and the ``PYTHON*`` names change what code is
imported; the loader and proxy names change what native code and certificates are trusted;
the locale and time-zone names would make a worker's behaviour depend on an override; the
temporary-directory and Windows-platform names would move a worker's scratch space or its
system DLL search outside the supervised environment. A control name beginning with
``DYNAMISBENCH_`` is reserved separately.

Names are compared case-insensitively because Windows environment blocks are
case-insensitive: ``Path`` and ``PATH`` name the same slot, so an exact-case set would let
one spelling of a loader-sensitive variable through on the authoritative platform.
"""

_RESERVED_PREFIX: Final = "DYNAMISBENCH_"
_PYTHON_PREFIX: Final = "PYTHON"

_FORBIDDEN_PREFIXES: Final = (
    _RESERVED_PREFIX,
    _PYTHON_PREFIX,
    "__",
    "BASH_",
    "BASH_FUNC_",
    "COMPLUS_",
    "CORECLR_",
    "COR_",
    "DOTNET_",
    "DYLD_",
    "GCONV_",
    "GLIBC_",
    "JAVA_",
    "LD_",
    "MALLOC_",
    "NODE_",
    "PERL",
    "RUBY",
    "_JAVA_",
)
"""Name families that are never a benign per-run declaration.

Each family has at least one member that changes which shared library, interpreter hook,
profiler, certificate or script is loaded. Blocking the whole family rather than an
incomplete list is deliberate: a denylist of individual loader names is always one
release behind the loader, while these prefixes are loader-owned namespaces in practice.
"""


def _normalise_environment_name(name: str) -> str:
    """The case-insensitive key the operating system uses for a variable name.

    The worker environment is admitted for Windows, where the environment block is
    case-insensitive, and for POSIX, where it is not. One rule covers both: admission and
    collision checks use the ASCII upper-case spelling, so ``Path`` cannot alias ``PATH``
    merely because one platform would have treated it as a different name.
    """
    return name.upper()


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
        normalised = _normalise_environment_name(self.name)
        if normalised in FORBIDDEN_WORKER_ENVIRONMENT_VARIABLES:
            raise ValueError(
                f"the worker environment variable {self.name!r} is reserved by the supervisor "
                "and may not be declared by an environment"
            )
        for prefix in _FORBIDDEN_PREFIXES:
            if normalised.startswith(prefix):
                raise ValueError(
                    f"the worker environment variable {self.name!r} uses the loader-sensitive "
                    f"{prefix!r} name family and may not be declared by an environment"
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

    @model_validator(mode="after")
    def _declared_names_are_case_distinct(self) -> WorkerEnvironmentManifest:
        """Reject two declarations that one platform would treat as one variable.

        ``keyed_by`` compares exact spellings. That is sufficient on POSIX, but Windows
        environment blocks are case-insensitive, so ``FOO`` and ``foo`` would become one
        slot and which value the worker observed would depend on the process launcher.
        The manifest therefore refuses the ambiguity rather than resolving it silently.
        """
        seen: dict[str, str] = {}
        for variable in self.environment_variables:
            normalised = _normalise_environment_name(variable.name)
            previous = seen.get(normalised)
            if previous is not None:
                raise ValueError(
                    f"worker environment variables {previous!r} and {variable.name!r} differ "
                    "only by case and would alias on Windows"
                )
            seen[normalised] = variable.name
        return self


def resolved_worker_program(manifest: WorkerEnvironmentManifest) -> Path:
    """Return the declared worker program after proving it is an executable file.

    The declared path is deliberately **not** symlink-resolved. On POSIX a virtual
    environment's interpreter is a symlink to the base CPython installation, and resolving
    it would launch the base interpreter without the environment's ``pyvenv.cfg`` and
    site-packages. The symlink path is part of the selected environment, not an incidental
    alias for its target. The declared path is still checked to be an absolute, existing
    regular file, and on POSIX it must be executable; no fallback to ``PATH`` is attempted.

    :raises WorkerEnvironmentError: if the program is missing, is not a regular file, or is
        not executable on POSIX.
    """
    declared = Path(manifest.command.program)
    try:
        is_file = declared.is_file()
    except OSError as error:
        raise WorkerEnvironmentError(
            f"the selected worker program cannot be inspected: {error}"
        ) from error
    if not is_file:
        raise WorkerEnvironmentError(
            "the selected worker program is not an existing regular file; a worker is never "
            "resolved through PATH or replaced by a fallback"
        )
    if os.name != "nt" and not os.access(declared, os.X_OK):
        raise WorkerEnvironmentError("the selected worker program exists but is not executable")
    return declared


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
        system_root = _case_insensitive_platform_value(source, "SYSTEMROOT")
        windows_directory = _case_insensitive_platform_value(source, "WINDIR")
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

    reserved = {_normalise_environment_name(name) for name in values}
    declarations: list[WorkerEnvironmentVariable] = []
    declared: set[str] = set()
    for variable in manifest.environment_variables:
        try:
            # Re-run admission at the launch boundary. A caller can produce a manifest with
            # ``model_copy``/``model_construct``, which does not re-run validators; the map
            # that actually reaches the child must never contain a loader-sensitive name.
            checked = WorkerEnvironmentVariable(name=variable.name, value=variable.value)
        except PydanticValidationError as error:
            raise WorkerEnvironmentError(
                f"the declared worker environment variable {variable.name!r} is not admissible"
            ) from error
        normalised = _normalise_environment_name(checked.name)
        if normalised in reserved:
            raise WorkerEnvironmentError(
                f"the declared worker environment variable {checked.name!r} would overwrite a "
                "supervisor-owned variable"
            )
        if normalised in declared:
            raise WorkerEnvironmentError(
                f"the declared worker environment variable {checked.name!r} aliases another "
                "declaration by case"
            )
        declared.add(normalised)
        declarations.append(checked)
    values.update({variable.name: variable.value for variable in declarations})
    return values


def _case_insensitive_platform_value(source: Mapping[str, str], name: str) -> str | None:
    """Read one inherited Windows platform variable, refusing conflicting case aliases.

    ``os.environ`` already collapses case on Windows, but a caller may supply a plain
    mapping in a test or an embedding host. If two spellings of ``SYSTEMROOT`` disagree,
    choosing one would make the DLL search depend on mapping order, so the ambiguity is a
    refusal rather than a guess.
    """
    matches = {value for key, value in source.items() if key.upper() == name}
    if not matches:
        return None
    if len(matches) > 1:
        raise WorkerEnvironmentError(
            f"the inherited platform variable {name} has conflicting case aliases"
        )
    return next(iter(matches))
