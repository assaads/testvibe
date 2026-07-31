"""Task C2 — `testvibe upgrade` refreshes scaffolding, preserves keep blocks.

A hand-edited ``# testvibe:keep <label>`` block must survive ``upgrade``; the
surrounding scaffolding is refreshed from the current templates. This is what
makes the generator safely re-runnable.
"""

import pathlib
import textwrap

from testvibe import scaffold


def test_upgrade_preserves_keep_block(tmp_path: pathlib.Path):
    """The plan's acceptance snippet (verbatim intent)."""
    f = tmp_path / "test_s1_boundary.py"
    f.write_text(
        textwrap.dedent(
            """
            # generated header (old version)
            # testvibe:keep scenarios
            MY_HARD_WON_SCENARIO = "tokiwoki-mcp-cluster"
            # end testvibe:keep
            # generated footer (old)
            """
        )
    )

    scaffold.upgrade(tmp_path)  # refresh from current templates

    content = f.read_text()
    assert "MY_HARD_WON_SCENARIO" in content  # kept
    assert "old version" not in content  # scaffolding refreshed


def test_upgrade_refreshes_scaffolding_around_keep(tmp_path: pathlib.Path):
    """Old scaffolding is replaced by the current generated header / guidance."""
    f = tmp_path / "test_s1_boundary.py"
    f.write_text(
        textwrap.dedent(
            """
            # STALE_HEADER_FROM_LONG_AGO
            # testvibe:slot:scenarios
            # testvibe:keep scenarios
            keepme = True
            # end testvibe:keep
            # STALE_FOOTER
            """
        )
    )

    scaffold.upgrade(tmp_path)

    content = f.read_text()
    assert "STALE_HEADER_FROM_LONG_AGO" not in content
    assert "STALE_FOOTER" not in content
    # refreshed scaffolding present
    assert "# testvibe:generated" in content
    # kept content survives
    assert "keepme = True" in content


def test_upgrade_preserves_multiple_labels(tmp_path: pathlib.Path):
    """Every labeled keep block in a file is preserved independently."""
    f = tmp_path / "test_s1_boundary.py"
    f.write_text(
        textwrap.dedent(
            """
            # generated header (old version)
            # testvibe:keep scenarios
            A = 1
            # end testvibe:keep
            # some middle scaffolding (old)
            # testvibe:keep extras
            B = 2
            # end testvibe:keep
            """
        )
    )

    scaffold.upgrade(tmp_path)

    content = f.read_text()
    assert "A = 1" in content
    # 'extras' has no matching slot in the new template -> appended (not dropped)
    assert "B = 2" in content
    assert "old version" not in content


def test_upgrade_processes_all_surfaces(tmp_path: pathlib.Path):
    """Upgrade refreshes every generated surface present in dest, not just S1."""
    contract = tmp_path / "c.yaml"
    contract.write_text("tool: demo\n")
    dest = tmp_path
    scaffold.generate(contract, dest)
    # Now hand-edit each surface's keep block.
    for name in ("test_s1_boundary.py", "test_s2_property.py", "known-failures.yaml"):
        p = dest / name
        text = p.read_text()
        # inject a marker line into the default keep block
        text = text.replace(
            "# TODO:", "HAND_EDITED_FOR_" + name + "\n        # TODO:"
        )
        p.write_text(text)

    scaffold.upgrade(dest)

    for name in ("test_s1_boundary.py", "test_s2_property.py", "known-failures.yaml"):
        content = (dest / name).read_text()
        assert "HAND_EDITED_FOR_" + name in content, f"keep block dropped in {name}"
        assert "# testvibe:generated" in content  # scaffolding refreshed


def test_upgrade_skips_missing_surfaces(tmp_path: pathlib.Path):
    """A dest with only some surfaces upgrades those and ignores the rest."""
    f = tmp_path / "conftest.py"
    f.write_text(
        textwrap.dedent(
            """
            # old conftest (ancient)
            # testvibe:keep fixtures
            my_fixture = lambda: None
            # end testvibe:keep
            """
        )
    )
    # other surfaces absent
    scaffold.upgrade(tmp_path)
    content = f.read_text()
    assert "my_fixture" in content
    assert "old conftest (ancient)" not in content
    # missing surfaces were NOT created (upgrade refreshes; it does not seed)
    assert not (tmp_path / "test_s1_boundary.py").exists()


def test_cli_upgrade_dispatches_to_upgrade(tmp_path: pathlib.Path):
    from testvibe import cli

    f = tmp_path / "test_s1_boundary.py"
    f.write_text(
        textwrap.dedent(
            """
            # generated header (old version)
            # testvibe:keep scenarios
            Z = "kept-via-cli"
            # end testvibe:keep
            """
        )
    )

    rc = cli.main(["upgrade", str(tmp_path)])

    assert rc == 0
    assert "Z = \"kept-via-cli\"" in f.read_text()
    assert "old version" not in f.read_text()
