"""testvibe scaffolder — `testvibe init` (generate) and `testvibe upgrade`.

``generate(contract, dest)`` renders the four testvibe surface templates
(``test_s1_boundary.py``, ``test_s2_property.py``, ``known-failures.yaml``,
``conftest.py``) into the destination dir. Each rendered file carries commented
guidance plus a labeled ``# testvibe:keep <label>`` block (anchored by a
``# testvibe:slot:<label>`` marker) where tool-specific code lives.

``upgrade(dest)`` regenerates each surface from the current templates while
preserving every ``# testvibe:keep <label>`` block found in the existing file:
the surrounding scaffolding is refreshed, the kept blocks are spliced into the
matching ``# testvibe:slot:<label>`` markers in the new template. A keep block
is never overwritten; user code is never dropped.

Design notes
------------
* Templates use stdlib :class:`string.Template` with a single ``$contract``
  placeholder (the contract file stem, purely cosmetic).
* Templates are loaded by path (``Path(__file__).parent / "templates"``); they
  ship next to this module in the wheel (hatchling includes the whole package
  dir, so the ``.tmpl`` files are packaged automatically — no pyproject change
  needed).
* The contract is used by **name only** in C1/C2; schema-driven generation from
  the contract body is a later task.
"""

from __future__ import annotations

import pathlib
import re
from string import Template

__all__ = ["SURFACES", "generate", "upgrade"]

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

# Ordered (template_name, output_name) pairs for the four testvibe surfaces.
SURFACES: list[tuple[str, str]] = [
    ("test_s1_boundary.py.tmpl", "test_s1_boundary.py"),
    ("test_s2_property.py.tmpl", "test_s2_property.py"),
    ("known-failures.yaml.tmpl", "known-failures.yaml"),
    ("conftest.py.tmpl", "conftest.py"),
]

# Default contract name used when none can be recovered (e.g. upgrade on a
# hand-edited file with no `# testvibe:contract:` line).
_DEFAULT_CONTRACT = "testvibe"

# Regex for `# testvibe:contract: <name>` recovery during upgrade.
_CONTRACT_RE = re.compile(r"^# testvibe:contract:\s*(.+?)\s*$", re.MULTILINE)

# Regex for extracting kept blocks from an existing generated file:
# `# testvibe:keep <label>\n<body># end testvibe:keep`.
_KEEP_RE = re.compile(
    r"^# testvibe:keep (\S+)\n(.*?)^# end testvibe:keep",
    re.MULTILINE | re.DOTALL,
)


def _template_text(template_name: str) -> str:
    path = _TEMPLATES_DIR / template_name
    if not path.is_file():
        raise FileNotFoundError(f"testvibe template missing: {path}")
    return path.read_text(encoding="utf-8")


def _contract_name(contract: str | pathlib.Path | None) -> str:
    if contract is None:
        return _DEFAULT_CONTRACT
    try:
        return pathlib.Path(contract).stem or _DEFAULT_CONTRACT
    except (TypeError, ValueError):
        return _DEFAULT_CONTRACT


def _render(template_name: str, contract: str) -> str:
    return Template(_template_text(template_name)).substitute(contract=contract)


def generate(contract: str | pathlib.Path | None, dest: str | pathlib.Path) -> None:
    """Render the four testvibe surfaces into ``dest``.

    Creates ``dest`` (including parents) if missing. Overwrites existing
    surface files wholesale — this is the *initial* scaffolder; use
    :func:`upgrade` to refresh while preserving keep blocks. Idempotent: the
    same ``contract`` always yields byte-identical output.
    """
    dest_path = pathlib.Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    name = _contract_name(contract)
    for template_name, out_name in SURFACES:
        (dest_path / out_name).write_text(_render(template_name, name), encoding="utf-8")


def upgrade(dest: str | pathlib.Path) -> None:
    """Refresh every testvibe surface in ``dest``, preserving keep blocks.

    For each surface file present in ``dest``: extract its ``# testvibe:keep
    <label>`` blocks, regenerate from the current template, and splice each
    kept block into the matching ``# testvibe:slot:<label>`` marker. Kept
    blocks whose label no longer exists in the new template are appended (user
    code is never silently dropped). Files not present in ``dest`` are left
    untouched (upgrade refreshes; it does not seed missing surfaces).
    """
    dest_path = pathlib.Path(dest)
    for template_name, out_name in SURFACES:
        out_file = dest_path / out_name
        if not out_file.is_file():
            continue
        old = out_file.read_text(encoding="utf-8")
        contract_match = _CONTRACT_RE.search(old)
        contract = contract_match.group(1) if contract_match else _DEFAULT_CONTRACT
        kept = {m.group(1): m.group(2) for m in _KEEP_RE.finditer(old)}
        new_content = _render(template_name, contract)
        new_content = _splice_kept(new_content, kept)
        out_file.write_text(new_content, encoding="utf-8")


def _slot_labels(content: str) -> list[str]:
    return re.findall(r"^# testvibe:slot:(\S+)", content, re.MULTILINE)


def _splice_kept(new_content: str, kept: dict[str, str]) -> str:
    """Splice each kept block into the matching slot in ``new_content``.

    Kept labels that have a slot in the new template replace the default block
    body in place. Kept labels with no slot are appended at the end so user
    code is preserved.
    """
    present = set(_slot_labels(new_content))
    for label, body in kept.items():
        if label in present:
            pattern = re.compile(
                r"(^# testvibe:slot:" + re.escape(label) + r"\n"
                r"^# testvibe:keep " + re.escape(label) + r"\n)"
                r".*?"
                r"(^# end testvibe:keep)",
                re.MULTILINE | re.DOTALL,
            )
            # Splice the kept block body into the slot's keep marker. ``body``
            # is bound as a default arg so each iteration captures its own value
            # (avoids late-binding closures); the explicit ``re.Match[str]``
            # annotation lets mypy infer the lambda/def return type cleanly.
            def _splice(m: re.Match[str], body: str = body) -> str:
                return m.group(1) + body + m.group(2)

            new_content, _ = pattern.subn(_splice, new_content, count=1)
        else:
            # Orphan: append so user code is never dropped.
            new_content = new_content.rstrip("\n") + "\n"
            new_content += (
                f"\n# testvibe:slot:{label}\n"
                f"# testvibe:keep {label}\n"
                f"{body}"
                f"# end testvibe:keep\n"
            )
    return new_content
