# Code-assistant rules — experiment log

Week-8 task: tune the code assistant with a rules file, then prove the tuning
works by running one identical prompt under two rule versions and comparing.

## Contents

| Path | What it is |
|---|---|
| `../../CLAUDE.md` | the live project rules (currently **v1**) |
| `project-CLAUDE.v1.md` | frozen snapshot of the project rules at generation 1 |
| `global-CLAUDE.v1.md` | frozen snapshot of `~/.claude/CLAUDE.md` at generation 1 |
| `prompt.txt` | the combat prompt — reused **verbatim** for both generations |
| `rubric.md` | scoring criteria, frozen before generation 1 |
| tag `rules-v1` | the commit both generations start from |
| `gen1/`, `gen2/` | captured artifacts per generation |
| `../../scripts/capture_generation.py` | collects the artifacts and scores them |

The global rules live at `~/.claude/CLAUDE.md`, outside this repo, so they cannot
be committed directly. `global-CLAUDE.v1.md` is the mirror kept as evidence of
what the global rules were when generation 1 ran.

## Running a generation

**1. Confirm the tree is clean and at the base commit.**

```bash
git status --short              # nothing but untracked course notes
git diff --stat rules-v1        # empty for generation 1
```

**2. Open a brand-new assistant session.**

Not a session that has discussed this experiment. A session that already knows
the rubric, the codebase or the predicted failure will not reproduce a cold
first-pass result, and the comparison becomes worthless.

**3. Paste `prompt.txt` verbatim. Answer nothing.**

No clarifications, no corrections, no follow-ups — one prompt, one shot. If the
assistant asks a question, that itself is a finding worth logging.

**4. Capture, with the generated code still uncommitted.**

```bash
python scripts/capture_generation.py gen1
```

Then save the session transcript to `docs/assistant-rules/gen1/transcript.md` and
add a screenshot if you want one for the writeup.

**5. Reset to the base tree.**

The artifacts are the evidence; the generated code is not kept.

```bash
git checkout -- . && git clean -fd jarvis/ tests/
git status --short          # docs/assistant-rules/ only
```

**6. Commit the artifacts**, then move to the next rule version.

## Comparing

Generation 2 must start from the same `rules-v1` tree with only `CLAUDE.md`
changed. Rule edits come from what generation 1 *actually* got wrong — not from
hindsight about what would have scored well.

The writeup goes in `comparison.md`: the two rubric tables side by side, the two
diffs, and a ranked list of which rule additions moved the score.
