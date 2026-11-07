"""Check or regenerate the squat realization's pinned authority, or write a squat workspace.

    uv run python tools/mujoco_squat_authority.py --check
    uv run python tools/mujoco_squat_authority.py --write-pins
    uv run python tools/mujoco_squat_authority.py --workspace <directory>

``--check`` recomputes every semantic digest from :mod:`dynamisbench.adapters.mujoco.squat.case`
and fails (exit 1) when one differs from :mod:`.pins`. ``--write-pins`` rewrites the pinned
digests in ``pins.py`` (a reviewed change). ``--workspace`` initialises a DynamisBench
workspace (``<directory>/source`` and ``<directory>/evidence``) whose source authority holds the
squat benchmark release, realization, system under test, both platform environments, the
configuration study and the model asset — the workspace a researcher
opens in the workbench to run the squat. It writes nothing outside ``<directory>``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

from dynamisbench.adapters.mujoco.squat import case, contract, pins
from dynamisbench.workspace import SourceCategory, initialize_workspace

PINS_PATH: Final = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "dynamisbench"
    / "adapters"
    / "mujoco"
    / "squat"
    / "pins.py"
)

_PIN_NAMES: Final = {
    "benchmark": "BENCHMARK_SEMANTIC_DIGEST",
    "scenario": "SCENARIO_SEMANTIC_DIGEST",
    "realization": "REALIZATION_SEMANTIC_DIGEST",
    "system_under_test": "SUT_SEMANTIC_DIGEST",
}

PREDECLARED_CASES: Final = {
    "nominal": {},
    "half-timestep": {"f.squat.integration-timestep": 0.0005},
    "static-internal-model": {"f.squat.internal-model-gain": 0.0},
    "soft-sole-friction": {"f.squat.sole-friction-time-constant": 0.015},
    "quarter-squat-90": {"f.squat.bottom-knee-flexion": 1.5707963267948966},
    "slow-tempo": {"f.squat.descent-duration": 2.0, "f.squat.ascent-duration": 1.6},
}
"""Named configurations offered as starting points (the workbench presets); a run records the
exact factor case it executed in its evidence."""


def _pinned() -> dict[str, str]:
    return {
        "benchmark": pins.BENCHMARK_SEMANTIC_DIGEST.hex,
        "scenario": pins.SCENARIO_SEMANTIC_DIGEST.hex,
        "realization": pins.REALIZATION_SEMANTIC_DIGEST.hex,
        "system_under_test": pins.SUT_SEMANTIC_DIGEST.hex,
        **{
            f"environment_{tag.replace('-', '_')}": digest.hex
            for tag, digest in pins.ENVIRONMENT_SEMANTIC_DIGESTS.items()
        },
    }


def check() -> int:
    observed = case.authority_digests()
    pinned = _pinned()
    stale = sorted(name for name in observed if observed[name] != pinned.get(name))
    print(json.dumps({"observed": observed, "stale": stale}, indent=2, sort_keys=True))
    return 1 if stale else 0


def write_pins() -> int:
    observed = case.authority_digests()
    text = PINS_PATH.read_text(encoding="utf-8")
    for name, constant in _PIN_NAMES.items():
        text = re.sub(
            rf'({constant}: Final = SemanticDigest\(\n    hex=")[0-9a-f]{{64}}',
            rf"\g<1>{observed[name]}",
            text,
        )
    for tag in pins.ENVIRONMENT_SEMANTIC_DIGESTS:
        key = f"environment_{tag.replace('-', '_')}"
        text = re.sub(
            rf'("{tag}": SemanticDigest\(\n        hex=")[0-9a-f]{{64}}',
            rf"\g<1>{observed[key]}",
            text,
        )
    PINS_PATH.write_text(text, encoding="utf-8")
    print(json.dumps(observed, indent=2, sort_keys=True))
    return 0


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_workspace(directory: Path) -> dict[str, str]:
    """Initialise ``directory/source`` and ``directory/evidence`` with the squat authority."""
    source = directory / "source"
    evidence = directory / "evidence"
    initialize_workspace(source, evidence, sources=tuple(SourceCategory))
    documents: dict[str, Any] = {
        "benchmarks/benchmark/squat_back_squat.json": case.benchmark_release(),
        "realizations/realization/squat_mujoco.json": case.realization_definition(),
        "realizations/sut/squat_athlete_barbell.json": case.system_under_test(),
        "studies/study/squat_configuration.json": case.study_definition(),
        **{
            f"realizations/environment/squat_{tag}.json": case.environment_definition(
                platform_tag=tag
            )
            for tag in sorted(pins.ENVIRONMENT_SEMANTIC_DIGESTS)
        },
    }
    for relative, model in documents.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json(model.model_dump(mode="json")), encoding="utf-8")
    asset = source / pins.MODEL_SOURCE_PATH
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(contract.model_bytes())
    return {"source_root": str(source), "evidence_root": str(evidence)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write-pins", action="store_true")
    group.add_argument("--workspace", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.check:
        return check()
    if arguments.write_pins:
        return write_pins()
    arguments.workspace.mkdir(parents=True, exist_ok=True)
    print(json.dumps(write_workspace(arguments.workspace), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
