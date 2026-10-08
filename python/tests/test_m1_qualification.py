"""Qualification of the M1 qualification-report generator itself.

The report tool is the artifact every M1 closure claim is read from, so its own
contract is tested rather than assumed: a clean JUnit report plus a successful
CLI smoke make one deterministic LF-only byte sequence, and every failed, error,
malformed, missing, or zero-test input is refused without writing an artifact.
These tests use small synthetic JUnit documents and never re-run the pytest
suite the generator consumes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tools import m1_qualification

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "m1_qualification"

CLEAN_JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="3" failures="0" errors="0" skipped="1">
  <testcase classname="tests.test_example" name="test_first"/>
  <testcase classname="tests.test_example" name="test_second"/>
  <testcase classname="tests.test_example" name="test_os_specific">
    <skipped message="requires linux port reservation"/>
  </testcase>
</testsuite>
"""

FAILED_JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0">
  <testcase classname="tests.test_example" name="test_broken">
    <failure message="assert False">assert False</failure>
  </testcase>
</testsuite>
"""

ERRORED_JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" failures="0" errors="1" skipped="0">
  <testcase classname="tests.test_example" name="test_broken">
    <error message="boom">RuntimeError: boom</error>
  </testcase>
</testsuite>
"""

ZERO_TEST_JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="0" failures="0" errors="0" skipped="0"/>
"""


def _report_args(
    tmp_path: Path,
    junit_text: str | None,
    output: Path,
    *,
    tested_sha: str = "a" * 40,
    source_sha: str = "b" * 40,
) -> list[str]:
    junit = tmp_path / "pytest.xml"
    if junit_text is not None:
        junit.write_text(junit_text, encoding="utf-8")
    return [
        "--target",
        "windows-x64",
        "--tested-sha",
        tested_sha,
        "--source-sha",
        source_sha,
        "--junit",
        str(junit),
        "--fixture-root",
        str(FIXTURE_ROOT),
        "--output",
        str(output),
    ]


def test_a_clean_junit_and_cli_smoke_make_a_deterministic_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Success: byte-identical output twice, and the real fixture expectations."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert m1_qualification.main(_report_args(tmp_path, CLEAN_JUNIT, first)) == 0
    assert m1_qualification.main(_report_args(tmp_path, CLEAN_JUNIT, second)) == 0
    assert first.read_bytes() == second.read_bytes()

    report = json.loads(first.read_text(encoding="utf-8"))
    assert report["schema_version"] == m1_qualification.SCHEMA_VERSION
    assert report["target"] == "windows-x64"
    assert report["tested_sha"] == "a" * 40
    assert report["source_sha"] == "b" * 40
    assert report["test_summary"] == {
        "total": 3,
        "passed": 2,
        "failures": 0,
        "errors": 0,
        "skipped": 1,
    }
    assert report["skipped_tests"] == [
        {
            "name": "test_os_specific",
            "module": "tests.test_example",
            "reason": "requires linux port reservation",
        }
    ]
    assert report["cli_smoke"]["spec_validate"]["ok"] is True
    assert report["cli_smoke"]["identity_inspect"]["algorithm"] == "sha256"
    assert report["semantic_digest"]["algorithm"] == "sha256"
    assert re.fullmatch(r"[0-9a-f]{64}", report["semantic_digest"]["hex"])
    assert report["plan_summary"] == {
        "run_count": 2,
        "distinct_execution_fingerprints": 1,
        "seeds": [11],
    }


def test_a_push_provenance_records_the_same_commit_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a push the tested commit is the source commit; both fields still exist."""
    output = tmp_path / "report.json"
    commit = "c" * 40
    args = _report_args(tmp_path, CLEAN_JUNIT, output, tested_sha=commit, source_sha=commit)
    assert m1_qualification.main(args) == 0, capsys.readouterr().err
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["tested_sha"] == report["source_sha"] == commit


@pytest.mark.parametrize(
    ("tested_sha", "source_sha"),
    [
        ("A" * 40, "b" * 40),
        ("a" * 39, "b" * 40),
        ("a" * 41, "b" * 40),
        ("z" * 40, "b" * 40),
    ],
)
def test_malformed_provenance_shas_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tested_sha: str, source_sha: str
) -> None:
    args = _report_args(
        tmp_path,
        CLEAN_JUNIT,
        tmp_path / "report.json",
        tested_sha=tested_sha,
        source_sha=source_sha,
    )
    assert m1_qualification.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SHA-1" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report.json").exists()


def test_the_report_uses_canonical_lf_bytes(tmp_path: Path) -> None:
    """No CRLF may reach the artifact on any host newline policy."""
    output = tmp_path / "report.json"
    assert m1_qualification.main(_report_args(tmp_path, CLEAN_JUNIT, output)) == 0
    data = output.read_bytes()
    assert b"\r\n" not in data
    assert b"\r" not in data
    assert data.endswith(b"\n")


def test_the_per_platform_report_does_not_self_certify_parity() -> None:
    """One platform's artifact is parity evidence input, not a parity verdict."""
    parity = next(
        gate for gate in m1_qualification.QUALIFIED_GATES if gate["name"] == "cross-platform-parity"
    )
    assert "evidence input" in parity["summary"]
    assert "qualified" not in parity["summary"]


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for entry in value for item in _string_values(entry)]
    if isinstance(value, dict):
        return [item for entry in value.values() for item in _string_values(entry)]
    return []


def test_the_report_carries_no_timestamp_and_no_machine_path(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    assert m1_qualification.main(_report_args(tmp_path, CLEAN_JUNIT, output)) == 0
    text = output.read_text(encoding="utf-8")

    lowered = text.lower()
    assert "timestamp" not in lowered
    assert "generated_at" not in lowered
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)

    values = _string_values(json.loads(text))
    assert not any(v.startswith("/") for v in values)
    assert not any(re.search(r"[A-Za-z]:[\\/]", v) for v in values)
    assert str(tmp_path) not in text
    assert str(FIXTURE_ROOT) not in text


@pytest.mark.parametrize(
    ("junit_text", "diagnosis"),
    [
        (FAILED_JUNIT, "not clean"),
        (ERRORED_JUNIT, "not clean"),
        ("<not xml", "malformed JUnit"),
        (ZERO_TEST_JUNIT, "zero tests"),
    ],
)
def test_unclean_or_malformed_junit_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], junit_text: str, diagnosis: str
) -> None:
    args = _report_args(tmp_path, junit_text, tmp_path / "report.json")
    assert m1_qualification.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert diagnosis in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report.json").exists()


def test_missing_junit_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _report_args(tmp_path, None, tmp_path / "report.json")
    assert m1_qualification.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not found" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report.json").exists()


def test_a_failed_cli_smoke_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing fixture makes the real CLI fail; the report must not be written."""
    args = _report_args(tmp_path, CLEAN_JUNIT, tmp_path / "report.json")
    args[args.index("--fixture-root") + 1] = str(tmp_path / "no-fixtures")
    assert m1_qualification.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "CLI failed" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report.json").exists()


def test_malformed_cli_json_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(m1_qualification, "run_cli", lambda *a, **k: "{ not json")
    args = _report_args(tmp_path, CLEAN_JUNIT, tmp_path / "report.json")
    assert m1_qualification.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert not (tmp_path / "report.json").exists()
