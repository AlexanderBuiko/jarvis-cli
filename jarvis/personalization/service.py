"""
PersonalizationService — owns the user profile and the behaviour-driven style
refinement loop.

Lifted out of JarvisAgent so personalisation is a self-contained concern:

  • the system-managed profile (onboarding + read access), and
  • the behaviour log plus the propose/confirm Style refinement (`personalize`),
    which learns only style/format preferences from recent activity.

It also paces the periodic, no-LLM nudge that reminds the user they can refresh
their style. All model access goes through the injected LLMGateway.
"""

from ..llm.gateway import LLMGateway
from ..prompt_builder.builder import build_profile_style_prompt, _PROFILE_NO_CHANGE
from ..session.behavior_log import BehaviorLog
from ..session.profile_store import ProfileStore

# Every N interactions, nudge the user that they can refresh their style profile.
PROFILE_NUDGE_INTERVAL: int = 5
# How many of the most recent behaviour-log notes the personaliser learns from.
PERSONALIZE_WINDOW: int = 100


class PersonalizationService:
    def __init__(
        self,
        gateway: LLMGateway,
        config,
        profile_store: ProfileStore | None = None,
        behavior_log: BehaviorLog | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config
        self._profile = profile_store or ProfileStore()
        self._behavior = behavior_log or BehaviorLog()
        # Counts interactions this session to pace the nudge (independent of the
        # on-disk log, which is capped and would plateau).
        self._interactions: int = 0

    # ── Profile access (system-managed) ────────────────────────────────────────

    def exists(self) -> bool:
        return self._profile.exists()

    def read(self) -> str | None:
        return self._profile.read()

    def read_active(self) -> str | None:
        return self._profile.read_active()

    def onboard(self, style: str, constraints: str, context: str) -> None:
        self._profile.write_sections(style, constraints, context)

    def skip_onboarding(self) -> None:
        self._profile.write_default()

    # ── Behaviour log + nudge ──────────────────────────────────────────────────

    def record_interaction(
        self,
        *,
        user_input: str,
        response_chars: int,
        solution_strategy: str,
        context_strategy: str,
        had_task: bool,
    ) -> None:
        self._behavior.record(
            user_input=user_input,
            response_chars=response_chars,
            solution_strategy=solution_strategy,
            context_strategy=context_strategy,
            had_task=had_task,
        )
        self._interactions += 1

    def maybe_nudge(self) -> str | None:
        """A one-line reminder every N interactions (no LLM call).

        Only nudges when a profile with a Style section exists, since that is the
        only thing `personalize` can refine.
        """
        if self._profile.read_style() is None:
            return None
        if self._interactions > 0 and self._interactions % PROFILE_NUDGE_INTERVAL == 0:
            return (
                "[Personalisation: enough recent activity to refresh your style profile — "
                "run 'personalize' to review a proposed update.]"
            )
        return None

    # ── Style refinement (propose + confirm) ───────────────────────────────────

    def propose_style(self) -> tuple[str | None, str | None, str | None]:
        """Propose an updated Style section from recent behaviour.

        Returns (current_style, proposed_style, error). On success error is None;
        proposed_style is None when no change is warranted. Makes one LLM call.
        """
        current = self._profile.read_style()
        if current is None:
            return None, None, (
                "No profile.md with a '## Style' section. Run 'profile onboard' first."
            )
        recent = self._behavior.recent(PERSONALIZE_WINDOW)
        if not recent:
            return current, None, "No recorded activity yet to learn from."

        prompt = build_profile_style_prompt(current, recent)
        params = {"model": self._config.runtime["model"]} if "model" in self._config.runtime else {}
        completion = self._gateway.complete([{"role": "user", "content": prompt}], params)
        proposed = completion.text.strip()
        if not proposed or proposed.upper().startswith(_PROFILE_NO_CHANGE):
            return current, None, None
        return current, proposed, None

    def apply_style(self, new_style: str) -> bool:
        return self._profile.replace_style(new_style)
