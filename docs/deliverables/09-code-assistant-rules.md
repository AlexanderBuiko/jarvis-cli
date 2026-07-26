# Week 8 — Code assistant tuning

Summary of the rules files, the experiment that tested them, and what came out.

Full detail: [`docs/assistant-rules/`](docs/assistant-rules/).
Branch: `code-assistant-rules`, 9 commits.

---

## 1. What was built

| Deliverable | Location |
|---|---|
| Global rules | `~/.claude/CLAUDE.md` (outside the repo; mirrored as `global-CLAUDE.v1/v2.md`) |
| Project rules | [`CLAUDE.md`](CLAUDE.md) — v1 → v2 → v3, each snapshotted |
| 5 good examples | in `CLAUDE.md`, all quoted from this repo with `file:line` |
| 6 antipatterns | in `CLAUDE.md`, all real defects found in this repo |
| File + package templates | in `CLAUDE.md` |
| 5 subagents | [`.claude/agents/`](.claude/agents/) |
| 2 skills | [`.claude/skills/`](.claude/skills/) |
| Measurement harness | [`scripts/capture_generation.py`](scripts/capture_generation.py) |

The two files are split by inheritance, as the lecture describes. Global holds the
operator profile, the invariants and the stage flow. Project holds only what is
specific to this repository and never contradicts the global file.

**The stage vocabulary is taken from the application itself.** `CLAUDE.md` uses
`clarification → planning → execution → validation → done`, which is the FSM in
[`jarvis/pipeline/fsm.py:16`](jarvis/pipeline/fsm.py:16). The rules and the code
being edited use one vocabulary rather than two.

The five subagents mirror the application's own pipeline roles one-to-one:

| Subagent | Mirrors | Tools |
|---|---|---|
| `planner` | `PlannerAgent` | read-only |
| `executor` | `ExecutorAgent` | read + write |
| `validator` | `ValidatorAgent` | read-only **by design** |
| `reviewer` | the swarm panel in `swarm.py` | read-only |
| `consolidator` | the swarm consolidator | read-only |

Two constraints are enforced by **tool grants**, not by instructions the model can
reinterpret. The validator cannot edit files — a validator that repairs its own
findings has a reason to under-report them. The reviewers never see each other's
output; every opinion goes only to the consolidator, which is the only role that
knows the goal.

---

## 2. The tests

One prompt, used verbatim in all three runs, each in a fresh session from the same
commit:

> Add a `notes` command to the Jarvis REPL. It should support `notes add <text>`,
> `notes list`, and `notes delete <id>`. Notes persist across sessions.

No clarifications, no corrections, no follow-ups. One prompt, one shot.

| Run | Project rules | Purpose |
|---|---|---|
| `gen0` | **none** — `CLAUDE.md` removed | ablation: what do the rules contribute? |
| `gen1` | v1 | the first real test |
| `gen2` | v2 | rerun after correcting the rules |

The **global** rules stayed active in all three. So the experiment measures what
the *project* file adds on top of them — which is the file this task asked for.

*Ablation* = remove one component, rerun the identical test, and attribute the
difference to what was removed.

Scoring used 9 pass/fail criteria, written and frozen **before** the first run so
they could not be adjusted to fit the results
([`rubric.md`](docs/assistant-rules/rubric.md)).

---

## 3. Results

| Run | Score | Compiles | Lint | Tests |
|---|---|---|---|---|
| `gen0` | 8/9 | yes | no new errors | 388 pass |
| `gen1` | 9/9 | yes | no new errors | 387 pass |
| `gen2` | 9/9 | yes | no new errors | 384 pass |

Lint baseline is 5 pre-existing errors; no run added any.

**All three runs produced working, tested, correctly registered code.** The
automated score separates them by one point.

### What actually differed

The score is a poor instrument here. The real differences are in the code:

| Convention | `gen0` no rules | `gen1` v1 | `gen2` v2 |
|---|---|---|---|
| `directory:` parameter, matching the sibling stores | ✗ | ✓ | ✓ |
| Named constant instead of a magic value | ✗ | ✓ | ✓ |
| `from __future__ import annotations` | ✗ | ✓ | ✓ |
| Class docstring | ✗ | ✓ | ✓ |
| Registration (dispatch, help text, autocomplete) | ✓ | ✓ | ✓ |
| Test shipped, no `print()` in the library module | ✓ | ✓ | ✓ |
| Module docstring naming the rejected alternative | ✓ | ✓ | ✓ |

Four conventions appear in **both** rule-runs and in **neither** ablation run.
Those are the reliable effects of the project rules.

---

## 4. What most affected the quality

1. **Naming conventions** — produced `directory:` rather than `path:`, matching
   `task_store`, `thread_store` and `invariant_store`.
2. **"Explain any constant that is not self-evident"** — magic values became named
   constants.
3. **`from __future__ import annotations`** — mechanical and reliable.
4. **Docstring rules** — a class docstring in both rule-runs, none without.

**What the rules did not need to supply.** Registration touchpoints, the
return-a-string layering rule, shipping a test, narrow exception handling, and
writing a docstring that explains *why*. The assistant produced all of these
correctly with no project rules at all, by reading the surrounding code.

This inverted the effort spent writing the rules. The registration checklists that
felt most valuable were redundant; the small typing and naming rules that read
like boilerplate did the work. The checklists were moved out of `CLAUDE.md` into a
skill, so they load only when the task matches instead of consuming context on
every turn.

---

## 5. What went wrong, and what it taught

### The prediction failed

`rubric.md` predicted the assistant would forget to register the command in
`COMMAND_TREE` (the autocomplete table). The evidence was strong: commit
`dd34a78` shipped the `support` command with exactly that defect, and `support` and
`quiz` are both still missing from it today.

**All three runs registered it correctly, including the run with no rules.** A
touchpoint a human missed twice turned out to be discoverable by reading the
adjacent code.

### Every suspected violation was a defect in the rules

Three times the generated code appeared to break a rule. Three times the codebase
showed the rule was wrong:

| Suspected miss | Actual cause |
|---|---|
| Test file lacked `from __future__ import annotations` | Only 1 of 36 test modules uses it — the rule overgeneralised |
| New store not re-exported in `session/__init__.py` | `session/` exports 2 of its 6 modules on purpose — the rule overgeneralised |
| Persisted record used a `dict`, not a `@dataclass` | Every persisted record in the codebase is a dict — the rule was ambiguous |

The third case is the most instructive. `CLAUDE.md` said "data carriers are
`@dataclass`" without saying which kind. The codebase has two kinds and they
follow opposite conventions:

- Values passed between functions are dataclasses — all 25 of them.
- Values written to a JSON file are plain dicts — `TaskStore`, `ThreadStore`,
  and `task: dict` throughout `pipeline/`.

`NoteStore` writes to `~/.jarvis/notes.json`, so a dict is correct. **`gen0` and
`gen2` matched the codebase; `gen1` — the run initially praised — is the one that
diverged.**

The ambiguity also collided with global invariant 7, *"follow the local dialect;
it beats any general best practice."* `gen1` resolved the conflict toward the
project rule, `gen0` and `gen2` toward the global one. No run disobeyed anything.
They resolved a contradiction present in the rules.

This is the failure the lecture names directly: the rule files are concatenated
into a single system prompt, so they must not contradict each other. Fixed in v3,
which states both cases explicitly.

### The measurement instrument had three defects

Found and fixed during the experiment. The score counter summed *every* check
instead of the passing ones, so it would have reported a perfect score for any
output. One criterion penalised modified files for lacking an import the rules
forbid adding to them. And the captured diff silently omitted every new file,
because `git diff` does not report untracked files.

All three fixes moved the scores **up** — against the conclusion being argued at
the time. `gen1` was re-scored with the corrected script, so all three runs were
measured by the same instrument.

---

## 6. Conclusions

**An ambiguous rule and an unreliable model produce identical evidence.** From
the outside, "the assistant ignores this rule half the time" looks exactly like
"this rule contradicts another rule". Only reading the codebase separates them.

**Check the rule against the code before blaming the output.** Three suspected
violations, three defective rules, no model errors.

**Rules earn their place by what the assistant would not work out alone.**
Registration steps were discoverable by imitation and belong in a skill. Typing
and naming conventions were not discoverable — `session/` contains both styles, so
the codebase gives no signal — and belong in the always-loaded file.

**This rubric measures wiring, not design.** All three runs scored 8–9/9 while
differing on data modelling, parameter naming and constant extraction. The manual
review found everything that mattered.

### Limits of these results

- **Task selection bias.** `notes` is structurally a sibling of the `support`
  command, whose recipe was studied in detail while writing the rules. The rules
  covered exactly the ground this task needed. A task in unstudied territory — a
  new MCP server, a third LLM provider — would be a stronger test and has not been
  run.
- **One run per condition.** This already caused one wrong conclusion. Treat any
  single-run difference as unproven unless it appeared in both rule-runs.
- **The subagents and skills are written but not yet exercised.** They parse
  correctly; none has been run. No claim is made about how well they work.
