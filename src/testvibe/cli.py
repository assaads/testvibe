"""``testvibe`` console-script entry point.

Subcommands owned by this goal:

* ``init <contract> --into <dest>`` — scaffold the four testvibe surfaces
  (:func:`testvibe.scaffold.generate`).
* ``upgrade <dest>`` — refresh scaffolding, preserving ``# testvibe:keep``
  blocks (:func:`testvibe.scaffold.upgrade`).

The remaining plan subcommands (``run``, ``corpus``, ``dogfood``, ``canary``,
``autopilot``) are owned by later goals and no-op here with a clear non-zero
exit code and an "not implemented" message — they must not crash the CLI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from testvibe import scaffold

# Exit code returned by the not-yet-implemented subcommand stubs.
_NOT_IMPLEMENTED_RC = 2


def _cmd_init(args: argparse.Namespace) -> int:
    scaffold.generate(args.contract, args.into)
    return 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    scaffold.upgrade(args.dest)
    return 0


def _not_implemented(name: str) -> Callable[[argparse.Namespace], int]:
    def _cmd(_args: argparse.Namespace) -> int:
        sys.stderr.write(f"testvibe: '{name}' is not implemented yet.\n")
        return _NOT_IMPLEMENTED_RC

    return _cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testvibe",
        description="scenario-driven, agent-driven real-usage testing for any tool",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="scaffold testvibe surfaces into a tests dir")
    p_init.add_argument("contract", help="path to the tool's testvibe contract file")
    p_init.add_argument(
        "--into", required=True, dest="into", help="destination tests directory"
    )
    p_init.set_defaults(func=_cmd_init)

    p_upgrade = sub.add_parser(
        "upgrade", help="refresh scaffolding, preserving # testvibe:keep blocks"
    )
    p_upgrade.add_argument("dest", help="tests directory previously created by `init`")
    p_upgrade.set_defaults(func=_cmd_upgrade)

    for name in ("run", "dogfood", "canary", "autopilot"):
        sp = sub.add_parser(name, help=f"(planned) `testvibe {name}` — not implemented yet")
        sp.set_defaults(func=_not_implemented(name))

    p_corpus = sub.add_parser("corpus", help="manage the scenario corpus")
    corpus_sub = p_corpus.add_subparsers(dest="corpus_cmd")
    for sub_name in ("add", "promote"):
        sc = corpus_sub.add_parser(sub_name, help=f"(planned) `testvibe corpus {sub_name}`")
        sc.set_defaults(func=_not_implemented(f"corpus {sub_name}"))

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
        return _NOT_IMPLEMENTED_RC
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
