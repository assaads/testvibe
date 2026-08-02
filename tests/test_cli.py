"""Tests for testvibe.cli — dispatch for run / corpus add / corpus promote + honest stubs.

Covers the 3 now-real CLI commands (Task: CLI wiring + honest stubs):

  * ``run`` — calls ``_run.run_scenarios``, prints the report, maps the tri-state
    exit to CLI codes 0 (pass) / 1 (product) / 2 (infra).
  * ``corpus add`` — appends a row via ``corpus.add_entry``.
  * ``corpus promote`` — flips status to fixed via ``corpus.promote_entry``.

And the 3 honest exit-3 stubs:

  * ``dogfood`` / ``canary`` — need a real host + scratch resource + scoped
    credential (S3/S4 surface); exit 3, NOT "not implemented yet".
  * ``autopilot`` — is the AI autopilot skill, run via Claude Code not the CLI;
    exit 3.

Pattern mirrors ``tests/test_init.py``: ``from testvibe import cli;
rc = cli.main([...])``; assert on the return code.
"""

import json
import pathlib

import pytest

# Exit codes the CLI contract uses.
_RC_PASS = 0
_RC_PRODUCT = 1
_RC_INFRA = 2
_RC_NEEDS_HOST_AGENT = 3


# ---------------------------------------------------------------------------
# `run` — real command.
# ---------------------------------------------------------------------------
def test_cli_run_passes_exits_zero(tmp_path: pathlib.Path, capsys):
    """`testvibe run` on a passing scenario repo exits 0 and prints a report."""
    from testvibe import cli

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_demo.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        "@scenario('ok')\n"
        "def test_ok():\n"
        "    assert True\n"
    )

    rc = cli.main(["run", "--cwd", str(tmp_path)])
    assert rc == _RC_PASS
    out = capsys.readouterr().out
    # A markdown report is printed.
    assert "Testvibe Report" in out
    assert "Passed:** True" in out


def test_cli_run_product_failure_exits_one(tmp_path: pathlib.Path, capsys):
    """A scenario assertion failure (rc 1) -> CLI exits 1 (product)."""
    from testvibe import cli

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_demo.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        "@scenario('bad')\n"
        "def test_bad():\n"
        "    assert False, 'intentional product failure'\n"
    )

    rc = cli.main(["run", "--cwd", str(tmp_path)])
    assert rc == _RC_PRODUCT
    out = capsys.readouterr().out
    assert "Passed:** False" in out


def test_cli_run_infra_failure_exits_two(tmp_path: pathlib.Path, capsys):
    """A collection error (rc 2) -> CLI exits 2 (infra, not product)."""
    from testvibe import cli

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_broken.py").write_text(
        "import does_not_exist_module_xyz  # noqa: F401\n"
    )

    rc = cli.main(["run", "--cwd", str(tmp_path)])
    assert rc == _RC_INFRA


def test_cli_run_defaults_cwd_to_here(tmp_path: pathlib.Path, monkeypatch, capsys):
    """`testvibe run` without --cwd runs in the current directory."""
    from testvibe import cli

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_demo.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        "@scenario('cwd_default')\n"
        "def test_cwd_default():\n"
        "    assert True\n"
    )
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["run"])
    assert rc == _RC_PASS


# ---------------------------------------------------------------------------
# `corpus add` — real command.
# ---------------------------------------------------------------------------
def test_cli_corpus_add_appends_row(tmp_path: pathlib.Path):
    """`testvibe corpus add` appends a reloadable row to known-failures.yaml."""
    from testvibe import cli
    from testvibe.corpus import load_corpus

    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"

    rc = cli.main(
        [
            "corpus",
            "add",
            "--invariant",
            "push is idempotent",
            "--repro",
            str(repro),
            "--corpus",
            str(corpus),
            "--id",
            "bug-cli-1",
        ]
    )
    assert rc == _RC_PASS

    entries = load_corpus(corpus)
    assert len(entries) == 1
    assert entries[0].id == "bug-cli-1"
    assert entries[0].invariant == "push is idempotent"
    assert entries[0].repro == str(repro)
    assert entries[0].status == "open"


def test_cli_corpus_add_missing_repro_is_nonzero(tmp_path: pathlib.Path, capsys):
    """A missing repro file -> non-zero exit + message (no silent success)."""
    from testvibe import cli

    corpus = tmp_path / "known-failures.yaml"
    rc = cli.main(
        [
            "corpus",
            "add",
            "--invariant",
            "inv",
            "--repro",
            str(tmp_path / "no-such.py"),
            "--corpus",
            str(corpus),
            "--id",
            "x",
        ]
    )
    assert rc != _RC_PASS
    err = capsys.readouterr().err
    # Tightened from a 3-way `or` (near-vacuous — the bare word "repro" matched
    # any message) to assert the actual filename OR "not found" appears. The
    # filename is the load-bearing signal the user needs to spot a typo'd path.
    assert "no-such.py" in err or "not found" in err.lower(), (
        f"missing-repro message must name the file or say 'not found': {err!r}"
    )


def test_cli_corpus_add_auto_generates_id(tmp_path: pathlib.Path):
    """`corpus add` without --id generates a unique id (not required arg)."""
    from testvibe import cli
    from testvibe.corpus import load_corpus

    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"

    rc = cli.main(
        [
            "corpus",
            "add",
            "--invariant",
            "inv",
            "--repro",
            str(repro),
            "--corpus",
            str(corpus),
        ]
    )
    assert rc == _RC_PASS
    entries = load_corpus(corpus)
    assert len(entries) == 1
    assert entries[0].id  # non-empty auto-generated id


# ---------------------------------------------------------------------------
# `corpus promote` — real command.
# ---------------------------------------------------------------------------
def test_cli_corpus_promote_flips_to_fixed(tmp_path: pathlib.Path):
    """`testvibe corpus promote <id>` after green sets status: fixed."""
    from testvibe import cli
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="to-fix",
            invariant="inv",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="pinned",
        ),
    )

    rc = cli.main(
        ["corpus", "promote", "to-fix", "--corpus", str(corpus)]
    )
    assert rc == _RC_PASS
    # fixed drops out of the active quarantine set.
    assert load_corpus(corpus) == []


def test_cli_corpus_promote_unknown_id_is_nonzero(tmp_path: pathlib.Path, capsys):
    """`corpus promote` on a missing id -> non-zero + message."""
    from testvibe import cli
    from testvibe.corpus import CorpusEntry, add_entry

    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="real",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="pinned",
        ),
    )

    rc = cli.main(
        ["corpus", "promote", "ghost", "--corpus", str(corpus)]
    )
    # CorpusError -> CLI maps to _RC_INFRA (2), the tri-state boundary contract.
    # Tightened from `!= _RC_PASS` so the exit code is actually verified.
    assert rc == _RC_INFRA


# ---------------------------------------------------------------------------
# Honest exit-3 stubs: dogfood / canary / autopilot.
#
# These need external prerequisites (a real host, scratch resource, scoped
# credential, or the Claude Code agent itself) that the CLI cannot provide.
# They exit 3 ("needs host/agent") — NOT exit 2 ("not implemented yet") and
# NOT a fake "done". The message must name the real prerequisite.
# ---------------------------------------------------------------------------
def test_cli_dogfood_exits_three_with_prerequisite_message(capsys):
    """`testvibe dogfood` exits 3 naming the real host/resource prerequisite."""
    from testvibe import cli

    rc = cli.main(["dogfood"])
    assert rc == _RC_NEEDS_HOST_AGENT
    cap = capsys.readouterr()
    combined = (cap.err + cap.out).lower()
    # Must NOT say "not implemented yet" (the old misleading stub).
    assert "not implemented yet" not in combined


def test_cli_canary_exits_three_with_prerequisite_message(capsys):
    """`testvibe canary` exits 3 naming the real host/resource prerequisite."""
    from testvibe import cli

    rc = cli.main(["canary"])
    assert rc == _RC_NEEDS_HOST_AGENT
    cap = capsys.readouterr()
    combined = (cap.err + cap.out).lower()
    assert "not implemented yet" not in combined


def test_cli_autopilot_exits_three_with_prerequisite_message(capsys):
    """`testvibe autopilot` exits 3 naming the agent prerequisite."""
    from testvibe import cli

    rc = cli.main(["autopilot"])
    assert rc == _RC_NEEDS_HOST_AGENT
    cap = capsys.readouterr()
    combined = (cap.err + cap.out).lower()
    assert "not implemented yet" not in combined


def test_cli_honest_stubs_message_names_real_prerequisite(capsys):
    """The exit-3 message must name a real prerequisite (host/agent/credential).

    Guards against a regression to a vague "not available" — the fable anti-fraud
    rule requires the stub to honestly state WHAT external thing is needed.
    """
    from testvibe import cli

    cli.main(["dogfood"])
    # readouterr must be captured once per call; combine err+out.
    captured = capsys.readouterr()
    combined = (captured.err + captured.out).lower()
    # Must mention at least one concrete prerequisite keyword.
    assert any(
        kw in combined
        for kw in ("host", "agent", "credential", "claude code", "resource", "real")
    ), f"stub message lacks a real-prerequisite keyword: {combined!r}"


# ---------------------------------------------------------------------------
# No-arg / help behavior (regression guards).
# ---------------------------------------------------------------------------
def test_cli_no_subcommand_returns_nonzero(capsys):
    """Bare `testvibe` with no subcommand prints help + non-zero (no crash)."""
    from testvibe import cli

    rc = cli.main([])
    assert rc != _RC_PASS


def test_cli_corpus_no_subcommand_returns_nonzero(capsys):
    """Bare `testvibe corpus` prints help + non-zero."""
    from testvibe import cli

    rc = cli.main(["corpus"])
    assert rc != _RC_PASS


# ---------------------------------------------------------------------------
# Patch A — corpus promote MUST verify a green re-run (most important patch).
#
# Per the I/O matrix: "re-run not green -> non-zero" and the PLAYBOOK: promotion
# is "only after a deterministic green re-run." The CLI must NOT hardcode
# passes=True; it must execute the entry's repro and only promote if it runs
# clean. A still-failing repro -> non-zero (product failure) AND status unchanged.
# ---------------------------------------------------------------------------
def test_cli_corpus_promote_failing_repro_is_nonzero_and_unchanged(
    tmp_path: pathlib.Path, capsys
):
    """promote on an entry whose repro still raises -> rc 1 (product), status
    unchanged (still open/pinned, NOT fixed)."""
    from testvibe import cli
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    raise AssertionError('still broken')\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="still-broken",
            invariant="inv",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="pinned",
        ),
    )

    rc = cli.main(["corpus", "promote", "still-broken", "--corpus", str(corpus)])
    # Product failure (rc 1): the repro genuinely still fails -> not green.
    assert rc == _RC_PRODUCT
    err = capsys.readouterr().err
    assert "still fails" in err.lower()
    assert "not promoted" in err.lower()
    # The corpus status MUST be unchanged (still pinned, NOT fixed). load_corpus
    # returns open/pinned entries, so the entry must still be present.
    entries = load_corpus(corpus)
    assert len(entries) == 1
    assert entries[0].id == "still-broken"
    assert entries[0].status == "pinned"


def test_cli_corpus_promote_passing_repro_promotes(
    tmp_path: pathlib.Path, capsys
):
    """promote on an entry whose repro runs clean -> rc 0, status flips to fixed.

    Complement to the failing-repro test: a repro that returns without raising
    IS the green signal, so promotion proceeds (passes=True)."""
    from testvibe import cli
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "repro.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="now-fixed",
            invariant="inv",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="pinned",
        ),
    )

    rc = cli.main(["corpus", "promote", "now-fixed", "--corpus", str(corpus)])
    assert rc == _RC_PASS
    # fixed drops out of the active quarantine set.
    assert load_corpus(corpus) == []


def test_cli_corpus_promote_missing_corpus_is_infra(tmp_path: pathlib.Path, capsys):
    """promote on a corpus file that doesn't exist -> rc 2 (infra), not product."""
    from testvibe import cli

    rc = cli.main(
        ["corpus", "promote", "x", "--corpus", str(tmp_path / "no-such.yaml")]
    )
    assert rc == _RC_INFRA


# ---------------------------------------------------------------------------
# Patch M — corpus add --repro must require a FILE, not a directory.
# ---------------------------------------------------------------------------
def test_cli_corpus_add_repro_directory_is_nonzero(tmp_path: pathlib.Path, capsys):
    """--repro pointing at a directory -> non-zero + clear message.

    dir.exists() is True, so the old exists() check accepted a directory. Must
    use is_file() so a typo'd directory path is rejected at the CLI boundary.
    """
    from testvibe import cli

    a_dir = tmp_path / "a-directory"
    a_dir.mkdir()
    corpus = tmp_path / "known-failures.yaml"
    rc = cli.main(
        [
            "corpus",
            "add",
            "--invariant",
            "inv",
            "--repro",
            str(a_dir),
            "--corpus",
            str(corpus),
            "--id",
            "x",
        ]
    )
    assert rc != _RC_PASS
    err = capsys.readouterr().err
    assert "not found" in err.lower() or "a-directory" in err
    # The corpus must NOT have been written (a directory is not a valid repro).
    assert not corpus.exists()
