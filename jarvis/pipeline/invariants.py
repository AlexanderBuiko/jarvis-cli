"""
InvariantChecker — the natural-language "requirements linter".

A first-class response validator (one of the abstractions the tutor's architecture
note calls for). It checks a reply against the configured invariants in code, and
reworks it once on a violation. Kept distinct from the ValidatorAgent: this is a
per-turn, cross-cutting filter on every answer, whereas the ValidatorAgent validates
the task *result* at the validation stage.
"""

from ..llm.accounting import make_call_record
from ..llm.engine import LLMEngine
from ..openrouter.client import Completion
from ..prompt_builder.builder import (
    build_invariant_check_prompt,
    build_invariant_rework_prompt,
)


class InvariantChecker:
    def __init__(self, engine: LLMEngine) -> None:
        self._engine = engine

    def validate(
        self,
        invariants: str,
        messages: list[dict],
        response_text: str,
        completion: Completion,
        params: dict,
        api_calls: list[dict],
    ) -> tuple[str, str | None, Completion]:
        """Check the reply against the invariants; rework once on violation.

        Appends each LLM call it makes to ``api_calls`` (preserving the caller's
        running index). Returns (final_text, notice_or_None, completion_for_finish_reason).
        """
        check_prompt = build_invariant_check_prompt(invariants, response_text)
        check_params = {"model": params["model"]} if "model" in params else {}
        check = self._engine.complete([{"role": "user", "content": check_prompt}], check_params)
        api_calls.append(make_call_record(len(api_calls) + 1, "invariant_check", check, self._engine))

        if _invariants_ok(check.text):
            return response_text, None, completion

        rework_prompt = build_invariant_rework_prompt(invariants, response_text, check.text.strip())
        rework_messages = messages + [
            {"role": "assistant", "content": response_text},
            {"role": "user", "content": rework_prompt},
        ]
        rework = self._engine.complete(rework_messages, params)
        api_calls.append(make_call_record(len(api_calls) + 1, "invariant_rework", rework, self._engine))
        notice = "[Invariant check: reply revised to satisfy the configured invariants.]"
        return rework.text.strip(), notice, rework


def _invariants_ok(verdict: str) -> bool:
    """True when the invariant checker reported no violations.

    The checker is told to answer exactly "OK" when compliant; anything else is
    treated as a violation list.
    """
    v = verdict.strip()
    if not v:
        return True
    return v.splitlines()[0].strip().upper().startswith("OK")
