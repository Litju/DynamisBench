"""Create a deterministic temporary DynamisBench workspace for browser-grade qualification.

DB-2.7's Playwright gate needs a workspace whose authority is real: two existing roots created
by :func:`initialize_workspace`, one valid definition, and one definition the domain model
rejects. The documents are the committed M1 fixtures rather than hand-written JSON, so the
browser is reading the same authority the Python suites read.

The tool prints one JSON object describing relative references and the expected digest of the
valid document. It prints no absolute path into the workspace beyond the two roots the caller
asked for, and it writes nothing outside ``--root``.

This is a test tool. It is not imported by the package, the API, or the desktop shell, and it
does not initialize or inspect a workspace the caller did not explicitly name.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from dynamisbench.domain.spec import authority_kind
from dynamisbench.workspace import SourceCategory, initialize_workspace
from dynamisbench.workspace.source_authority import document_identity, validate_document

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "domain"
VALID_SCENARIO = FIXTURES / "valid" / "scenario_definition.loaded_cmj.json"
INVALID_SCENARIO = FIXTURES / "invalid" / "scenario_definition.non_positive_duration.json"

VALID_REFERENCE = "benchmarks/scenario/valid_scenario.json"
INVALID_REFERENCE = "benchmarks/scenario/invalid_scenario.json"


def _semantic_digest(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    kind = authority_kind("scenario")
    model = validate_document(kind, document)
    return document_identity(kind, model).digest.hex


def create(root: Path) -> dict[str, str]:
    source = root / "authority-repository"
    evidence = root / "sealed-evidence"
    initialize_workspace(source, evidence, sources=tuple(SourceCategory))

    scenario = source / "benchmarks" / "scenario"
    scenario.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VALID_SCENARIO, scenario / "valid_scenario.json")
    shutil.copyfile(INVALID_SCENARIO, scenario / "invalid_scenario.json")

    return {
        "source_root": str(source),
        "evidence_root": str(evidence),
        "valid_reference": VALID_REFERENCE,
        "invalid_reference": INVALID_REFERENCE,
        "valid_digest": _semantic_digest(scenario / "valid_scenario.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    arguments = parser.parse_args()
    arguments.root.mkdir(parents=True, exist_ok=True)
    print(json.dumps(create(arguments.root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
