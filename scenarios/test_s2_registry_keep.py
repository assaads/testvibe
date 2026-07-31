"""S2 self-dogfood scenario: @scenario registry + scaffold upgrade keep-survival.

Two user-facing behaviors of the scenario API in one drive:

1. ``@scenario`` registers the function into ``testvibe.scenario.SCENARIOS``
   with the exact ``kind``/``surfaces`` the user declared.
2. ``scaffold.upgrade`` regenerates surfaces while preserving every
   ``# testvibe:keep <label>`` block (user code survives an upgrade).
"""

from __future__ import annotations

from pathlib import Path

from testvibe import scaffold, scenario
from testvibe.scenario import SCENARIOS


@scenario(
    "s2_registry_and_keep",
    kind="hermetic",
    surfaces=("invariant", "perf"),
)
def test_s2_registry_and_keep(tmp_path: Path) -> None:
    # --- registry: the decorator records kind/surfaces exactly as declared ---
    entry = SCENARIOS["s2_registry_and_keep"]
    assert entry["kind"] == "hermetic"
    assert entry["surfaces"] == ("invariant", "perf")
    fn = entry["fn"]
    assert callable(fn)
    # The decorated function carries the testvibe marker + dynamic attr.
    assert hasattr(fn, "__testvibe__")
    assert fn.__testvibe__["name"] == "s2_registry_and_keep"

    # --- upgrade: a # testvibe:keep block survives regeneration ---
    dest = tmp_path / "proj"
    scaffold.generate("my-tool", dest)
    boundary = dest / "test_s1_boundary.py"
    rendered = boundary.read_text(encoding="utf-8")

    # Replace the boundary TODO body with a user keep block.
    user_block = (
        "# testvibe:keep scenarios\n"
        "MAGIC_KEPT_LINE_42 = 1\n"
        "# end testvibe:keep"
    )
    original_keep = (
        "# testvibe:keep scenarios\n"
        "# TODO: replace with your @scenario(...) boundary cases.\n"
        "# end testvibe:keep"
    )
    assert original_keep in rendered, "template no longer ships the expected empty keep block"
    boundary.write_text(rendered.replace(original_keep, user_block), encoding="utf-8")

    # Make conftest.py's GENERATED body stale (but keep its contract marker) so
    # we can prove upgrade actually regenerates non-keep content. A no-op
    # upgrade would leave this stale body untouched.
    conftest = dest / "conftest.py"
    stale_body = conftest.read_text(encoding="utf-8").replace(
        "Guidance: shared pytest hooks",
        "STALE-BODY-MARKER-FROM-AN-OLD-TEMPLATE-VERSION",
    )
    assert "STALE-BODY-MARKER-FROM-AN-OLD-TEMPLATE-VERSION" in stale_body, (
        "fixture setup: stale marker must be present before upgrade"
    )
    conftest.write_text(stale_body, encoding="utf-8")

    scaffold.upgrade(dest)
    after = boundary.read_text(encoding="utf-8")
    # The user line survived the upgrade (kept block re-spliced into its slot).
    assert "MAGIC_KEPT_LINE_42 = 1" in after, (
        "upgrade dropped a user # testvibe:keep block"
    )
    # And the regenerated template content (the slot marker) is still present.
    assert "# testvibe:slot:scenarios" in after

    # --- upgrade refreshes GENERATED (non-keep) content, not just keeps ---
    # This distinguishes a working upgrade from a no-op: the stale body must be
    # gone and the regenerated conftest must match what generate() would now
    # produce. A no-op upgrade would leave the stale marker in place.
    after_conftest = conftest.read_text(encoding="utf-8")
    assert "STALE-BODY-MARKER-FROM-AN-OLD-TEMPLATE-VERSION" not in after_conftest, (
        "upgrade did not refresh generated content (stale marker survived) — looks like a no-op"
    )
    assert "Guidance: shared pytest hooks" in after_conftest, (
        "upgrade did not restore the current template's generated body"
    )
