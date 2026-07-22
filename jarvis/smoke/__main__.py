"""
Entrypoint for Level-2 smoke: ``python -m jarvis.smoke``.

    python -m jarvis.smoke                       # all CLI scenarios, print report
    python -m jarvis.smoke --platform cli        # explicit platform
    python -m jarvis.smoke path/to/scenarios/    # a custom scenario dir
    python -m jarvis.smoke --report smoke.txt    # also write the report to a file

Exit code is non-zero when any scenario failed, so CI can gate on it. Only the
``cli`` platform has a driver today; ``web``/``mobile`` are recognised names that
report "no adapter" until their UIs exist.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .cli import CLIAdapter
from .report import render_report
from .runner import load_scenarios, run_suite

_DEFAULT_SCENARIOS = Path(__file__).resolve().parent / "scenarios"

# platform → zero-arg factory that builds a fresh adapter. Add web/mobile here.
_ADAPTERS = {
    "cli": CLIAdapter,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.smoke",
                                     description="Level-2 UI smoke, driven through the real interface.")
    parser.add_argument("scenarios", nargs="?", default=str(_DEFAULT_SCENARIOS),
                        help="a scenario .json file or a directory of them")
    parser.add_argument("--platform", default="cli", choices=sorted(_ADAPTERS) + ["web", "mobile"],
                        help="which interface to drive (default: cli)")
    parser.add_argument("--report", help="write the report to this file as well as stdout")
    args = parser.parse_args(argv)

    factory = _ADAPTERS.get(args.platform)
    if factory is None:
        print(f"no smoke adapter for platform '{args.platform}' yet — "
              f"it has no UI to drive. Available: {', '.join(sorted(_ADAPTERS))}.",
              file=sys.stderr)
        return 2

    scenarios = load_scenarios(args.scenarios)
    results = run_suite(factory, scenarios, args.platform)
    report = render_report(results)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    return 0 if all(r.passed for r in results) and results else 1


if __name__ == "__main__":
    raise SystemExit(main())
