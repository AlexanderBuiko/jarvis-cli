# What had to be finalised after the first attempt

The teacher asks specifically for this: what changed in the profiles after the
first try. There were two rounds of change, and the first was structural.

## Iteration 1 → 2: wrong form (subagents), corrected to profiles

**First attempt.** The three profiles were built as subagents in
`.claude/agents/bug-fix.md`, `research.md`, `convention-audit.md`, each scoped by
its tool grant.

**Why it was wrong.** A subagent and a profile are different things:

- A **subagent** is a *worker*. The main agent delegates a task to it; it runs in
  its own context and reports back.
- A **profile** is a *mode the main agent itself enters*. It is not a separate
  worker — it decides which workers to use, in what order, for what purpose.

The Day-2 task asks for profiles ("System prompt / profile instructions",
"profiles for agent mode"), not more workers. Building them as subagents put the
orchestration and the work at the same level and left the global `CLAUDE.md` with
nothing to select.

**The correction**, following the tutor's guidance:

1. Global `~/.claude/CLAUDE.md` reduced to a **selector** (section 5): read the
   request, pick the profile, follow that profile file.
2. Profiles moved to `~/.claude/profiles/` as **workflows** that orchestrate the
   existing Day-1 subagents (`planner`, `executor`, `validator`, `reviewer`,
   `consolidator`).
3. The three profile-as-subagent files were deleted from `.claude/agents/`. The
   five real worker subagents stayed.
4. Project-specific commands (test runner, linter, the config-param check) moved
   into the project `CLAUDE.md`, so the global profiles stay stack-agnostic.

This came from a direct exchange with the tutor:

> — do these profiles mean files of the sub-agents, or the main CLAUDE.md?
> — Not just separate files. Make a custom profiles folder where the global
>   CLAUDE lies. Leave global CLAUDE purely as a selector for which profile to go.
> — so within the chosen profile we then have certain subagents?
> — Yes, it describes exactly which subagents will be used and for what purpose.

So the final shape is three layers: **selector → profile → subagents.**

## Iteration on the profile bodies (after the test runs)

**No profile body needed changing.** All three ran once, the selector picked the
right profile unprompted, and each returned a working result on the first launch.
Full run notes in [`results.md`](results.md).

That is the honest Day-2 outcome: the finalisation happened *before* the runs (the
subagent → profile restructure above), not after. Forcing a v2 of a profile that
already worked would be the "put everything in there" mistake the lecture warns
about.

What the runs changed was not the profiles but the **material they audit** — which
is exactly what a working profile should produce:

| Run | Real defect it surfaced | Fix |
|---|---|---|
| Bug Fix | the documented lint baseline "5 F401" is really 2× F401 + 3× E731 | corrected in `CLAUDE.md`, `validator`, both skills |
| Convention Audit | antipattern 5 wording is over-broad — a self-validating parser (`_parse_bool`, which raises) needs no validator | refined antipattern 5 in `CLAUDE.md` |
| Research | (none — clean answer, interpretation difference only) | — |

Both defects were mine, both were verified against the code before acting, and
both are the same failure mode as the rest of the week: a plausible-looking claim
in the rules that only checking against the code exposed. The profiles found them
without being asked to.
