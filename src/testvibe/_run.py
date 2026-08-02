"""testvibe._run — shared scenario-run orchestrator (Task: shared run orchestrator).

``run_scenarios`` is the single place that shells out to pytest and builds a
:class:`~testvibe.report.RunReport` from the result. Both consumers of a testvibe
run share it:

  * the CLI ``run`` command — runs ALL hermetic scenarios (``name=None``),
    i.e. ``pytest -m testvibe_scenario`` with no ``-k`` filter (the S0 gate).
  * the MCP ``run_scenario`` tool — runs ONE scenario by name (``name=<x>``),
    i.e. ``pytest -m testvibe_scenario -k <name>``.

Tri-state exit-code contract (PLAYBOOK infra-vs-product taxonomy):

  * pytest rc 0                          -> ``passed=True``, no failure row.
  * pytest rc 1                          -> ``passed=False``, failure ``kind="product"``.
  * pytest rc 2/3/4/5 or ``TimeoutExpired`` -> ``passed=False``, failure ``kind="infra"``.
  * ``OSError`` (bad ``--cwd``)          -> ``passed=False``, failure ``kind="infra"``.

A rc of 1 means a scenario assertion genuinely failed (a product regression);
any other non-zero code (collection error, internal error, usage error, no
tests collected), a subprocess timeout, or an ``OSError`` from a bad cwd (the
working directory does not exist or is unreadable) is the harness/environment
misbehaving, not a product bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .report import Failure, RunReport

__all__ = ["run_scenarios"]


def run_scenarios(cwd: str | Path | None = None, *, name: str | None = None) -> RunReport:
    """Run testvibe scenarios via pytest and return a :class:`RunReport`.

    Builds the pytest invocation as ``sys.executable -m pytest -m
    testvibe_scenario`` (plus ``-k <name>`` when *name* is given), runs it as a
    subprocess in *cwd*, classifies the exit code (0 pass / 1 product /
    else+timeout infra), and returns a populated RunReport.

    Parameters
    ----------
    cwd:
        Working directory for the pytest subprocess. ``None`` uses the current
        working directory.
    name:
        Optional scenario-name filter (``pytest -k <name>``). ``None`` (the
        CLI ``run`` default) runs all hermetic scenarios — the S0 gate.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        "testvibe_scenario",
    ]
    if name is not None:
        cmd += ["-k", str(name)]
    cmd += ["-q"]

    passed = False
    infra = False
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=600,
        )
        passed = proc.returncode == 0
        if not passed and proc.returncode != 1:
            infra = True
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        # A negative returncode means the process was killed by a signal
        # (e.g. -9 SIGKILL, -15 SIGTERM). Surface that explicitly so the
        # report distinguishes signal death from a weird positive exit code.
        # Appended AFTER the stderr assignment so it is not overwritten.
        if proc.returncode < 0:
            infra = True
            stderr += f"\nkilled by signal {-proc.returncode}"
    except subprocess.TimeoutExpired as exc:
        infra = True
        # A hung pytest's stderr is the diagnostic — keep it, don't discard it.
        to_stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        to_stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stdout = to_stdout
        stderr = to_stderr + "\nscenario run timed out"
    except OSError as exc:
        # A bad --cwd (nonexistent or unreadable dir) makes subprocess.run raise
        # FileNotFoundError / PermissionError before pytest ever runs. This is
        # an infra problem (the environment/cwd is wrong), not a product bug.
        infra = True
        stdout = ""
        stderr = f"could not run pytest subprocess: {exc}"

    label = name if name is not None else "all"
    report = RunReport(tool="testvibe", run=f"scenario:{label}", passed=passed)
    combined = (stdout + "\n" + stderr).strip()
    # Keep the FULL combined output reachable for the advisory analyzer (which
    # benefits from the whole transcript) via a private attribute that is NOT
    # part of the RunReport dataclass surface (to_json/to_markdown enumerate
    # fields explicitly, so this never leaks into the serialized report).
    report._full_output = combined  # type: ignore[attr-defined]
    if not passed:
        # Failure.detail is the STORED/REPORT surface and must stay bounded so a
        # pathological pytest run cannot grow memory without limit across many
        # MCP runs. The tail carries the assertion/error signal; the full
        # transcript lives on report._full_output for the advisory path.
        bounded = combined[-4000:] if combined else "no output captured"
        report.add_failure(
            Failure(
                kind="infra" if infra else "product",
                message=(
                    f"scenario '{label}' runner failed (infra)"
                    if infra
                    else f"scenario '{label}' did not pass"
                ),
                detail=bounded,
            )
        )
    return report
