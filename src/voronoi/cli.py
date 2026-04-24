"""voronoi CLI.

Entry points:

- ``voronoi reproduce --N 8`` — run Layer A tally on N=8.
- ``voronoi extend --N 9 --n 12`` — Layer B enumeration (not yet).
"""

from __future__ import annotations

import argparse
import sys


def _cmd_reproduce(args: argparse.Namespace) -> int:
    print(f"voronoi reproduce --N {args.N}: not implemented yet.")
    print("Layer A tasks (see PLAN.md):")
    print("  1. Parser   — partial (parse/pari_gp.py)")
    print("  2. Stab     — stub (stab.py, blocked on noether qfauto)")
    print("  3. χ_σ      — stub (orientation.py)")
    print("  4. Boundary — stub (complex.py)")
    print("  5. Homology — stub (homology.py)")
    return 1


def _cmd_extend(args: argparse.Namespace) -> int:
    print(f"voronoi extend --N {args.N} --n {args.n}: Layer B, not started.")
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="voronoi")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reproduce", help="Layer A reproducibility run")
    r.add_argument("--N", type=int, required=True, help="lattice rank")
    r.set_defaults(func=_cmd_reproduce)

    e = sub.add_parser("extend", help="Layer B cell enumeration")
    e.add_argument("--N", type=int, required=True)
    e.add_argument("--n", type=int, required=True, help="cell dimension")
    e.set_defaults(func=_cmd_extend)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
