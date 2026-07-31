"""testvibe.report — RunReport builder with detect-secrets redaction.

RunReport serializes a test run (failures + advisories) to JSON and markdown.
All output is run through :func:`redact`, which masks secrets using
``detect-secrets`` (when its scanner API is available) and a defensive regex
for well-known token prefixes (ghp_, ghs_, AKIA, xox[baprs]-) so secrets never
leak regardless of which detect-secrets plugins are active.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Failure", "RunReport", "redact"]

# Well-known token prefixes we always mask defensively. detect-secrets only
# reports secrets for plugins that are active at runtime; with the default
# install zero plugins are active, so this regex is the guaranteed backstop.
_SECRET_PREFIX_RE = re.compile(r"(ghp_|ghs_|AKIA|xox[baprs]-)[A-Za-z0-9]{6,}")

_REDACTED = "***REDACTED***"

# Defensively import detect-secrets' line scanner. If the scanner API is
# unavailable (older/newer detect-secrets, or a stripped build), redaction
# falls back to the regex backstop above. The explicit annotation makes the
# optional-import pattern type-check cleanly (local name is the union, not
# ``object`` inferred from the ``None`` fallback).
_ds_scan_line: Callable[[str], Generator[Any, None, None]] | None = None
try:  # pragma: no cover - import guard
    from detect_secrets.core.scan import scan_line as _ds_scan_line
except Exception:
    _ds_scan_line = None


def _regex_mask(text: str) -> str:
    """Mask well-known token prefixes defensively."""

    def _sub(match: re.Match[str]) -> str:
        return f"{match.group(1)}{_REDACTED}"

    return _SECRET_PREFIX_RE.sub(_sub, text)


def redact(text: str) -> str:
    """Mask secrets in *text* via detect-secrets + defensive regex prefixes.

    The detect-secrets path scans each line for active-plugin findings and
    masks the reported secret values. The regex path is then applied
    unconditionally so the well-known prefixes are always masked even when no
    detect-secrets plugin is active.
    """
    if not isinstance(text, str) or not text:
        return text

    # 1. detect-secrets findings (only if a scanner is importable + active).
    if _ds_scan_line is not None:
        secrets = set()
        try:
            for line in text.splitlines():
                for finding in _ds_scan_line(line):
                    value = getattr(finding, "secret_value", None)
                    if value:
                        secrets.add(value)
        except Exception:
            secrets = set()
        for secret in secrets:
            if secret and len(secret) >= 4:
                text = text.replace(secret, _REDACTED)

    # 2. Defensive regex backstop — always applied.
    return _regex_mask(text)


@dataclass
class Failure:
    """A single failure, tagged infra vs product.

    - ``infra``: the harness/environment is at fault (flaky boundary, scrubbed
      env, network). Not a product regression.
    - ``product``: the tool itself misbehaved. A real regression.
    """

    kind: str
    message: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("infra", "product"):
            raise ValueError(
                f"Failure.kind must be 'infra' or 'product', got {self.kind!r}"
            )


@dataclass
class RunReport:
    """JSON + markdown report for one testvibe run, with secret redaction."""

    tool: str
    run: str
    passed: bool
    failures: list[Failure] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)

    def add_failure(self, failure: Failure) -> None:
        """Record a failure (infra or product)."""
        self.failures.append(failure)

    def add_advisory(self, advisory: str) -> None:
        """Record a non-blocking advisory (slow-but-passing, smell, gap)."""
        self.advisories.append(advisory)

    def to_json(self) -> str:
        """Serialize the report to a redacted JSON string."""
        payload = {
            "tool": self.tool,
            "run": self.run,
            "passed": self.passed,
            "failures": [
                {"kind": f.kind, "message": f.message, "detail": f.detail}
                for f in self.failures
            ],
            "advisories": list(self.advisories),
        }
        return redact(json.dumps(payload, indent=2))

    def to_markdown(self) -> str:
        """Serialize the report to redacted markdown, always including an
        ``## Advisory`` section."""
        lines = [
            f"# Testvibe Report: {self.tool} ({self.run})",
            "",
            f"**Passed:** {self.passed}",
            "",
        ]
        if self.failures:
            lines.append("## Failures")
            for f in self.failures:
                lines.append(f"- **[{f.kind}]** {f.message}: {f.detail}")
            lines.append("")
        lines.append("## Advisory")
        if self.advisories:
            for a in self.advisories:
                lines.append(f"- {a}")
        else:
            lines.append("- None")
        lines.append("")
        return redact("\n".join(lines))
