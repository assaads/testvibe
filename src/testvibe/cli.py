"""``testvibe`` console-script entry point.

Subcommands:

* ``init <contract> --into <dest>`` — scaffold the four testvibe surfaces
  (:func:`testvibe.scaffold.generate`).
* ``upgrade <dest>`` — refresh scaffolding, preserving ``# testvibe:keep``
  blocks (:func:`testvibe.scaffold.upgrade`).
* ``run [--cwd <dir>]`` — run the hermetic scenario gate (S0):
  ``pytest -m testvibe_scenario`` and exit 0 (pass) / 1 (product) / 2 (infra).
* ``corpus add --invariant <s> --repro <path> [--corpus <p>] [--id <s>]`` —
  append a captured failure to ``known-failures.yaml``.
* ``corpus promote <id> [--corpus <p>]`` — flip a corpus entry to ``fixed``
  after a green re-run (the only promotion path).

Honest exit-3 stubs (need external prerequisites the CLI cannot provide):

* ``dogfood`` / ``canary`` — need a real host + scratch resource + scoped
  credential (S3/S4 surface). Exit 3.
* ``autopilot`` — is the AI autopilot skill; run via Claude Code, not the CLI.
  Exit 3.

Exit-code convention: 0 = success; 1 = product failure (a scenario assertion
failed); 2 = infra failure (collection error, usage error, no subcommand);
3 = honestly needs an external host/agent (not a bug, not "not implemented").
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from testvibe import corpus, scaffold

# Exit codes.
_RC_SUCCESS = 0
_RC_PRODUCT = 1
_RC_INFRA = 2
_RC_NEEDS_HOST_AGENT = 3

# Default corpus path (relative to cwd) when --corpus is not given.
_DEFAULT_CORPUS = "known-failures.yaml"


def _cmd_init(args: argparse.Namespace) -> int:
    scaffold.generate(args.contract, args.into)
    return _RC_SUCCESS


def _cmd_upgrade(args: argparse.Namespace) -> int:
    scaffold.upgrade(args.dest)
    return _RC_SUCCESS


def _cmd_run(args: argparse.Namespace) -> int:
    """Run the hermetic scenario gate; map tri-state exit to CLI codes."""
    from testvibe._run import run_scenarios

    cwd = args.cwd if args.cwd is not None else None
    report = run_scenarios(cwd=cwd)
    sys.stdout.write(report.to_markdown())
    sys.stdout.write("\n")
    if report.passed:
        return _RC_SUCCESS
    # A failure is product (rc 1) unless the only failure is infra.
    kinds = {f.kind for f in report.failures}
    if kinds == {"infra"} or (kinds and "product" not in kinds):
        return _RC_INFRA
    return _RC_PRODUCT


def _cmd_corpus_add(args: argparse.Namespace) -> int:
    """Append a captured failure to the corpus."""
    repro = Path(args.repro)
    # Must be a FILE, not a directory: repro.is_file() is False for dirs even
    # though dir.exists() is True. Fail fast at the CLI boundary so a typo'd
    # directory path does not get recorded as a repro.
    if not repro.is_file():
        sys.stderr.write(
            f"testvibe: repro file not found: {repro}\n"
        )
        return _RC_INFRA
    entry_id = args.id if args.id else f"entry-{uuid.uuid4().hex[:12]}"
    entry = corpus.add_entry(
        Path(args.corpus),
        corpus.CorpusEntry(
            id=entry_id,
            invariant=args.invariant,
            discovered_at=date.today().isoformat(),
            source="cli",
            repro=str(repro),
            status=args.status,
        ),
    )
    sys.stdout.write(
        f"added corpus entry id={entry.id} status={entry.status} "
        f"-> {args.corpus}\n"
    )
    return _RC_SUCCESS


def _cmd_corpus_promote(args: argparse.Namespace) -> int:
    """Flip a corpus entry to fixed after a green re-run.

    Per the I/O matrix: "re-run not green -> non-zero" and the PLAYBOOK:
    promotion is "only after a deterministic green re-run." So BEFORE flipping
    status, the CLI actually executes the entry's repro. If the repro raises
    (AssertionError or anything else) the bug is NOT fixed -> return the product
    failure code (a real product signal, not infra). Only a clean repro run is
    handed to ``promote_entry(passes=True)``.
    """
    p = Path(args.corpus)
    # Find the entry by id via load_corpus (which filters to open/pinned — the
    # only statuses that can be promoted). A missing file or unknown id is a
    # real caller bug, not a product signal.
    try:
        entries = corpus.load_corpus(p)
    except corpus.CorpusError as e:
        sys.stderr.write(f"testvibe: promote failed: {e}\n")
        return _RC_INFRA
    target = next((e for e in entries if e.id == args.id), None)
    if target is None:
        sys.stderr.write(
            f"testvibe: entry id {args.id!r} not found in corpus {p}\n"
        )
        return _RC_INFRA
    # Actually execute the repro. A still-failing repro means the bug is not
    # fixed -> do NOT promote, return the product failure code.
    try:
        repro_fn = corpus._load_repro(target.repro)
        repro_fn()
    except Exception as e:  # any repro failure means not-green
        sys.stderr.write(
            f"testvibe: repro for {args.id} still fails; not promoted ({e})\n"
        )
        return _RC_PRODUCT
    try:
        entry = corpus.promote_entry(p, args.id, passes=True)
    except corpus.CorpusError as e:
        sys.stderr.write(f"testvibe: promote failed: {e}\n")
        return _RC_INFRA
    sys.stdout.write(
        f"promoted corpus entry id={entry.id} -> status={entry.status}\n"
    )
    return _RC_SUCCESS


def _needs_host_agent(name: str) -> Callable[[argparse.Namespace], int]:
    """Honest exit-3 stub for commands needing an external host/agent.

    ``dogfood``/``canary`` need a real host + scratch resource + scoped
    credential (S3/S4 surface); ``autopilot`` IS the AI autopilot skill (run via
    Claude Code, not the CLI). Exit 3 distinguishes "honestly needs external
    prerequisites" from a generic "not implemented" (exit 2) — so a human or
    agent reading the code knows exactly what external thing is missing rather
    than guessing whether the feature is merely unfinished.
    """

    def _cmd(_args: argparse.Namespace) -> int:
        if name == "autopilot":
            sys.stderr.write(
                "testvibe: 'autopilot' is the AI autopilot skill — run it via "
                "Claude Code (ask 'run testvibe on this tool'), not the CLI. "
                "The CLI makes no LLM calls; the agent IS the autopilot.\n"
            )
        else:
            sys.stderr.write(
                f"testvibe: '{name}' needs a real host + scratch resource + "
                f"scoped credential (S3/S4 surface). It cannot run hermetically "
                f"from the CLI — point it at a real environment.\n"
            )
        return _RC_NEEDS_HOST_AGENT

    return _cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testvibe",
        description="scenario-driven, agent-driven real-usage testing for any tool",
    )
    sub = parser.add_subparsers(dest="cmd")

    # ---- init ----
    p_init = sub.add_parser("init", help="scaffold testvibe surfaces into a tests dir")
    p_init.add_argument("contract", help="path to the tool's testvibe contract file")
    p_init.add_argument(
        "--into", required=True, dest="into", help="destination tests directory"
    )
    p_init.set_defaults(func=_cmd_init)

    # ---- upgrade ----
    p_upgrade = sub.add_parser(
        "upgrade", help="refresh scaffolding, preserving # testvibe:keep blocks"
    )
    p_upgrade.add_argument("dest", help="tests directory previously created by `init`")
    p_upgrade.set_defaults(func=_cmd_upgrade)

    # ---- run (real) ----
    p_run = sub.add_parser("run", help="run the hermetic scenario gate (S0)")
    p_run.add_argument(
        "--cwd",
        default=None,
        help="working directory for pytest (defaults to cwd)",
    )
    p_run.set_defaults(func=_cmd_run)

    # ---- corpus add / promote (real) ----
    p_corpus = sub.add_parser("corpus", help="manage the captured-failure corpus")
    corpus_sub = p_corpus.add_subparsers(dest="corpus_cmd")

    p_add = corpus_sub.add_parser("add", help="append a captured failure")
    p_add.add_argument(
        "--invariant", required=True, help="the invariant this failure violates"
    )
    p_add.add_argument(
        "--repro", required=True, help="path to a .py file with a repro() callable"
    )
    p_add.add_argument(
        "--corpus",
        default=_DEFAULT_CORPUS,
        help=f"path to known-failures.yaml (default: {_DEFAULT_CORPUS})",
    )
    p_add.add_argument(
        "--id",
        default=None,
        help="entry id (auto-generated if omitted)",
    )
    p_add.add_argument(
        "--status",
        default="open",
        choices=["open", "pinned"],
        help="initial status (default: open)",
    )
    p_add.set_defaults(func=_cmd_corpus_add)

    p_promote = corpus_sub.add_parser(
        "promote", help="flip a corpus entry to fixed after a green re-run"
    )
    p_promote.add_argument("id", help="the entry id to promote")
    p_promote.add_argument(
        "--corpus",
        default=_DEFAULT_CORPUS,
        help=f"path to known-failures.yaml (default: {_DEFAULT_CORPUS})",
    )
    p_promote.set_defaults(func=_cmd_corpus_promote)

    # ---- honest exit-3 stubs ----
    for name in ("dogfood", "canary", "autopilot"):
        sp = sub.add_parser(
            name,
            help=f"`testvibe {name}` — needs a real host/agent (exit 3)",
        )
        sp.set_defaults(func=_needs_host_agent(name))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a ``testvibe`` subcommand. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        # No subcommand given (e.g. bare `testvibe`) or `corpus` without a
        # sub-subcommand: print help and return a clear non-zero code.
        parser.print_help(sys.stderr)
        return _RC_INFRA
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
