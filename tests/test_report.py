"""Tests for testvibe.report — RunReport, Failure, detect-secrets redaction."""
from testvibe.report import Failure, RunReport


def test_report_redacts_and_tags():
    r = RunReport(tool="x", run="gate", passed=False)
    r.add_failure(
        Failure(
            kind="product",
            message="push failed",
            detail="token=ghp_abcDEF1234567890",
        )
    )
    js = r.to_json()
    assert "ghp_abcDEF1234567890" not in js
    assert "## Advisory" in r.to_markdown()


def test_report_always_has_advisory_section():
    # to_markdown() must include a `## Advisory` section even with no advisories added.
    r = RunReport(tool="x", run="gate", passed=True)
    assert "## Advisory" in r.to_markdown()


def test_report_advisory_content_rendered():
    r = RunReport(tool="x", run="gate", passed=True)
    r.add_advisory("slow-but-passing: push p90 over baseline")
    md = r.to_markdown()
    assert "## Advisory" in md
    assert "slow-but-passing" in md


def test_report_infra_failure_tagged():
    r = RunReport(tool="x", run="gate", passed=False)
    r.add_failure(
        Failure(
            kind="infra",
            message="env scrubbed",
            detail="xoxb-1234567890abcdef secret leaked",
        )
    )
    js = r.to_json()
    # slack-token prefix must be redacted, and the infra kind must be tagged.
    assert "xoxb-1234567890abcdef" not in js
    assert '"kind": "infra"' in js


def test_report_rejects_unknown_failure_kind():
    import pytest

    with pytest.raises(ValueError):
        Failure(kind="bogus", message="nope", detail="x")
