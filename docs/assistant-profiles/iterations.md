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

To be filled in once each profile is exercised on its task. Record here, per
profile: what the first run got wrong, and the single change to the profile file
that fixed it. Success target is one run, working result — the same standard as
Day 1.
