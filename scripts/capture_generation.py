"""
Capture one generation of the rules-file experiment and score it.

The week-8 task compares two runs of an identical prompt under different
`CLAUDE.md` versions. Scoring by hand invites drift — you remember the rubric
differently once you have seen the diff — so every mechanical criterion is
checked here and written to disk as evidence. The script never judges style; it
only reports what it can verify by running the code.

Run this from the repo root with the generated (uncommitted) code still in the
working tree.

Usage:
    python scripts/capture_generation.py gen1
    python scripts/capture_generation.py gen2 --command notes

Writes docs/assistant-rules/<label>/ — diff, tool output, and score.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "docs" / "assistant-rules"

# `ruff check jarvis/` on the v1 commit. Criterion 2 measures *new* errors only,
# so the pre-existing F401s must not count against a generation.
BASELINE_RUFF_ERRORS = 5

PYTHON = str(ROOT / ".venv" / "bin" / "python")
RUFF = str(ROOT / ".venv" / "bin" / "ruff")


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run ``cmd`` in the repo root, returning (exit code, combined output)."""
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=600
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _ruff_error_count(output: str) -> int:
    """Parse ruff's trailing ``Found N errors.`` line, or 0 when it is absent."""
    for line in output.splitlines():
        if line.startswith("Found ") and "error" in line:
            return int(line.split()[1])
    return 0


def _touches(path: Path, token: str) -> bool:
    """True when ``token`` appears in ``path`` (missing file counts as False)."""
    try:
        return token in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _changed_files(status: str, codes: frozenset[str]) -> list[str]:
    """Source paths git reports under ``codes``, ignoring repo-root noise.

    Scoped to ``jarvis/`` and ``tests/`` on purpose: the repo root carries a pile
    of untracked course notes that would otherwise count as work the generation
    produced.

    Callers must distinguish *created* from *modified*. Conventions that apply to
    a new file (``from __future__ import annotations``) must not be asserted
    against a pre-existing one the generation merely edited — the rules forbid
    retrofitting them, so scoring a modification as a miss inverts the rule.
    """
    out = []
    for line in status.splitlines():
        if len(line) > 3 and line[:2].strip() in codes:
            path = line[3:].strip().strip('"')
            if path.startswith(("jarvis/", "tests/")):
                out.append(path)
    return out


def _help_text() -> str:
    """The body of ``commands.HELP_TEXT``, or "" when it cannot be located.

    Searching the whole module gives false positives — ``task.get("notes")``
    already matches a command named ``notes`` — so the criterion is checked
    against the help block alone.
    """
    src = (ROOT / "jarvis/repl/commands.py").read_text(encoding="utf-8")
    start = src.find('HELP_TEXT = """')
    if start == -1:
        return ""
    body = src[start + len('HELP_TEXT = """'):]
    end = body.find('"""')
    return body[:end] if end != -1 else body


def _listed_in_help(cmd: str) -> bool:
    """True when ``cmd`` heads a line of the help block (not just appears in it)."""
    return any(line.strip().startswith(cmd) for line in _help_text().splitlines())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="generation label, e.g. gen1")
    parser.add_argument("--command", default="notes",
                        help="the REPL command token the prompt asked for")
    args = parser.parse_args()

    out = OUT_ROOT / args.label
    out.mkdir(parents=True, exist_ok=True)
    cmd = args.command

    # ── Raw evidence ──────────────────────────────────────────────────────────
    _, status = _run(["git", "status", "--porcelain"])
    (out / "files.txt").write_text(status, encoding="utf-8")

    _, diff = _run(["git", "diff"])
    _, staged = _run(["git", "diff", "--cached"])
    (out / "changes.diff").write_text(diff + staged, encoding="utf-8")

    # `git diff` reports tracked modifications only, so a generation's *new*
    # modules — usually the substance of the work — would be absent from the
    # captured diff entirely. They are inlined into one markdown document rather
    # than copied as files: a copied `tests/test_*.py` sitting under docs/ gets
    # collected by pytest a second time, which corrupts the test count of every
    # later run.
    doc = [f"# {args.label} — files created by this generation", ""]
    for rel in _changed_files(status, frozenset({"??", "A", "AM"})):
        src = ROOT / rel
        if not src.is_file() or not rel.endswith(".py"):
            continue
        doc += [f"## `{rel}`", "", "```python",
                src.read_text(encoding="utf-8").rstrip(), "```", ""]
    (out / "new_files.md").write_text("\n".join(doc), encoding="utf-8")

    import_rc, import_out = _run([PYTHON, "-c", "import jarvis.repl.loop"])
    (out / "import.txt").write_text(f"exit={import_rc}\n{import_out}", encoding="utf-8")

    _, ruff_out = _run([RUFF, "check", "jarvis/"])
    (out / "ruff.txt").write_text(ruff_out, encoding="utf-8")

    pytest_rc, pytest_out = _run([PYTHON, "-m", "pytest", "-q"])
    (out / "pytest.txt").write_text(pytest_out, encoding="utf-8")

    # ── Criteria ──────────────────────────────────────────────────────────────
    ruff_errors = _ruff_error_count(ruff_out)
    created = _changed_files(status, frozenset({"A", "??", "AM"}))
    # Only files the generation *created* under jarvis/ carry the future-import
    # rule; tests are exempt (1 of 37 existing test modules uses it).
    new_py = [p for p in created if p.endswith(".py") and p.startswith("jarvis/")]
    new_tests = [p for p in created if p.startswith("tests/test_")]
    new_libs = [
        p for p in new_py if "/repl/" not in p
    ]

    checks: list[tuple[str, bool, str]] = [
        ("1 imports", import_rc == 0, f"exit={import_rc}"),
        ("2 lint", ruff_errors <= BASELINE_RUFF_ERRORS,
         f"{ruff_errors} errors (baseline {BASELINE_RUFF_ERRORS})"),
        ("3 tests pass", pytest_rc == 0, pytest_out.strip().splitlines()[-1] if pytest_out.strip() else ""),
        ("4 test shipped", bool(new_tests), ", ".join(new_tests) or "none"),
        ("5 dispatch", _touches(ROOT / "jarvis/repl/loop.py", f'"{cmd}"'),
         "jarvis/repl/loop.py::_dispatch"),
        ("6 help text", _listed_in_help(cmd),
         "jarvis/repl/commands.py::HELP_TEXT"),
        ("7 autocomplete", _touches(ROOT / "jarvis/repl/input.py", f'"{cmd}"'),
         "jarvis/repl/input.py::COMMAND_TREE"),
        ("8 layering", bool(new_libs) and not any(
            _touches(ROOT / p, "\n    print(") for p in new_libs),
         f"new library modules: {', '.join(new_libs) or 'none'}"),
        ("9 future import", bool(new_py) and all(
            _touches(ROOT / p, "from __future__ import annotations") for p in new_py),
         f"new jarvis/ modules: {', '.join(new_py) or 'none'}"),
    ]

    passed = sum(1 for _, ok, _ in checks if ok)
    lines = [
        f"# {args.label} — score {passed}/{len(checks)}",
        "",
        "Generated by `scripts/capture_generation.py`. Criterion 9 is a partial",
        "proxy; review the diff by hand for naming, `__all__` and PEP 604 typing.",
        "",
        "| Criterion | Result | Detail |",
        "|---|---|---|",
    ]
    for name, ok, detail in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines.append("")
    (out / "score.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nArtifacts written to {out.relative_to(ROOT)}/")
    print("Remember to save the session transcript as transcript.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
