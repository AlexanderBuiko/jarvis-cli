"""
InvariantChecker — the natural-language "requirements linter".

A first-class response validator (one of the abstractions the tutor's architecture
note calls for). It checks a reply against the configured invariants in code, and
on a violation regenerates it once to either correct accidental drift while staying
compliant OR refuse the request and explain the conflict (refuse-and-explain). Kept
distinct from the ValidatorAgent: this is a per-turn, cross-cutting filter on every
answer, whereas the ValidatorAgent validates the task *result* at the validation stage.
"""

from ..llm.gateway import LLMGateway
from ..openrouter.client import Completion
from ..prompt_builder.builder import (
    build_invariant_check_prompt,
    build_invariant_resolution_prompt,
)


class InvariantChecker:
    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def validate(
        self,
        invariants: str,
        messages: list[dict],
        response_text: str,
        completion: Completion,
        params: dict,
        api_calls: list[dict],
    ) -> tuple[str, str | None, Completion]:
        """Check the reply against the invariants; resolve once on violation.

        On a violation the reply is regenerated to correct compliant drift, or to
        refuse and explain when the request cannot be satisfied without breaking an
        invariant. Appends each LLM call to ``api_calls`` (preserving the caller's
        running index). Returns (final_text, notice_or_None, completion_for_finish_reason).
        """
        check_prompt = build_invariant_check_prompt(invariants, response_text)
        check_params = {"model": params["model"]} if "model" in params else {}
        check = self._gateway.complete(
            [{"role": "user", "content": check_prompt}], check_params,
            label="invariant_check", api_calls=api_calls,
        )

        if _invariants_ok(check.text):
            return response_text, None, completion

        resolution_prompt = build_invariant_resolution_prompt(invariants, response_text, check.text.strip())
        resolution_messages = messages + [
            {"role": "assistant", "content": response_text},
            {"role": "user", "content": resolution_prompt},
        ]
        resolution = self._gateway.complete(
            resolution_messages, params,
            label="invariant_resolution", api_calls=api_calls,
        )
        notice = (
            "[Invariant check: your request conflicted with the configured invariants — "
            "the reply above was adjusted or declined to respect them.]"
        )
        return resolution.text.strip(), notice, resolution


def _invariants_ok(verdict: str) -> bool:
    """True when the invariant checker reported no violations.

    The checker is told to answer exactly "OK" when compliant; anything else is
    treated as a violation list.
    """
    v = verdict.strip()
    if not v:
        return True
    return v.splitlines()[0].strip().upper().startswith("OK")
