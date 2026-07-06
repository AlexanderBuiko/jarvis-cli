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
    def __init__(self, gateway: LLMGateway, resolve_gateway: LLMGateway | None = None) -> None:
        # The compliance CHECK runs on ``gateway`` (may be a cheap/local utility
        # engine). The RESOLUTION rewrites the user-facing answer, so it runs on
        # ``resolve_gateway`` — the main engine — for answer quality. Defaults to
        # the same gateway when not split.
        self._gateway = gateway
        self._resolve_gateway = resolve_gateway or gateway

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
        tool_context = _tool_context(messages)
        check_prompt = build_invariant_check_prompt(invariants, response_text, tool_context)
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
        resolution = self._resolve_gateway.complete(
            resolution_messages, params,
            label="invariant_resolution", api_calls=api_calls,
        )
        final_text, notice = _interpret_resolution(resolution.text)
        return final_text, notice, resolution


def _interpret_resolution(text: str) -> tuple[str, str]:
    """Split the resolution's CORRECTED:/REFUSED: tag from the reply and pick a notice.

    A *correction* (the reply slipped and was rewritten) is a routine adjustment —
    the shown reply already complies, so the note is calm and doesn't imply the
    user's request was at fault. A *refusal* (the request truly conflicts) keeps the
    stronger notice that names the conflict. Returns (reply_text, notice).
    """
    stripped = text.strip()
    head, _, rest = stripped.partition("\n")
    tag = head.strip().upper().rstrip(":")
    body = rest.strip() or stripped

    if tag == "CORRECTED":
        return body, "[Note: the reply was adjusted to stay within your configured invariants.]"
    if tag == "REFUSED":
        return body, (
            "[Invariant check: this request conflicts with your configured invariants — "
            "the reply above declined it and offered an alternative.]"
        )
    # No recognisable tag: fall back to the neutral combined notice on the full text.
    return stripped, (
        "[Invariant check: the reply was adjusted or declined to respect your configured invariants.]"
    )


def _tool_context(messages: list[dict]) -> str:
    """Summarise this turn's tool calls and their results for the checker.

    Reads the tool exchange the gateway appended to ``messages`` (assistant
    messages carrying ``tool_calls`` and the ``tool`` result messages). Returns an
    empty string when no tools were used, so non-tool turns are unaffected.
    """
    lines: list[str] = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", "")
                lines.append(f"- called {fn.get('name', '?')}({args})")
        elif m.get("role") == "tool":
            content = (m.get("content") or "").strip()
            lines.append(f"  → returned: {content}")
    return "\n".join(lines)


def _invariants_ok(verdict: str) -> bool:
    """True when the invariant checker reported no violations.

    The checker is told to answer exactly "OK" when compliant; anything else is
    treated as a violation list.
    """
    v = verdict.strip()
    if not v:
        return True
    return v.splitlines()[0].strip().upper().startswith("OK")
