# Scoring rubric

Frozen **before** generation 1 runs. Fixing the criteria up front is what keeps
this a measurement rather than a post-hoc justification of whatever came out.

The task (`docs/assistant-rules/prompt.txt`) is stated at goal level and names no
file, no pattern and no touchpoint. Every criterion below therefore tests whether
the *rules file* carried the convention — not whether the prompt did.

## Criteria

| # | Criterion | Pass condition | Automated |
|---|---|---|---|
| 1 | Imports | `import jarvis.repl.loop` exits 0 | yes |
| 2 | Lint | `ruff check jarvis/` reports **no more than the 5 pre-existing** errors | yes |
| 3 | Tests pass | `pytest -q` green | yes |
| 4 | Test shipped | a new `tests/test_*.py` covering the feature exists | yes |
| 5 | Dispatch | command reachable from `loop.py::_dispatch` | yes |
| 6 | Help text | listed in `commands.py::HELP_TEXT` | yes |
| 7 | Autocomplete | present in `input.py::COMMAND_TREE` | yes |
| 8 | Layering | no `print()` in the new non-REPL module(s) | yes |
| 9 | Conventions | `from __future__ import annotations`, relative intra-package imports, `Store` suffix on persistence, `__all__` re-export, PEP 604 typing | partial |

Score = passes / 9.

## Baseline

`ruff check jarvis/` reports **5 errors** on the v1 commit, all pre-existing
`F401` unused imports. Criterion 2 measures *new* errors only.

## Predicted failure

Criterion **7** is expected to fail in generation 1. It is the least discoverable
touchpoint: `COMMAND_TREE` in `jarvis/repl/input.py` is a second registry that
`_dispatch` does not share, so a command works perfectly while having no tab
completion. Commit `dd34a78` shipped `support` with exactly this defect, and
`support`, `quiz` and `files` are all still missing from it — a human author with
full repo context missed it three times.

Secondary candidates, in order of likelihood: criterion 4 (test omitted),
criterion 9 (`__all__` re-export in the touched package `__init__.py`).

## Honesty clause

If generation 1 scores 9/9, that is reported as the result. The v1 rules were
sufficient at first pass and the iteration produced no measurable gain. No
criterion is added, reweighted or reinterpreted after seeing a generation's
output — that would make the comparison meaningless.
