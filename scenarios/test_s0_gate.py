"""S0 self-dogfood scenario: gate env-scrub + secret redaction.

Drives testvibe the way a user drives it on the pre-merge gate: scrub tool-specific
env vars so the gate matches CI, and prove a planted token never reaches a report.
"""

from __future__ import annotations

from testvibe import scenario
from testvibe.gate import scrub_env
from testvibe.report import Failure, RunReport

# Well-known fake tokens (inlined here to avoid a cross-file `from _helpers
# import` that relies on pytest prepend-mode inserting scenarios/ on
# sys.path). Each carries >= 6 trailing alphanumerics so the
# ``testvibe.report.redact`` regex ``(ghp_|ghs_|AKIA|xox[baprs]-)[A-Za-z0-9]{6,}``
# is guaranteed to match and mask them.
FAKE_GHP_TOKEN = "ghp_aBcDeFgHiJkLmNoPqRsTuVwxYz0123456789"
FAKE_AKIA_TOKEN = "AKIAIOSFODNN7EXAMPLE1234567890"


@scenario("s0_gate_scrub_and_redact", kind="hermetic")
def test_s0_gate_scrub_and_redact() -> None:
    # --- scrub_env: drops prefixed keys, keeps everything else, input intact ---
    src = {"LEAK_SECRET": "s3cr3t", "LEAK_TOKEN": "xyz", "KEEP_ME": "y", "OTHER": "z"}
    out = scrub_env("LEAK_", src)
    assert "LEAK_SECRET" not in out, f"prefixed key leaked through scrub: {out}"
    assert "LEAK_TOKEN" not in out
    # Non-prefixed keys are preserved exactly.
    assert out == {"KEEP_ME": "y", "OTHER": "z"}
    # scrub_env returns a NEW dict; the input mapping is never mutated.
    assert src == {"LEAK_SECRET": "s3cr3t", "LEAK_TOKEN": "xyz", "KEEP_ME": "y", "OTHER": "z"}

    # --- RunReport.to_json redacts planted ghp_/AKIA tokens ---
    report = RunReport(tool="self-dogfood", run="s0", passed=False)
    report.add_failure(
        Failure(
            kind="product",
            message=f"stderr leaked tokens: {FAKE_GHP_TOKEN} {FAKE_AKIA_TOKEN}",
            detail=f"env had {FAKE_GHP_TOKEN}",
        )
    )
    rendered = report.to_json()
    # The full token strings must NEVER appear in rendered output.
    assert FAKE_GHP_TOKEN not in rendered, "ghp_ token was not redacted"
    assert FAKE_AKIA_TOKEN not in rendered, "AKIA token was not redacted"
    # The redaction marker is present (regex backstop masks the secret value).
    assert "***REDACTED***" in rendered
