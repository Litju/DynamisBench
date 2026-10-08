#!/usr/bin/env python3
"""Deterministic M1 qualification report for the scientific kernel.

This tool does not re-run the M1 test suites. It reads the already-authoritative
evidence (a full-suite JUnit report), refuses to certify a failed or malformed
evidence set, exercises the real CLI primitives against the committed M1
qualification fixtures, and emits one compact deterministic JSON report per
qualification target. The report states exactly what M1 qualifies — software and
domain infrastructure only — and what remains outside the claim ceiling.

Determinism rules: no timestamps, no network, no hidden Git lookup, no absolute
machine paths, keys sorted, ASCII-only output, LF-only canonical bytes, and the
same inputs always produce byte-identical output.

The module is deliberately a small set of pure-ish functions over explicit paths
so that ``tests/test_m1_qualification.py`` can qualify every refusal path without
re-running the pytest suite it is generating evidence for.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "m1.qualification.1"

NON_CLAIMS = [
    "human-movement model validity",
    "benchmark scientific validity",
    "MuJoCo/OpenSim validity",
    "controller validity",
    "clinical claims",
    "cross-simulator numerical equivalence",
]

CLAIM_CEILING = (
    "M1 qualifies software/domain infrastructure only. It proves the scientific "
    "kernel — schemas, canonical identity, planning determinism, workspace and "
    "evidence boundaries, CLI primitives, and simulator import isolation — is "
    "implemented and reproducible. It does not validate any human-movement model, "
    "simulator realization, controller, or benchmark science."
)

QUALIFIED_GATES: tuple[dict[str, str], ...] = (
    {
        "name": "domain-schema-corpus",
        "evidence": "python/tests/domain/test_corpus.py",
        "summary": "Valid and invalid domain fixtures validate and reject as declared.",
    },
    {
        "name": "quantity-and-identity-property-invariants",
        "evidence": (
            "python/tests/domain/test_quantities.py,"
            " python/tests/identity/test_identity_properties.py"
        ),
        "summary": "Hypothesis invariants over quantity/spec bounds and semantic identity.",
    },
    {
        "name": "canonical-hash-determinism",
        "evidence": (
            "python/tests/identity/test_golden_corpus.py,"
            " python/tests/identity/test_rfc8785_conformance.py"
        ),
        "summary": "RFC 8785 canonical bytes and golden semantic digests are stable.",
    },
    {
        "name": "workspace-path-invariants",
        "evidence": "python/tests/workspace",
        "summary": "Workspace layout and authority boundaries hold.",
    },
    {
        "name": "manifest-seal-failure-injection",
        "evidence": "python/tests/evidence",
        "summary": "Manifests and sealed evidence bundles reject tampering.",
    },
    {
        "name": "planning-determinism",
        "evidence": "python/tests/planning/test_determinism.py",
        "summary": "Equal planning arguments compile byte-identical StudyPlans.",
    },
    {
        "name": "simulator-import-boundary",
        "evidence": "python/tests/test_simulator_isolation.py",
        "summary": "The scientific core imports no MuJoCo/OpenSim or other simulator.",
    },
    {
        "name": "cli-primitives",
        "evidence": "python/tests/test_cli_primitives.py",
        "summary": "spec validate, identity inspect, and plan compile qualify fixtures.",
    },
    {
        "name": "cross-platform-parity",
        "evidence": "m1-qualification-windows-x64 / m1-qualification-linux-x64 artifacts",
        "summary": (
            "cross-platform-parity evidence input: per-platform digests, run counts, and "
            "fingerprint summaries; the pairwise comparison across both artifacts establishes "
            "parity."
        ),
    },
)


class EvidenceError(Exception):
    """Evidence is missing, malformed, or not clean enough to certify."""


def parse_junit(path: Path) -> dict[str, Any]:
    """Read one JUnit XML report and return its clean counts and skip records."""
    if not path.is_file():
        raise EvidenceError(f"JUnit report not found: {path}")
    try:
        root = ET.fromstring(path.read_bytes())
    except (ET.ParseError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"malformed JUnit XML: {exc}") from exc
    suites = root.findall("testsuite")
    if root.tag == "testsuite":
        suites = [root]
    if not suites:
        raise EvidenceError("JUnit XML contains no testsuite elements")
    total = failures = errors = skipped = 0
    skipped_tests: list[dict[str, str]] = []
    for suite in suites:
        try:
            total += int(suite.attrib["tests"])
            failures += int(suite.attrib["failures"])
            errors += int(suite.attrib["errors"])
            skipped += int(suite.attrib["skipped"])
        except (KeyError, ValueError) as exc:
            raise EvidenceError(f"JUnit suite is missing required counters: {exc}") from exc
        for case in suite.iter("testcase"):
            skip = case.find("skipped")
            if skip is not None:
                name = case.attrib.get("name", "")
                module = case.attrib.get("classname", "")
                reason = skip.attrib.get("message", "") or (skip.text or "").strip()
                skipped_tests.append({"name": name, "module": module, "reason": reason})
            for problem in list(case.iter("failure")) + list(case.iter("error")):
                if problem is not None:
                    raise EvidenceError("the pytest suite is not clean; refusing to certify M1")
        if failures or errors:
            raise EvidenceError("the pytest suite is not clean; refusing to certify M1")
    if total == 0:
        raise EvidenceError("the JUnit report records zero tests")
    skipped_tests.sort(key=lambda item: (item["module"], item["name"]))
    return {
        "total": total,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": total - failures - errors - skipped,
        "skipped_tests": skipped_tests,
    }


def run_cli(args: list[str], *, executable: str) -> str:
    """Run one ``dbench`` primitive in a fresh process and return its stdout."""
    result = subprocess.run(
        [executable, "-m", "dynamisbench", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise EvidenceError(f"CLI failed: dbench {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def cli_smoke(
    fixture_root: Path, *, executable: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Exercise the three real primitives against the committed fixtures."""
    validate_out = run_cli(
        ["spec", "validate", "--kind", "benchmark", str(fixture_root / "benchmark.json")],
        executable=executable,
    )
    validate = json.loads(validate_out)
    if validate.get("valid") is not True or validate.get("kind") != "benchmark":
        raise EvidenceError("spec validate output failed the expected shape")

    identity_out = run_cli(
        ["identity", "inspect", "--kind", "benchmark", str(fixture_root / "benchmark.json")],
        executable=executable,
    )
    identity = json.loads(identity_out)
    if identity.get("algorithm") != "sha256" or not identity.get("digest"):
        raise EvidenceError("identity inspect output failed the expected shape")

    plan_out = run_cli(
        [
            "plan",
            "compile",
            "--study",
            str(fixture_root / "study.json"),
            "--benchmark",
            str(fixture_root / "benchmark.json"),
            "--realization",
            str(fixture_root / "realization.json"),
            "--sut",
            str(fixture_root / "sut.json"),
            "--environment",
            str(fixture_root / "environment.json"),
            "--factor-case",
            str(fixture_root / "factor-case.json"),
        ],
        executable=executable,
    )
    plan = json.loads(plan_out)
    runs = plan.get("runs")
    if not isinstance(runs, list) or not runs:
        raise EvidenceError("plan compile produced no runs")
    fingerprints = {run["fingerprint"]["hex"] for run in runs}
    seeds = sorted({run["spec"]["seed"] for run in runs}) if "seed" in runs[0]["spec"] else []
    plan_summary = {
        "run_count": len(runs),
        "distinct_execution_fingerprints": len(fingerprints),
        "seeds": seeds,
    }
    return (
        {
            "ok": True,
            "kind": validate["kind"],
            "identifier": validate["identifier"],
            "version": validate.get("version"),
        },
        {"ok": True, "algorithm": "sha256", "digest": identity["digest"]},
        plan_summary,
    )


def build_report(
    *,
    target: str,
    git_sha: str,
    summary: dict[str, Any],
    validate_smoke: dict[str, Any],
    identity_smoke: dict[str, Any],
    plan_summary: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the deterministic report object from already-verified evidence."""
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M1",
        "target": target,
        "git_sha": git_sha,
        "test_summary": {
            "total": summary["total"],
            "passed": summary["passed"],
            "failures": summary["failures"],
            "errors": summary["errors"],
            "skipped": summary["skipped"],
        },
        "skipped_tests": summary["skipped_tests"],
        "qualified_gates": list(QUALIFIED_GATES),
        "cli_smoke": {
            "spec_validate": validate_smoke,
            "identity_inspect": identity_smoke,
            "plan_compile": {
                "ok": True,
                "run_count": plan_summary["run_count"],
                "distinct_execution_fingerprints": plan_summary["distinct_execution_fingerprints"],
            },
        },
        "semantic_digest": {
            "algorithm": "sha256",
            "hex": identity_smoke["digest"],
        },
        "plan_summary": plan_summary,
        "claim_ceiling": CLAIM_CEILING,
        "non_claims": NON_CLAIMS,
    }


def render_report(report: dict[str, Any]) -> str:
    """One canonical LF-only JSON rendering of the report."""
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_report(path: Path, text: str) -> None:
    """Write the report as explicit UTF-8 bytes, never through newline translation."""
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True)
    path.write_bytes(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the deterministic M1 qualification report.")
    parser.add_argument("--target", required=True, choices=["windows-x64", "linux-x64"])
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--fixture-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        summary = parse_junit(args.junit)
        validate_smoke, identity_smoke, plan_summary = cli_smoke(
            args.fixture_root, executable=sys.executable
        )
    except (EvidenceError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"m1_qualification: error: {exc}", file=sys.stderr)
        return 2

    report = build_report(
        target=args.target,
        git_sha=args.git_sha,
        summary=summary,
        validate_smoke=validate_smoke,
        identity_smoke=identity_smoke,
        plan_summary=plan_summary,
    )
    text = render_report(report)
    write_report(args.output, text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
