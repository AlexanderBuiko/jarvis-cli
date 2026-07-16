"""
LLMGateway — the single chokepoint for every LLM call in the application.

The KB's architecture note calls for one component through which all model access
flows, so cross-cutting concerns (accounting, and later retries / rate-limiting /
caching) live in exactly one place instead of being scattered across the agent,
the invariant checker and the stage agents. Every caller depends on this gateway,
never on a concrete engine.

It wraps an LLMEngine implementation and, on each call, optionally builds the
accounting record via make_call_record and appends it to a running ``api_calls``
list so the caller's billing stays correct. Background/admin calls that are billed
out of band can use ``record()`` to mint a record with an explicit index.
"""

import json
import logging
from typing import Any

from .accounting import make_call_record
from .engine import LLMEngine
from ..openrouter.client import Completion

# Per-call tool trace (selected tool, target server, call order, result). Surfaced
# at INFO so a demo/E2E run can show cross-server routing; quiet by default.
tool_logger = logging.getLogger("jarvis.tools")

# Safety cap on tool-call rounds in a single turn, so a model that keeps calling
# tools can't loop forever. Sized for long cross-server flows (the multi-server
# demo chains ~8 dependent calls across 3 servers, one per round).
MAX_TOOL_ROUNDS = 12

# How much of a tool result to show in the trace line (full result still goes to
# the model). Keeps the trace readable when a tool returns a large JSON blob.
_TRACE_PREVIEW_CHARS = 200
# Per-argument value length in the trace, so a relayed report/blob doesn't bloat it.
_TRACE_ARG_CHARS = 40


def _compact_args(args: dict) -> str:
    """Render call args as ``k=v, …`` with each value truncated, for the trace."""
    parts = []
    for key, value in (args or {}).items():
        text = " ".join(str(value).split())
        if len(text) > _TRACE_ARG_CHARS:
            text = text[:_TRACE_ARG_CHARS] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts)


class LLMGateway:
    """The one place the rest of the system calls the model through."""

    def __init__(
        self,
        engine: LLMEngine,
        tool_provider: Any | None = None,
        tool_gate: Any | None = None,
    ) -> None:
        self._engine = engine
        # Optional MCPToolProvider. Only calls that pass use_tools=True see tools,
        # so background/utility calls (memory, invariants, personalisation) never
        # get them. None → tool support is simply off.
        self._tool_provider = tool_provider
        # Optional ToolPermissions gate (CLI side). Consulted before a mutating tool
        # (e.g. files.write_file) runs; None → no gating (server-side gateways).
        self._tool_gate = tool_gate

    def complete(
        self,
        messages: list[dict],
        params: dict[str, Any],
        *,
        label: str | None = None,
        api_calls: list[dict] | None = None,
        use_tools: bool = False,
    ) -> Completion:
        """Run a completion. When ``api_calls`` is given, append an accounting
        record (indexed sequentially) labelled ``label``.

        When ``use_tools`` is set and a tool provider is attached, the model is
        offered the MCP tool catalogue and any tool calls it makes are executed
        and fed back, looping until it returns a final answer (or the round cap).
        Every model call in the loop is billed via ``api_calls``.
        """
        tool_specs = (
            self._tool_provider.tool_specs()
            if (use_tools and self._tool_provider is not None)
            else None
        )
        if not tool_specs:
            completion = self._engine.complete(messages, params)
            self._maybe_record(api_calls, label, completion)
            return completion
        return self._complete_with_tools(messages, params, tool_specs, label, api_calls)

    def _complete_with_tools(
        self,
        messages: list[dict],
        params: dict[str, Any],
        tool_specs: list[dict],
        label: str | None,
        api_calls: list[dict] | None,
    ) -> Completion:
        # Append the tool exchange to the caller's own ``messages`` list so that
        # downstream consumers (notably the invariant checker) can see that facts
        # were tool-sourced. Each engine call is given a *snapshot* (list(messages))
        # so the recorded request payload is frozen at that moment rather than
        # mutating as later rounds append to the shared list.
        call_params = {**params, "tools": tool_specs}
        completion: Completion | None = None
        call_index = 0  # running order across rounds, for the trace
        for _ in range(MAX_TOOL_ROUNDS):
            completion = self._engine.complete(list(messages), call_params)
            self._maybe_record(api_calls, label or "completion", completion)
            if not completion.tool_calls:
                return completion
            # Surface the model's own "what I'm about to do" narration (the text it
            # emits alongside a tool call) as a live note, so the chat reads like
            # "let me read gateway.py" → the tool call. Prefixed SAY: for the REPL styler.
            if completion.text and completion.text.strip():
                tool_logger.info("SAY: %s", " ".join(completion.text.split()))
            # Echo the assistant's tool-call message, then append each tool result.
            messages.append({
                "role": "assistant",
                "content": completion.text or None,
                "tool_calls": completion.tool_calls,
            })
            for call in completion.tool_calls:
                call_index += 1
                messages.append(self._run_tool_call(call, call_index))
        # Round cap hit: return the last completion as-is.
        return completion  # type: ignore[return-value]

    def _run_tool_call(self, call: dict, order: int = 0) -> dict:
        """Execute one tool call via the provider; return its 'tool' result message.

        Emits a trace line — order index, target server, tool, and a result preview
        — so a multi-server run shows which server each call was routed to.
        """
        fn = call.get("function", {})
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        server = self._server_for(name)
        bare = name.split("__", 1)[-1]  # drop the wire-name server prefix for display
        # Permission gate: a mutating tool (e.g. files.write_file) may need the user's
        # OK before it runs. When it isn't pre-authorised the gate queues it for approval
        # after the turn — not an error, so tell the model it's pending and to move on
        # (don't repeat the call) rather than crash or loop.
        if self._tool_gate is not None and not self._tool_gate.allow(name, args):
            target = (args or {}).get("path", "the file")
            tool_logger.info("[%d] %s.%s(%s) → queued for approval",
                             order, server, bare, _compact_args(args))
            return {"role": "tool", "tool_call_id": call.get("id", ""),
                    "content": (f"The change to '{target}' was captured and is awaiting the "
                                f"user's approval after this turn. Do not repeat the call; "
                                f"continue or summarise what you've prepared.")}
        try:
            content = self._tool_provider.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001 — report back to the model, don't crash the turn
            content = f"Tool '{name}' failed: {exc}"
        # A dry-run diff preview: show it to the user in a read-only frame (captured on
        # the gate) and hand the model only a short summary, so it doesn't re-dump the
        # whole file as prose. The user sees the diff framed, not duplicated.
        if (self._tool_gate is not None and hasattr(self._tool_gate, "add_preview")
                and bare in ("write_file", "delete_file") and (args or {}).get("dry_run")
                and isinstance(content, str) and content.startswith("[dry run")):
            path = (args or {}).get("path", "the file")
            self._tool_gate.add_preview(path, content)
            content = f"[dry-run preview of '{path}' shown to the user in a frame; not written]"
        preview = " ".join(str(content).split())[:_TRACE_PREVIEW_CHARS]
        tool_logger.info("[%d] %s.%s(%s) → %s",
                         order, server, bare, _compact_args(args), preview)
        return {"role": "tool", "tool_call_id": call.get("id", ""), "content": content}

    def _server_for(self, name: str) -> str:
        """Best-effort owning-server name for the trace (provider may not expose it)."""
        resolver = getattr(self._tool_provider, "server_for", None)
        if callable(resolver):
            try:
                return resolver(name)
            except Exception:  # noqa: BLE001 — tracing must never break a tool call
                pass
        return "?"

    def _maybe_record(self, api_calls: list[dict] | None, label: str | None, completion: Completion) -> None:
        if api_calls is not None:
            api_calls.append(
                make_call_record(len(api_calls) + 1, label or "completion", completion, self._engine)
            )

    def record(self, index: int, label: str, completion: Completion) -> dict:
        """Mint an accounting record for a completion the caller bills separately."""
        return make_call_record(index, label, completion, self._engine)

    # ── Metadata pass-through (the gateway is the engine the app sees) ──────────

    def get_pricing(self, model_id: str) -> tuple[float | None, float | None]:
        return self._engine.get_pricing(model_id)

    def get_context_window(self, model_id: str) -> int | None:
        return self._engine.get_context_window(model_id)
