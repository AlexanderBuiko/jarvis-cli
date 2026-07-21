# What the project rules actually changed

Three runs of one prompt, verbatim, each in a fresh session from the same tree.
The global rules (`~/.claude/CLAUDE.md`) were active in all three, so everything
below measures the marginal contribution of the **project** file only.

| Run | Project rules | Automated score |
|---|---|---|
| `gen0` | none — `CLAUDE.md` removed (the ablation) | 8/9 |
| `gen1` | v1 | 9/9 |
| `gen2` | v2 | 9/9 |

**Ablation** = remove one component, rerun the identical test, and attribute the
difference to what you removed.

## The automated rubric is nearly blind here

Across three runs the 9 criteria separate them by a single point, and that point
is the mechanical `from __future__ import annotations` check. Every run compiled,
kept the lint baseline at 5, shipped tests, and registered the command in the
dispatch chain, the help text and `COMMAND_TREE`.

**The `COMMAND_TREE` prediction failed in all three runs.** `rubric.md` called it
the near-certain miss, on the evidence that commit `dd34a78` shipped `support`
with exactly that defect and that `support`, `quiz` and `files` are all still
absent from it. Every run registered it correctly — including `gen0`, with no
project rules at all. A touchpoint a human missed three times is, in fact,
discoverable by reading the surrounding code.

## Where the runs actually differ

| Convention | `gen0` no rules | `gen1` v1 | `gen2` v2 | Reliable? |
|---|---|---|---|---|
| `@dataclass` over raw `dict` | ✗ | ✓ | **✗** | **No — 1 of 2 rule-runs** |
| `from __future__ import annotations` | ✗ | ✓ | ✓ | Yes |
| `_FILENAME` named constant | ✗ | ✓ | ✓ | Yes |
| `directory:` param, matching the sibling stores | ✗ | ✓ | ✓ | Yes |
| Class docstring | ✗ | ✓ | ✓ | Yes |
| Module docstring naming the rejected alternative | ✓ | ✓ | ✓ | No signal — all three |
| Layering, tests, dispatch, help, autocomplete, `except` tuples | ✓ | ✓ | ✓ | No signal — all three |

## Second correction: gen2 was right and the rule was wrong

The section below was itself written on a wrong premise. It treats gen2's use of
raw dicts as non-compliance. A later audit of all 25 dataclasses in the codebase
shows the opposite.

The dataclasses split cleanly by persistence. Every one of them is an *in-memory*
carrier — `StageVerdict`, `StageResult`, `EvalReport`, `Completion`, `Chunk`,
`ReviewOpinion`. Every *persisted* record is a plain dict: `TaskStore.load() ->
dict | None`, `ThreadStore.list_all() -> list[dict]`, `task: dict` throughout
`pipeline/`. No dataclass in `session/` survives a restart.

`NoteStore` persists to `~/.jarvis/notes.json`. **gen0 and gen2 matched the local
dialect; gen1 is the run that diverged from it.**

The v1/v2 rule said only "data carriers are `@dataclass`" without distinguishing
the two cases, and it contradicted global invariant 7 ("follow the local dialect;
the conventions of the file you are editing beat any general best practice").
gen1 resolved that contradiction toward the project rule, gen0 and gen2 toward
the global one. No run disobeyed. The rules disagreed with each other.

This is the failure the source lecture names directly: the rule files are
concatenated into one system prompt, so they must not contradict. The apparent
"unreliable rule" was an authoring defect presenting as model non-determinism.

Corrected in v3 (`project-CLAUDE.v3.md`): persisted records are dicts, in-memory
carriers are dataclasses, stated explicitly.

## A correction to the earlier conclusion

After `gen0` this document claimed the dataclass difference was "the substantive
one" and identified it as the single biggest thing the rules bought.

**`gen2` falsifies that.** The data-carrier rule is *identical* in v1 and v2 — it
was never edited. `gen2` had it in context and used raw dicts anyway, exactly as
the no-rules run did. Two of three runs produced dicts, one of them while being
explicitly told not to.

So the `gen0`/`gen1` gap on that dimension was at least partly chance. The
threat to validity recorded in the previous version of this file — *n = 1 per
condition* — materialised, and it struck the finding that was leading the
document. The third run was worth doing precisely because it was expected to be a
no-op.

## What most affected the quality

Ranked by **reliability across runs**, which is a stronger basis than a single
comparison.

1. **Naming conventions table** — `directory:` over `path:`, matching
   `task_store`, `thread_store`, `invariant_store`. Delivered in both rule-runs.
2. **"Explain any constant that is not self-evident"** — magic values became named
   constants in both rule-runs.
3. **`from __future__ import annotations`** — mechanical, reliable, and the only
   one the rubric detects.
4. **Docstring rules** — a class docstring appeared in both rule-runs and in
   neither ablation run.
5. **Data-carrier rule (`@dataclass`)** — **obeyed half the time.** Highest impact
   when followed, lowest reliability of anything measured.

What the project rules did **not** need to supply, because the codebase or the
global rules already carried it: registration touchpoints (dispatch, help text,
`COMMAND_TREE`), return-a-string layering, shipping a test, narrow exception
tuples degrading to a neutral value, section separators, and the "docstring
explains why" habit — `gen0` wrote a genuinely good module docstring with no
project rules at all.

## The lesson

**Writing a rule does not make it stick.** `gen2` scored a perfect 9/9 while
violating the convention this document had called the most important one. The two
facts are compatible because the rubric tests registration and mechanics, not data
modelling — the automated score was blind to the regression.

Two practical consequences:

- Short, mechanical rules (add this import, name this constant) are followed
  reliably. Rules requiring a modelling *decision* (use a dataclass, not a dict)
  are followed inconsistently, and need either repetition, a worked example at the
  point of use, or enforcement outside the prompt.
- A rubric that a change can pass while regressing is an incomplete rubric. This
  one measures whether the feature is wired up, not whether it is well built.

## Why the registration recipes became skills, not rules

`CLAUDE.md` is loaded on every turn; a skill loads only when its description
matches the task. The ablation showed the registration steps were discoverable
without rules, so keeping the six-step recipe in the always-loaded file bought
nothing and cost context on every unrelated turn. It now lives in
`.claude/skills/add-repl-command/`.

Honest caveat: since all three runs registered correctly without it, the skill's
value is **unproven**. The argument for keeping it is that it costs nothing when
not loaded, and that this repository's own history contains three commits that
made exactly that mistake.

## Threats to validity

- **n = 1 per condition, and it already bit.** One threat in this list has
  already turned into a wrong conclusion. Treat every single-run difference below
  the level of "appeared in both rule-runs" as unproven.
- **Task selection bias.** `notes` is structurally a sibling of the `support`
  command, whose recipe was traced in detail while writing the rules. The rules
  documented the conventions this task needed. Unstudied territory — a new MCP
  server, a third LLM provider — would likely widen the gap.
- **Global rules active throughout**, so the total contribution of rules is
  understated; only the project file's marginal effect is measured.
- **The instrument had three defects**, all found after `gen1` and fixed before
  `gen0` and `gen2`. `gen1` was re-scored with the corrected script, so all three
  runs were measured by the same instrument.
- **The rubric cannot see data modelling.** The one regression found in `gen2` was
  invisible to it and surfaced only on manual review.
