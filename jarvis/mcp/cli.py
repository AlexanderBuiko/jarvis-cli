"""
A tiny CLI front-end for the MCP layer — the Phase 2 proof-of-concept.

    python -m jarvis.mcp list                 # connect, list every tool
    python -m jarvis.mcp call <tool> k=v ...  # call a tool, print its result

It connects the default local fleet (see config.DEFAULT_SERVERS) through the
async :class:`MCPRegistry`, but exposes a plain synchronous command interface so
it drops into the existing REPL/command style without forcing async on callers.

Arguments to ``call`` are given as ``key=value`` pairs; values are parsed as JSON
when possible (so ``count=3`` is an int) and otherwise kept as strings.
"""

from __future__ import annotations

import asyncio
import json
import sys

from .config import default_servers
from .registry import MCPRegistry


def _parse_kwargs(pairs: list[str]) -> dict:
    args: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Expected key=value, got {pair!r}")
        key, raw = pair.split("=", 1)
        try:
            args[key] = json.loads(raw)
        except json.JSONDecodeError:
            args[key] = raw
    return args


def _render_result(result) -> str:
    """Flatten an MCP CallToolResult into printable text."""
    if getattr(result, "isError", False):
        return "Tool reported an error:\n" + _render_content(result)
    return _render_content(result)


def _render_content(result) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else str(item))
    return "\n".join(parts) if parts else "(no content)"


async def _list() -> str:
    async with MCPRegistry(default_servers()) as reg:
        lines = [f"✓ Connected: {', '.join(reg.connected_servers) or '(none)'}"]
        for server, err in reg.failures.items():
            lines.append(f"✗ {server}: {err}")
        tools = await reg.list_tools()
        lines.append("")
        lines.append(f"Tools ({len(tools)}):")
        for tool in tools:
            summary = (tool.description or "").splitlines()[0] if tool.description else ""
            lines.append(f"  • {tool.qualified_name:<24} {summary}")
        return "\n".join(lines)


async def _call(tool: str, kwargs: dict) -> str:
    async with MCPRegistry(default_servers()) as reg:
        if reg.failures:
            fails = "; ".join(f"{s}: {e}" for s, e in reg.failures.items())
            print(f"Warning — some servers failed: {fails}", file=sys.stderr)
        result = await reg.call_tool(tool, kwargs)
        return _render_result(result)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "list":
            print(asyncio.run(_list()))
            return 0
        if cmd == "call":
            if not rest:
                print("Usage: call <tool> [key=value ...]", file=sys.stderr)
                return 2
            print(asyncio.run(_call(rest[0], _parse_kwargs(rest[1:]))))
            return 0
    except Exception as exc:  # noqa: BLE001 — CLI boundary: report, don't trace
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Unknown command: {cmd!r}. Try 'list' or 'call'.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
