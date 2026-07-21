# Generation 1 — findings

**Score: 9/9.** One prompt, no clarifications, under `CLAUDE.md` v1
(commit tagged `rules-v1`).

Files produced: `jarvis/session/notes_store.py` (new), `tests/test_notes_store.py`
(new), and edits to `commands.py`, `input.py`, `loop.py`.

## The score moved after the run — because the instrument was wrong

The raw capture reported 8/9. Three defects in `scripts/capture_generation.py`
were found and fixed; none of them were changes to the *criteria*.

| Defect | Effect |
|---|---|
| Criterion 9 tested new **and modified** files | Flagged the 3 pre-existing REPL modules for lacking `from __future__ import annotations` — which the rules explicitly forbid retrofitting. Inverted the rule it was meant to enforce. |
| `changes.diff` built from `git diff` alone | Untracked files are invisible to `git diff`, so the two *new* modules — the substance of the work — were absent from the evidence entirely. |
| New files copied into the artifact tree | pytest collected the copied `test_*.py` a second time, corrupting the test count on every later run. Now inlined into `new_files.md`. |

Fixing a broken measurement is not the same as reinterpreting a criterion. The
distinction that matters: every one of these fixes moved the score **up**, i.e.
against the hypothesis being argued. The rubric's honesty clause was also
breached once during this pass — a criterion 10 was added, reverse-engineered
from what generation 1 happened to do — and reverted before scoring.

## Manual review — no genuine convention violation

The automated criteria are shallow. Every suspected miss was checked against the
codebase, and each turned out to be the rules being wrong, not the code.

| Suspected miss | Verdict |
|---|---|
| Test file lacks `from __future__ import annotations` | **Rule wrong.** 1 of 37 existing test modules uses it. Generation followed local dialect. |
| `NotesStore` not re-exported in `session/__init__.py` | **Rule wrong.** `session/` holds 7 modules and exports 2; `pipeline/` has no `__all__` at all. Adding one would have been the defect. |
| Command handlers lack docstrings | **Matches dialect.** 9 of 38 existing handlers have them. |
| `_write` is not atomic (no temp+rename) | **Matches dialect.** All 7 existing stores use a plain `write_text`. |
| `__init__(self, directory: Path \| None = None) -> None` | Byte-identical to `task_store`, `thread_store`, `invariant_store`. |

Conventions the generation picked up unprompted, none of which the prompt
mentioned: module docstring naming the rejected alternative (single JSON file
vs. `TaskStore`'s file-per-record) — the hardest part of the house style to
imitate; narrow exception tuple `(json.JSONDecodeError, OSError)` degrading to a
neutral `[]`; trailing `#` comment documenting a dataclass field; `# ── Internal ──`
section separator; private helper placed last; `Store` suffix; PEP 604 typing
throughout; handlers returning strings with no `print()` in the library module.

## The prediction failed

`rubric.md` predicted criterion 7 (`COMMAND_TREE` autocomplete) would fail. It
passed — registered correctly and aligned with the surrounding dict. The
reasoning behind the prediction was that commit `dd34a78` shipped `support` with
exactly this defect and that `support`, `quiz` and `files` are still missing from
it. A human author with full repo context missed it three times; the assistant,
given the rules, did not.

## Caveat that limits what this proves

**The task was chosen adjacent to code already studied when the rules were
written.** `notes` is structurally a sibling of the `support` command, whose
registration recipe was traced in detail during the analysis that produced
`CLAUDE.md`. The rules therefore documented precisely the conventions this task
required. This is a ceiling effect by construction, and 9/9 should be read as
"the rules cover the ground they were written from", not "the rules generalise".

## Consequence for v2

Nothing in the generated code needs fixing, so re-running the identical prompt
under a corrected v1 cannot produce a measurable difference. v2 is therefore
**two corrections and zero additions** — the `__future__` rule scoped to
`jarvis/` and away from tests, and the `__init__.py` re-export rule downgraded
from universal to per-package. Adding rules to manufacture a delta is the
"put everything in there" failure the source lecture warns against.

The question the same-prompt rerun can no longer answer — *what did the rules
actually contribute?* — is answered instead by ablation: run the identical
prompt with the project rules removed. See `../README.md`.
