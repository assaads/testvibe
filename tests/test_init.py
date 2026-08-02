"""Task C1 — `testvibe init` scaffolder.

`testvibe init <contract> --into <dest>` must generate the four testvibe
surfaces into the destination dir, each carrying commented guidance plus a
labeled `# testvibe:keep <label>` block (with a `# testvibe:slot:<label>`
marker) so a later `testvibe upgrade` can refresh scaffolding without
clobbering tool-specific code.
"""

import pathlib

CONTRACT_YAML = """\
# testvibe contract (minimal, for scaffolder tests)
tool: demo-tool
surfaces:
  s1_boundary: {}
  s2_property: {}
"""

SURFACES = [
    "test_s1_boundary.py",
    "test_s2_property.py",
    "known-failures.yaml",
    "conftest.py",
]


def test_generate_creates_all_surfaces(tmp_path: pathlib.Path):
    from testvibe import scaffold

    contract = tmp_path / "testvibe.yaml"
    contract.write_text(CONTRACT_YAML)
    dest = tmp_path / "tests"
    dest.mkdir()

    scaffold.generate(contract, dest)

    for name in SURFACES:
        out = dest / name
        assert out.exists(), f"{name} not generated"
        text = out.read_text()
        assert text.strip(), f"{name} is empty"


def test_generated_files_carry_keep_and_slot_markers(tmp_path: pathlib.Path):
    from testvibe import scaffold

    contract = tmp_path / "testvibe.yaml"
    contract.write_text(CONTRACT_YAML)
    dest = tmp_path / "tests"
    dest.mkdir()

    scaffold.generate(contract, dest)

    s1 = (dest / "test_s1_boundary.py").read_text()
    # labeled keep block (default tool-specific region)
    assert "# testvibe:keep" in s1
    assert "# end testvibe:keep" in s1
    # matching slot marker so upgrade can splice deterministically
    assert "# testvibe:slot:" in s1
    # generated header so upgrade can recognise / refresh scaffolding
    assert "# testvibe:generated" in s1


def test_generate_creates_dest_if_missing(tmp_path: pathlib.Path):
    from testvibe import scaffold

    contract = tmp_path / "testvibe.yaml"
    contract.write_text(CONTRACT_YAML)
    dest = tmp_path / "nested" / "tests"  # does not exist yet

    scaffold.generate(contract, dest)

    assert dest.is_dir()
    for name in SURFACES:
        assert (dest / name).exists()


def test_generate_is_idempotent(tmp_path: pathlib.Path):
    """Re-running generate over the same dest does not duplicate/corrupt."""
    from testvibe import scaffold

    contract = tmp_path / "testvibe.yaml"
    contract.write_text(CONTRACT_YAML)
    dest = tmp_path / "tests"
    dest.mkdir()

    scaffold.generate(contract, dest)
    first = {n: (dest / n).read_text() for n in SURFACES}
    scaffold.generate(contract, dest)
    second = {n: (dest / n).read_text() for n in SURFACES}
    assert first == second


def test_cli_init_dispatches_to_generate(tmp_path: pathlib.Path):
    """`testvibe init <contract> --into <dest>` routes to scaffold.generate."""
    from testvibe import cli

    contract = tmp_path / "testvibe.yaml"
    contract.write_text(CONTRACT_YAML)
    dest = tmp_path / "out"

    rc = cli.main(["init", str(contract), "--into", str(dest)])

    assert rc == 0
    for name in SURFACES:
        assert (dest / name).exists(), f"{name} missing via cli init"


def test_cli_unimplemented_subcommands_return_nonzero(capsys):
    """Honest stubs (dogfood/canary/autopilot) exit 3 (needs host/agent).

    These need external prerequisites (real host/agent) and exit 3 — NOT the old
    exit-2 'not implemented yet'. The full dispatch coverage for run/corpus
    (now real commands) lives in tests/test_cli.py. Tightened from ``rc != 0`` to
    ``rc == 3`` (the _RC_NEEDS_HOST_AGENT code) so the exact contract is verified.
    """
    from testvibe import cli

    _RC_NEEDS_HOST_AGENT = 3
    for name in ("dogfood", "canary", "autopilot"):
        rc = cli.main([name])
        assert rc == _RC_NEEDS_HOST_AGENT, (
            f"{name} must exit {_RC_NEEDS_HOST_AGENT} (needs host/agent), got {rc}"
        )
        captured = capsys.readouterr()
        combined = (captured.err + captured.out).lower()
        assert "not implemented yet" not in combined, (
            f"{name} must not say 'not implemented yet' (it is an honest exit-3 stub)"
        )
