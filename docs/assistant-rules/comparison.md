# What the project rules actually changed

Three runs of one prompt, verbatim, each in a fresh session from the same tree.

| Run | Rules active | Automated score |
|---|---|---|
| `gen0` | global only (project `CLAUDE.md` removed) | 8/9 |
| `gen1` | global + project v1 | 9/9 |
| `gen2` | not run — see "Why there is no gen2" | — |

The automated rubric separates the runs by a single criterion. It is the wrong
instrument for this question, and the interesting result is entirely in the code.

## The automated delta is nearly flat

Both runs passed criteria 1–8: imports clean, no new lint errors, tests green, a
test file shipped, dispatch wired, help text written, `COMMAND_TREE` registered,
no `print()` in the library module. Only `from __future__ import annotations`
separated them.

**The prediction failed twice.** `COMMAND_TREE` was called the near-certain miss
in `rubric.md`, on the evidence that commit `dd34a78` shipped `support` with
exactly that defect and that `support`, `quiz` and `files` are still absent from
it. It was registered correctly by gen1 *and* by gen0 — with no project rules at
all. The touchpoint a human missed three times is, in fact, discoverable by
reading the surrounding code.

## The qualitative delta is large

| Aspect | `gen0` — no project rules | `gen1` — v1 rules |
|---|---|---|
| **Data carrier** | raw `dict` throughout; `note["text"]`, `note.get("created_at")` | `@dataclass Note` with a trailing `#` comment documenting the field |
| **Constructor param** | `path: Path \| None = None` | `directory: Path \| None = None` — identical to `task_store`, `thread_store`, `invariant_store` |
| **Constants** | inline `"notes.json"`, bare `[:8]` | `_FILENAME`, `_ID_LENGTH`, the latter with a comment explaining the width |
| **Class docstring** | none | one-line summary naming the storage location |
| **`__future__` import** | absent | present |
| Module docstring | explains single-file vs file-per-note | explains single-file vs `TaskStore`'s file-per-record |
| Layering, tests, dispatch, help, autocomplete, section separators, narrow `except` tuples | correct | correct |

The dict-vs-dataclass split is the substantive one. It propagates: gen0's store
returns `dict` from `add`, `list_all`, `find` and `delete`, so every caller
indexes by string key and the type checker has nothing to hold. `CLAUDE.md`'s
"data carriers are `@dataclass`, or `NamedTuple` when immutable" is what bought
that, and no amount of reading neighbouring files would have supplied it —
`session/` contains both styles.

One mild over-imitation in gen0: `sep = "─" * 60` in the list renderer, borrowed
from the `/help` and `/support` clients where it separates a remote answer. Local
command output in this codebase does not use it. Given no rules, the model picked
a plausible sibling and copied the wrong one.

## What most affected the quality

Ranked by observed effect, not by how much was written about them.

1. **Data-carrier rule** (`@dataclass` over `dict`) — the only difference that
   changes the shape of the API and every call site.
2. **Naming conventions table** — produced `directory:` over `path:`, matching
   the three sibling stores.
3. **"Explain any constant that is not self-evident"** — turned two magic values
   into named, documented constants.
4. **`from __future__ import annotations`** — mechanical, and the only one the
   automated rubric caught.
5. **Docstring rules** — small delta; the codebase already teaches this well by
   example.

What the project rules did **not** need to supply, because the codebase or the
global rules already carried it: registration touchpoints (dispatch, help text,
`COMMAND_TREE`), the return-a-string layering discipline, shipping a test,
narrow exception tuples degrading to a neutral value, section separators, and
the "docstring explains why, not what" habit.

That is the useful lesson, and it inverts the effort spent writing the rules: the
registration checklists that seemed most valuable were redundant, and the
type-discipline rules that read as boilerplate did the real work.

## Why there is no gen2

gen1 scored 9/9 with no genuine convention violation on manual review
(`gen1/findings.md`). With nothing to fix, a rerun under corrected rules could
not produce a measurable difference, and adding rules to manufacture one is the
"put everything in there" failure the source lecture warns against. v2 exists and
is two corrections with zero additions — both of them cases where v1 asserted a
convention the codebase does not actually hold:

- `from __future__ import annotations` scoped to `jarvis/` and away from tests
  (1 of 37 test modules uses it).
- `__init__.py` re-export downgraded from universal to per-package (`session/`
  exports 2 of 7 modules; `pipeline/` has no `__all__` at all).

Both corrections came from gen1 being *right* where the rules were wrong.

## Threats to validity

- **Task selection bias.** `notes` is structurally a sibling of the `support`
  command, whose recipe was traced in detail while writing the rules. The rules
  documented the conventions this task needed. A task in less-studied territory
  (a new MCP server, a third LLM provider) would likely widen the gen0/gen1 gap.
- **n = 1 per condition.** Both runs are single samples of a stochastic process.
  The dict-vs-dataclass difference is large and structural enough to be unlikely
  as noise; the docstring differences are not.
- **The global rules were active in both runs**, so everything above measures the
  *project* file's marginal contribution only — which is the right unit for this
  task, but means the total contribution of rules is understated.
- **The instrument had three defects**, all found after gen1 ran and all fixed
  before gen0 (`gen1/findings.md`). gen1's captured score was re-derived with the
  corrected script, so both runs were scored by the same instrument.
