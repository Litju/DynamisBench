"""Smoke gates for the M1 inspection/compilation primitives.

Three JSON-only primitives qualify the M1 scientific kernel: spec validation,
semantic identity inspection, and deterministic plan compilation against the
committed M1 qualification fixtures. They are exercised through the real process
entry point (``python -m dynamisbench``), never against an in-process fake, so the
gate covers the boundary a qualification runner actually uses.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "m1_qualification"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "dynamisbench", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_spec_validate_succeeds_for_the_qualification_study() -> None:
    result = run_cli(
        "spec",
        "validate",
        "--kind",
        "study",
        str(FIXTURE_ROOT / "study.json"),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "study"
    assert payload["valid"] is True
    assert payload["identifier"] == "study.m1.qualification"
    assert payload["version"] == "1.0.0"


def test_spec_validate_refuses_an_invalid_spec() -> None:
    invalid_dir = FIXTURE_ROOT.parents[0] / "domain" / "invalid"
    invalid = invalid_dir / "benchmark_release.blank_intended_use.json"
    result = run_cli("spec", "validate", "--kind", "benchmark", str(invalid))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "error" in result.stderr
    assert "Traceback" not in result.stderr


def test_spec_validate_refuses_malformed_json(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{ not json", encoding="utf-8")
    result = run_cli("spec", "validate", "--kind", "study", str(malformed))
    assert result.returncode != 0
    assert result.stdout == ""
    assert "error" in result.stderr
    assert "Traceback" not in result.stderr


def test_spec_validate_refuses_invalid_utf8(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-utf8.json"
    invalid.write_bytes(b'{"study_id": "study.m1.qualification", "note": "\xff\xfe"}')
    result = run_cli("spec", "validate", "--kind", "study", str(invalid))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid UTF-8" in result.stderr
    assert "Traceback" not in result.stderr


def test_identity_inspect_is_stable_across_json_formatting() -> None:
    fixture = FIXTURE_ROOT / "benchmark.json"
    canonical = run_cli("identity", "inspect", "--kind", "benchmark", str(fixture))
    assert canonical.returncode == 0, canonical.stderr
    payload = json.loads(canonical.stdout)
    assert payload["algorithm"] == "sha256"
    assert payload["kind"] == "benchmark"
    assert payload["identifier"] == "db.m1-qual"

    # Re-serialize the same content with different formatting and key order.
    import json as _json

    reformatted = _json.loads(fixture.read_text(encoding="utf-8"))
    tmp = fixture.parent / ".benchmark_reformatted.tmp.json"
    try:
        tmp.write_text(_json.dumps(reformatted, indent=4, sort_keys=True), encoding="utf-8")
        alternate = run_cli("identity", "inspect", "--kind", "benchmark", str(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    assert alternate.returncode == 0, alternate.stderr
    assert json.loads(alternate.stdout)["digest"] == payload["digest"]


def test_plan_compile_emits_a_deterministic_two_replicate_plan() -> None:
    args = [
        "plan",
        "compile",
        "--study",
        str(FIXTURE_ROOT / "study.json"),
        "--benchmark",
        str(FIXTURE_ROOT / "benchmark.json"),
        "--realization",
        str(FIXTURE_ROOT / "realization.json"),
        "--sut",
        str(FIXTURE_ROOT / "sut.json"),
        "--environment",
        str(FIXTURE_ROOT / "environment.json"),
        "--factor-case",
        str(FIXTURE_ROOT / "factor-case.json"),
    ]
    first = run_cli(*args)
    assert first.returncode == 0, first.stderr
    second = run_cli(*args)
    assert first.stdout == second.stdout
    plan = json.loads(first.stdout)
    assert len(plan["runs"]) == 2
    fingerprints = {run["fingerprint"]["hex"] for run in plan["runs"]}
    assert len(fingerprints) == 1


def test_plan_compile_refuses_a_missing_varied_factor_case() -> None:
    args = [
        "plan",
        "compile",
        "--study",
        str(FIXTURE_ROOT / "study.json"),
        "--benchmark",
        str(FIXTURE_ROOT / "benchmark.json"),
        "--realization",
        str(FIXTURE_ROOT / "realization.json"),
        "--sut",
        str(FIXTURE_ROOT / "sut.json"),
        "--environment",
        str(FIXTURE_ROOT / "environment.json"),
    ]
    result = run_cli(*args)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_plan_compile_refuses_duplicate_authority(tmp_path: Path) -> None:
    """Two definitions with the same ``(identifier, version)`` are invalid user input.

    The refusal comes from the planning catalog's own validators, so it must be bounded
    like every other input failure rather than escaping as a Pydantic traceback.
    """
    duplicate = tmp_path / "duplicate-benchmark.json"
    duplicate.write_bytes((FIXTURE_ROOT / "benchmark.json").read_bytes())
    result = run_cli(
        "plan",
        "compile",
        "--study",
        str(FIXTURE_ROOT / "study.json"),
        "--benchmark",
        str(FIXTURE_ROOT / "benchmark.json"),
        "--benchmark",
        str(duplicate),
        "--realization",
        str(FIXTURE_ROOT / "realization.json"),
        "--sut",
        str(FIXTURE_ROOT / "sut.json"),
        "--environment",
        str(FIXTURE_ROOT / "environment.json"),
        "--factor-case",
        str(FIXTURE_ROOT / "factor-case.json"),
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid planning authority" in result.stderr
    assert "Traceback" not in result.stderr
