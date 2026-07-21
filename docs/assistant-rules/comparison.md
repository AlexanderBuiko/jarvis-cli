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
with exactly that defect and that `support` and `quiz` are both still
absent from it. Every run registered it correctly — including `gen0`, with no
project rules at all. A touchpoint a human missed twice is, in fact,
discoverable by reading the surrounding code.

## Where the runs actually differ

| Convention | `gen0` no rules | `gen1` v1 | `gen2` v2 | Reliable? |
|---|---|---|---|---|
| `@dataclass` for a *persisted* record | ✗ | ✓ | ✗ | **Not a defect — see the correction below; gen1 is the outlier** |
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
5. **Data-carrier rule (`@dataclass`)** — **withdrawn as a finding.** It looked
   like the highest-impact and least reliable rule. It was neither: it was
   ambiguous, it contradicted global invariant 7, and the run that "obeyed" it is
   the run that diverged from the codebase. Fixed in v3.

What the project rules did **not** need to supply, because the codebase or the
global rules already carried it: registration touchpoints (dispatch, help text,
`COMMAND_TREE`), return-a-string layering, shipping a test, narrow exception
tuples degrading to a neutral value, section separators, and the "docstring
explains why" habit — `gen0` wrote a genuinely good module docstring with no
project rules at all.

## The lesson

**An ambiguous rule looks exactly like an unreliable model.** The dataclass
finding survived two rewrites of this document before an audit of the codebase
showed the rule itself was the defect. From the outside, "the model ignores this
rule half the time" and "the rule contradicts another rule" produce identical
evidence. Only reading the codebase separates them.

Three practical consequences:

- **Check the rule against the code before blaming the output.** Every single
  suspected violation across three runs — the test-file `__future__` import, the
  missing `__all__` re-export, the dataclass — turned out to be the rule
  overstating a convention the codebase does not hold. Three for three.
- **Rules must be specific enough not to collide.** "Data carriers are
  `@dataclass`" reads as precise but does not say *which* carriers, so it
  silently contradicted "follow the local dialect". Both were mine.
- **This rubric measures wiring, not design.** All three runs scored 8–9/9 while
  differing on data modelling, parameter naming and constant extraction. A score
  that cannot distinguish them is not measuring quality, and the manual review
  did the real work throughout.

## Why the registration recipes became skills, not rules

`CLAUDE.md` is loaded on every turn; a skill loads only when its description
matches the task. The ablation showed the registration steps were discoverable
without rules, so keeping the six-step recipe in the always-loaded file bought
nothing and cost context on every unrelated turn. It now lives in
`.claude/skills/add-repl-command/`.

Honest caveat: since all three runs registered correctly without it, the skill's
value is **unproven**. The argument for keeping it is that it costs nothing when
not loaded, and that this repository's own history contains two commits that
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
