"""
Runtime configuration manager.

Maintains a validated set of user-defined parameters. Any parameter not
explicitly set is absent from the runtime dict — the LLM client falls back
to its own defaults for missing fields.
"""

from typing import Any


def _parse_bool(raw: str) -> bool:
    if raw.lower() in ("true", "yes", "1", "on"):
        return True
    if raw.lower() in ("false", "no", "0", "off"):
        return False
    raise ValueError(f"Cannot convert '{raw}' to bool. Use true/false.")


_PARAM_PARSERS: dict[str, Any] = {
    "model":             str,
    "temperature":       float,
    "top_p":             float,
    "top_k":             int,
    "max_tokens":        int,
    "seed":              lambda v: None if v.lower() in ("none", "null", "") else int(v),
    "solution_strategy": str,
    "context_strategy":  str,
    "window_size":       int,
    "task_autonomy":     str,
}

_PARAM_VALIDATORS: dict[str, tuple] = {
    "temperature": (
        lambda v: 0.0 <= v <= 2.0,
        "temperature must be between 0.0 and 2.0",
    ),
    "top_p": (
        lambda v: 0.0 <= v <= 1.0,
        "top_p must be between 0.0 and 1.0",
    ),
    "solution_strategy": (
        lambda v: v in ("direct", "step_by_step", "prompt_generation", "expert_panel"),
        "solution_strategy must be one of: direct, step_by_step, prompt_generation, expert_panel",
    ),
    "context_strategy": (
        lambda v: v in ("none", "compression", "sliding_window", "sticky_facts", "topics"),
        "context_strategy must be one of: none, compression, sliding_window, sticky_facts, topics",
    ),
    "window_size": (
        lambda v: v >= 1,
        "window_size must be at least 1",
    ),
    "task_autonomy": (
        lambda v: v in ("auto", "manual"),
        "task_autonomy must be one of: auto, manual",
    ),
}

SUPPORTED_PARAMS: frozenset[str] = frozenset(_PARAM_PARSERS)


class ConfigManager:
    """
    Flat, validated key-value configuration store.

    Parameters are set explicitly by the user via config set / config update.
    Absent parameters are not sent to the API — the client uses its own defaults.
    config reset clears all user-set values.
    """

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    @property
    def runtime(self) -> dict[str, Any]:
        """The current set of user-defined parameters."""
        return dict(self._values)

    def set(self, key: str, raw_value: str) -> str:
        _require_supported(key)
        value = _parse_param(key, raw_value)
        self._values[key] = value
        return f"{key} = {value}"

    def update(self, pairs: list[str]) -> str:
        """Apply multiple key=value pairs atomically (all-or-nothing)."""
        parsed: list[tuple[str, Any]] = []
        for pair in pairs:
            if "=" not in pair:
                raise ValueError(f"Invalid syntax '{pair}'. Expected key=value.")
            key, _, raw = pair.partition("=")
            key = key.strip()
            _require_supported(key)
            value = _parse_param(key, raw.strip())
            parsed.append((key, value))
        for key, value in parsed:
            self._values[key] = value
        return "\n".join(f"  {k} = {v}" for k, v in parsed)

    def reset(self) -> None:
        """Clear all user-set parameters."""
        self._values.clear()

    def show(self) -> str:
        if not self._values:
            return "No parameters set. Using API defaults."
        lines = ["Active configuration:", ""]
        max_key = max(len(k) for k in self._values)
        for k, v in self._values.items():
            lines.append(f"  {k:<{max_key}}  =  {v}")
        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _require_supported(key: str) -> None:
    if key not in SUPPORTED_PARAMS:
        raise ValueError(
            f"Unknown parameter '{key}'. Run 'help' to see supported parameters."
        )


def _parse_param(key: str, raw: str) -> Any:
    parser = _PARAM_PARSERS[key]
    try:
        value = parser(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid value for '{key}': {exc}") from exc
    checker, msg = _PARAM_VALIDATORS.get(key, (None, ""))
    if checker is not None and not checker(value):
        raise ValueError(msg)
    return value
