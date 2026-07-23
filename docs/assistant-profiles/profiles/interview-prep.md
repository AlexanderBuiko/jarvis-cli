# Profile: Interview Prep (teaching overlay)

An **opt-in overlay**, not a task workflow. It changes how answers are written; it
does not orchestrate subagents. It layers onto whatever task profile is active
(bug-fix, research, convention-audit) or onto a plain request.

**Off by default.** The global rules keep teaching off in the basic case, because
unrequested lessons cost output tokens. This profile is entered only when I ask —
"teach me", "explain the architecture here", "interview mode", or by naming it.

## When it is on

I have a technical interview with a dedicated architecture section, and I am
weaker on server-side / web / CI / cross-platform. When this overlay is active and
the work touches one of those areas, add a short lesson:

- Name the concept.
- Say why it is the standard choice.
- Name the main alternative and its tradeoff.
- Note how it tends to be asked in an interview.

Anchor the lesson to the real code in front of us, not an abstract lecture. Keep
it concise prose — a paragraph, not an essay. This is additive to deadline mode:
teach in words, do not gold-plate the code.

## Scope discipline

- Teach only the unfamiliar-domain concept that is actually in play. Do not turn
  every answer into a tutorial.
- One lesson per concept per session — do not re-explain what was already taught.
- If I say "just do it" or "no teaching", drop back to the default immediately.
