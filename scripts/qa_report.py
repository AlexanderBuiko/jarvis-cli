"""
QA gate — run both test levels and collect ONE report.

The Day-3 flow: after a change, the agent runs Level-1 code tests and Level-2 UI
smoke and produces a single verdict. This script is that gate. It runs pytest,
then the smoke suite, captures both, and writes one combined report; it exits
non-zero if either level failed, so CI (and a human) can gate on it.

Usage:
    python scripts/qa_report.py                 # print the report
    python scripts/qa_report.py --report qa.md  # also write it to a file

This is a dev/CI entry point, so printing here is correct (like jarvis/review).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / ".venv" / "bin" / "python")
if not Path(PYTHON).exists():          # fall back to the current interpreter
    PYTHON = sys.executable

_RULE = "═" * 70


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run ``cmd`` from the repo root; return (exit code, combined output)."""
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _level_1() -> tuple[bool, str]:
    """Level 1 — the code test suite."""
    code, out = _run([PYTHON, "-m", "pytest", "-q"])
    return code == 0, out.strip()


def _level_2() -> tuple[bool, str]:
    """Level 2 — the UI smoke suite (CLI platform, the deterministic gate)."""
    code, out = _run([PYTHON, "-m", "jarvis.smoke"])
    return code == 0, out.strip()


def _playwright_available() -> bool:
    """True when the optional web extra is installed and its browser present."""
    code, _ = _run([PYTHON, "-c", "import playwright"])
    return code == 0


def _level_2_web() -> tuple[bool | None, str]:
    """Level 2 (web) — headless-browser smoke. Optional: skipped (None) when
    Playwright is not installed, so the base gate never depends on a browser."""
    if not _playwright_available():
        return None, "skipped — playwright not installed (pip install -e .[web])"
    scenarios = str(ROOT / "jarvis" / "smoke" / "scenarios" / "web")
    code, out = _run([PYTHON, "-m", "jarvis.smoke", "--platform", "web", scenarios])
    return code == 0, out.strip()


def _verdict(ok: bool | None) -> str:
    return "SKIP" if ok is None else ("PASS" if ok else "FAIL")


def build_report() -> tuple[bool, str]:
    """Run the levels and render one report; return (all passed, report text).

    The web tier is optional: when Playwright is absent it is SKIPped and does not
    fail the gate, keeping the fast CLI path free of a browser dependency."""
    l1_ok, l1_out = _level_1()
    l2_ok, l2_out = _level_2()
    web_ok, web_out = _level_2_web()
    # A skipped (None) web tier does not count against the overall result.
    overall = l1_ok and l2_ok and web_ok is not False

    lines = [
        _RULE,
        f"QA REPORT — {'PASS' if overall else 'FAIL'}",
        _RULE,
        f"  Level 1 (code tests)     : {_verdict(l1_ok)}",
        f"  Level 2 (UI smoke, cli)  : {_verdict(l2_ok)}",
        f"  Level 2 (UI smoke, web)  : {_verdict(web_ok)}",
        "",
        "── Level 1: code tests " + "─" * 47,
        l1_out or "(no output)",
        "",
        "── Level 2: UI smoke — cli " + "─" * 43,
        l2_out or "(no output)",
        "",
        "── Level 2: UI smoke — web " + "─" * 43,
        web_out or "(no output)",
    ]
    if not overall:
        lines += [
            "",
            _RULE,
            "WHERE TO LOOK",
            "  - Level 1 fail → a code test broke; the pytest output above names it.",
            "  - Level 2 fail → a smoke step broke; its captured terminal output above",
            "    shows what the interface returned instead of the expected text.",
        ]
    return overall, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/qa_report.py",
                                     description="Run Level-1 code tests + Level-2 smoke, one report.")
    parser.add_argument("--report", help="write the combined report to this file as well as stdout")
    args = parser.parse_args(argv)

    ok, report = build_report()
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
