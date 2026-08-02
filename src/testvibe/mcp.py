"""testvibe.mcp - FastMCP server exposing the testvibe engine to coding agents.

This is a thin, DATA-ONLY RPC layer (Task B4 / Spec S8). The server makes **no
LLM and no network calls** of its own; it wires the existing testvibe
primitives - the scenario runner, :class:`~testvibe.report.RunReport`, the
:mod:`testvibe.advisory` analyzer, and the captured-failure
:mod:`testvibe.corpus` - into six named tools a coding agent invokes to observe
runs, surface coverage gaps, and grow the quarantine corpus. All interpretation
of the returned rows stays with the agent.

``build_server(contract_path=None)`` constructs the server. ``contract_path=None``
uses ``./testvibe.yaml`` in the cwd if present, else an empty contract (empty
fixture/touched sets, no transcript) so the advisory tools simply return ``[]``
until the agent feeds them data, and the corpus path defaults to
``./known-failures.yaml``. Optional kwargs (``corpus_path``, ``fixture_paths``,
``touched_paths``, ``transcript``, ``baseline``, ``cwd``) override those
defaults so callers - and tests - can pin a deterministic surface without
depending on cwd state.

State (run reports + their advisory rows) is held in-process, keyed by the
``run_id`` that ``run_scenario`` returns.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastmcp import FastMCP

from . import _run, advisory, corpus
from .report import RunReport

__all__ = ["build_server"]


def _adv_to_dict(a: advisory.Advisory) -> dict[str, str]:
    return {"kind": a.kind, "message": a.message, "detail": a.detail}


def _classify_corpus_error(exc: corpus.CorpusError) -> str:
    """Map a CorpusError to a specific MCP error marker.

    CorpusError now covers three distinct caller bugs (missing file, unknown id,
    corrupt YAML / non-dict row) that previously all collapsed to ``not_found``
    on the MCP surface. Inspect the message so an agent can branch on the real
    cause rather than guessing. Falls back to ``corpus_error`` for anything
    unrecognized so future CorpusError shapes are still graceful (never a raise).
    """
    msg = str(exc).lower()
    if "not found" in msg and "entry id" in msg:
        return "not_found"
    if "corpus file not found" in msg or "no such file" in msg:
        return "corpus_missing"
    if "malformed yaml" in msg or "not a list" in msg or "not a mapping" in msg:
        return "corpus_corrupt"
    return "corpus_error"


def build_server(
    contract_path: str | Path | None = None,
    *,
    corpus_path: str | Path | None = None,
    fixture_paths: list[str] | None = None,
    touched_paths: list[str] | None = None,
    transcript: str | None = None,
    baseline: float | None = None,
    cwd: str | Path | None = None,
) -> FastMCP:
    """Build a FastMCP server exposing the testvibe engine as six named tools.

    Tools exposed (names are the contract an agent depends on):

      * ``run_scenario(name)``          - run a testvibe scenario; return ``run_id``.
      * ``get_run_report(run_id)``      - the run's :class:`RunReport` as JSON.
      * ``list_coverage_gaps()``        - ``advisory.analyze`` ``coverage_gap`` rows.
      * ``list_advisories(run_id)``     - advisory rows recorded for a run.
      * ``add_corpus_entry(...)``       - append a captured failure to the corpus.
      * ``promote_corpus(id)``          - flip a corpus entry to ``status: fixed``.

    Parameters
    ----------
    contract_path:
        Path to a ``testvibe.yaml`` contract. ``None`` (default) uses
        ``./testvibe.yaml`` in the cwd if present, else an empty contract (empty
        fixture/touched sets, no transcript) so the advisory tools return ``[]``
        until the agent feeds them data. If a path is given and exists, it is
        parsed (best-effort) for
        ``fixture_paths``/``touched_paths``/``transcript``/``baseline`` defaults.
    corpus_path:
        Path to ``known-failures.yaml``. Defaults to ``./known-failures.yaml``
        (cwd) when not given. The corpus tools read/append this file.
    fixture_paths / touched_paths / transcript / baseline:
        Optional overrides feeding :func:`testvibe.advisory.analyze`. Explicit
        kwargs take precedence over values pulled from the contract.
    cwd:
        Working directory for the pytest subprocess invoked by
        ``run_scenario``. Defaults to the current working directory.
    """
    m = FastMCP("testvibe")

    # ---- configuration -----------------------------------------------------
    contract = _load_contract(contract_path)

    cfg_cwd = str(cwd) if cwd is not None else None
    cfg_corpus = (
        Path(corpus_path)
        if corpus_path is not None
        else Path("known-failures.yaml")
    )
    cfg_fixtures = _coerce_str_list(fixture_paths, contract, "fixture_paths")
    cfg_touched = _coerce_str_list(touched_paths, contract, "touched_paths")
    if baseline is None:
        contract_baseline = contract.get("baseline")
        cfg_baseline = (
            float(contract_baseline) if contract_baseline is not None else None
        )
    else:
        cfg_baseline = float(baseline)

    # ---- in-process run state ---------------------------------------------
    _runs: dict[str, RunReport] = {}
    _run_advisories: dict[str, list[dict[str, str]]] = {}

    # ---- tools -------------------------------------------------------------

    @m.tool()
    def run_scenario(name: str) -> str:
        """Invoke pytest on a testvibe scenario and return its ``run_id``.

        Runs ``pytest -m testvibe_scenario -k <name>`` as a subprocess in the
        configured cwd, captures pass/fail + output, and stores a
        :class:`RunReport` keyed by the returned ``run_id``. Use
        ``get_run_report`` / ``list_advisories`` with that id to inspect it.

        Delegates the pytest-subprocess + tri-state-exit-code work to
        :func:`testvibe._run.run_scenarios` so the CLI ``run`` command and this
        tool share one orchestrator. The report is then tagged
        ``tool="testvibe-mcp"`` so MCP-sourced runs are distinguishable, and the
        captured output is fed through :func:`testvibe.advisory.analyze` for
        smell/coverage signals.
        """
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        report = _run.run_scenarios(cwd=cfg_cwd, name=name)
        report.tool = "testvibe-mcp"

        # Reconstruct the combined output transcript for the advisory analyzer.
        # run_scenarios keeps the FULL (stdout+stderr) on report._full_output (a
        # private attribute, NOT part of the RunReport dataclass surface) so the
        # advisory analyzer sees the whole transcript while Failure.detail stays
        # bounded ([-4000:]) for the stored/report surface. On a pass there is no
        # failure row and the transcript is empty (matching the pre-refactor
        # pass-path behavior where advisory received transcript="" and returned
        # coverage gaps only).
        combined = getattr(report, "_full_output", "")
        if not combined and report.failures:
            combined = report.failures[0].detail

        # Feed the run output through the advisory analyzer so the agent gets
        # smell/coverage signals alongside the pass/fail verdict. ``report=[]``
        # because the op-level p90 records live elsewhere; here we only want the
        # transcript/coverage branches of analyze().
        adv_rows = advisory.analyze(
            report=[],
            baseline=cfg_baseline,
            fixture_paths=cfg_fixtures,
            touched_paths=cfg_touched,
            transcript=combined,
        )
        _runs[run_id] = report
        _run_advisories[run_id] = [_adv_to_dict(a) for a in adv_rows]
        return run_id

    @m.tool()
    def get_run_report(run_id: str) -> str:
        """Return the stored :class:`RunReport` for ``run_id`` as JSON.

        An unknown ``run_id`` yields a JSON object with an ``error`` marker
        rather than raising, so an agent can branch on it cleanly.
        """
        report = _runs.get(run_id)
        if report is None:
            return json.dumps(
                {"run_id": run_id, "error": "unknown run_id"}
            )
        return report.to_json()

    @m.tool()
    def list_coverage_gaps() -> list[dict[str, str]]:
        """Return ``coverage_gap`` advisory rows.

        A coverage gap is a path touched by dogfood/canary traces but absent
        from the configured fixture set - the data the agent turns into new
        scenarios. No LLM, no network: pure set difference via
        :func:`testvibe.advisory.analyze`.
        """
        rows = advisory.analyze(
            report=[],
            baseline=None,
            fixture_paths=cfg_fixtures,
            touched_paths=cfg_touched,
            transcript="",
        )
        return [_adv_to_dict(a) for a in rows if a.kind == "coverage_gap"]

    @m.tool()
    def list_advisories(run_id: str) -> list[dict[str, str]]:
        """Return the advisory rows recorded for ``run_id`` (``[]`` if unknown)."""
        return list(_run_advisories.get(run_id, []))

    @m.tool()
    def add_corpus_entry(
        id: str, invariant: str, repro_path: str, status: str = "open"
    ) -> dict[str, str]:
        """Append a captured failure to ``known-failures.yaml``.

        ``discovered_at`` (today) and ``source="mcp"`` are filled so the row
        satisfies :class:`testvibe.corpus.CorpusEntry`'s required fields and is
        immediately picked up by the plugin's quarantine collection hook.

        Routes through :func:`testvibe.corpus.add_entry` so known-failures.yaml
        has a single mutation path (the CLI ``corpus add`` uses the same fn).

        Returns a structured ``{error, message}`` dict (never raises) for
        parity with :func:`promote_corpus` so an agent can branch on the marker
        rather than catching an RPC exception.
        """
        try:
            entry = corpus.add_entry(
                cfg_corpus,
                corpus.CorpusEntry(
                    id=id,
                    invariant=invariant,
                    discovered_at=date.today().isoformat(),
                    source="mcp",
                    repro=repro_path,
                    status=status,
                ),
            )
        except corpus.CorpusError as exc:
            return {
                "id": id,
                "error": _classify_corpus_error(exc),
                "message": str(exc),
            }
        return {
            "id": entry.id,
            "invariant": entry.invariant,
            "discovered_at": entry.discovered_at,
            "source": entry.source,
            "repro": entry.repro,
            "status": entry.status,
        }

    @m.tool()
    def promote_corpus(id: str) -> dict[str, str]:
        """Flip a corpus entry to ``status: fixed`` and drop its xfail pin.

        Delegates to :func:`testvibe.corpus.promote_entry` with ``passes=True``
        (the MCP surface is the "after a green re-run" path — the agent has
        already confirmed the repro passes before calling promote). Because
        :func:`testvibe.corpus.load_corpus` only collects ``open``/``pinned``
        entries, a fixed entry naturally drops out of the xfail quarantine set -
        no separate "delete xfail" step is needed.
        """
        try:
            entry = corpus.promote_entry(cfg_corpus, id, passes=True)
        except corpus.CorpusError as exc:
            return {
                "id": id,
                "status": "unknown",
                "error": _classify_corpus_error(exc),
                "message": str(exc),
            }
        return {
            "id": entry.id,
            "invariant": entry.invariant,
            "discovered_at": entry.discovered_at,
            "source": entry.source,
            "repro": entry.repro,
            "status": entry.status,
        }

    return m


# ----------------------------------------------------------------------
# contract helpers (module-level; pure, no FastMCP dependency)
# ----------------------------------------------------------------------


def _load_contract(contract_path: str | Path | None) -> dict[str, Any]:
    """Best-effort parse of a ``testvibe.yaml`` contract for advisory defaults.

    ``contract_path=None`` falls back to ``./testvibe.yaml`` when present, else
    a no-op empty dict. A missing/malformed/non-mapping file degrades to ``{}``
    so the server always builds.
    """
    p = Path(contract_path) if contract_path is not None else Path("testvibe.yaml")
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _coerce_str_list(
    explicit: list[str] | None,
    contract: dict[str, Any],
    key: str,
) -> list[str]:
    """Pick the explicit list, else the contract's list for ``key``, else ``[]``."""
    if explicit is not None:
        return [str(x) for x in explicit]
    raw = contract.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []
