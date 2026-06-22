"""
bridge — translate aggregated MCP tools into the function-calling schema the
existing LLM stack already speaks.

This is the seam between the MCP layer and the rest of Jarvis. The stage agents
were designed to take tools "later" (see pipeline/base.py); when that day comes,
the orchestrator asks the registry for its catalogue, runs it through
:func:`tools_to_openrouter`, and passes the result as the ``tools`` parameter of
an LLM call via the existing :class:`jarvis.llm.gateway.LLMGateway`. When the model
returns a tool call, the dispatcher routes it back through
``MCPRegistry.call_tool`` by the qualified name.

Keeping this conversion in one tiny module means the registry stays
provider-agnostic and the agent stays MCP-agnostic — neither depends on the other.
"""

from __future__ import annotations

from typing import Any

from .registry import NAMESPACE_SEP, AggregatedTool

# Function-calling APIs (OpenAI/Anthropic) require tool names to match
# ^[a-zA-Z0-9_-]{1,64}$ — the dot in our qualified names (``server.tool``) is
# rejected with a 400. On the wire we therefore use ``__`` as the separator;
# the provider reverses it before routing back to the registry.
WIRE_SEP = "__"


def to_wire_name(qualified_name: str) -> str:
    """``weather.get_weather`` → ``weather__get_weather`` (API-legal name)."""
    return qualified_name.replace(NAMESPACE_SEP, WIRE_SEP)


def tool_to_openrouter(tool: AggregatedTool) -> dict[str, Any]:
    """Convert one AggregatedTool to an OpenRouter/OpenAI function-tool spec.

    The wire-safe qualified name becomes the function name; the provider maps it
    back to the dotted name and routes through ``MCPRegistry.call_tool``.
    """
    return {
        "type": "function",
        "function": {
            "name": to_wire_name(tool.qualified_name),
            "description": tool.description,
            "parameters": tool.input_schema or {"type": "object", "properties": {}},
        },
    }


def tools_to_openrouter(tools: list[AggregatedTool]) -> list[dict[str, Any]]:
    """Convert a whole aggregated catalogue to the function-calling ``tools`` list."""
    return [tool_to_openrouter(t) for t in tools]
