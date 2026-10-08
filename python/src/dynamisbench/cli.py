"""``dbench`` command line.

DB-1.1 exposes the entry point only. Product commands arrive with the issues that
own them; command behaviour must stay engine-independent (ADR-001).

One command exists, and it has no options. ``dbench api serve`` starts the session-secured
localhost sidecar (RES-375) and takes its credential and its origin list from the process
environment, so there is nothing to pass on the command line: no ``--host`` to widen the
bind, no ``--token`` to leak the credential into the process list, no ``--workers`` or
``--reload`` to turn a supervised sidecar into a fleet. Every one of those is a decision
that belongs to the desktop session, and a flag would be a way to make it in the wrong place.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dynamisbench import __version__
from dynamisbench.cli_support import (
    SPEC_KINDS,
    CliInputError,
    describe_identity,
    load_json_model,
    load_spec,
    spec_summary,
)
from dynamisbench.planning.errors import PlanningError


def _machine_json(value: Any) -> str:
    """One deterministic JSON rendering of a validated value."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """The command line, described."""
    parser = argparse.ArgumentParser(
        prog="dbench",
        description="DynamisBench — scientific workbench command line.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    commands = parser.add_subparsers(dest="command")
    api = commands.add_parser("api", help="Local application API.")
    api_commands = api.add_subparsers(dest="api_command")
    api_commands.add_parser(
        "serve",
        help="Serve the session-secured localhost API sidecar.",
        description=(
            "Serve the local API on one ephemeral 127.0.0.1 port. The session credential and "
            "the allowed origins are read from the environment; there is no command line option "
            "for either, and no option to change the bind address."
        ),
    )

    spec = commands.add_parser("spec", help="Specification validation and identity.")
    spec_commands = spec.add_subparsers(dest="spec_command")
    validate = spec_commands.add_parser(
        "validate",
        help="Validate one JSON spec against its existing Pydantic model.",
    )
    validate.add_argument("--kind", required=True, choices=sorted(SPEC_KINDS))
    validate.add_argument("file", type=Path, help="JSON file to validate.")

    identity = commands.add_parser("identity", help="Semantic identity inspection.")
    identity_commands = identity.add_subparsers(dest="identity_command")
    inspect = identity_commands.add_parser(
        "inspect",
        help="Inspect the semantic digest of one validated JSON spec.",
    )
    inspect.add_argument("--kind", required=True, choices=sorted(SPEC_KINDS))
    inspect.add_argument("file", type=Path, help="JSON file to inspect.")

    plan = commands.add_parser("plan", help="Study planning.")
    plan_commands = plan.add_subparsers(dest="plan_command")
    compile_command = plan_commands.add_parser(
        "compile",
        help="Compile a study into a deterministic StudyPlan from explicit authority files.",
    )
    compile_command.add_argument("--study", required=True, type=Path)
    compile_command.add_argument("--benchmark", action="append", default=[], type=Path)
    compile_command.add_argument("--realization", action="append", default=[], type=Path)
    compile_command.add_argument("--sut", action="append", default=[], type=Path)
    compile_command.add_argument("--environment", action="append", default=[], type=Path)
    compile_command.add_argument("--factor-case", action="append", default=[], type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the DynamisBench command line."""
    arguments = build_parser().parse_args(argv)

    if getattr(arguments, "api_command", None) == "serve":
        # Imported here so that `dbench --version` and `dbench --help` do not load the
        # application stack to answer a question about the program's own name.
        from dynamisbench.api.server import serve

        return serve()

    try:
        if getattr(arguments, "spec_command", None) == "validate":
            model = load_spec(arguments.kind, arguments.file)
            payload: dict[str, Any] = {**spec_summary(arguments.kind, model), "valid": True}
            print(_machine_json(payload))
            return 0

        if getattr(arguments, "identity_command", None) == "inspect":
            model = load_spec(arguments.kind, arguments.file)
            print(_machine_json(describe_identity(arguments.kind, model)))
            return 0

        if getattr(arguments, "plan_command", None) == "compile":
            from dynamisbench.domain.spec import (
                BenchmarkRelease,
                EnvironmentDefinition,
                RealizationDefinition,
                SUTDefinition,
                StudyDefinition,
            )
            from dynamisbench.planning import (
                FactorCase,
                PlanningContext,
                PlanningError,
                plan_study,
            )

            study = load_json_model(StudyDefinition, arguments.study)
            context = PlanningContext(
                benchmarks=tuple(
                    load_json_model(BenchmarkRelease, path) for path in arguments.benchmark
                ),
                realizations=tuple(
                    load_json_model(RealizationDefinition, path) for path in arguments.realization
                ),
                systems_under_test=tuple(
                    load_json_model(SUTDefinition, path) for path in arguments.sut
                ),
                environments=tuple(
                    load_json_model(EnvironmentDefinition, path) for path in arguments.environment
                ),
            )
            factor_cases = tuple(
                load_json_model(FactorCase, path) for path in arguments.factor_case
            )
            plan = plan_study(study, context, factor_cases=factor_cases)
            print(_machine_json(plan.model_dump(mode="json")))
            return 0
    except CliInputError as exc:
        print(f"dbench: error: {exc}", file=sys.stderr)
        return 2
    except PlanningError as exc:
        print(f"dbench: error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
