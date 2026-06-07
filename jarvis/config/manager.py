import copy
from typing import Any

from ..presets.registry import load_preset, all_presets
from ..presets.schema import AssignmentPreset

_STARTUP_MODE = "basic"

def _parse_bool(raw: str) -> bool:
    if raw.lower() in ("true", "yes", "1", "on"):
        return True
    if raw.lower() in ("false", "no", "0", "off"):
        return False
    raise ValueError(f"Cannot convert '{raw}' to bool. Use true/false.")


# ── Global parameter schema ───────────────────────────────────────────────────
# Every parameter the system understands.  Validation uses this registry;
# mode presets have NO say in what is a valid parameter to set.

_PARAM_PARSERS: dict[str, Any] = {
    "temperature":            float,
    "top_p":                  float,
    "top_k":                  int,
    "max_tokens":             int,
    "seed":                   lambda v: None if v.lower() in ("none", "null", "") else int(v),
    "response_format":        str,
    "max_words":              int,
    "prompt_stop_enabled":    _parse_bool,
    "api_stop_enabled":       _parse_bool,
    "stop_sequence":          str,
    "solution_strategy":      str,
    "clarification_questions": int,
}

_PARAM_VALIDATORS: dict[str, tuple] = {
    "temperature":    (lambda v: 0.0 <= v <= 2.0,
                       "temperature must be between 0.0 and 2.0"),
    "top_p":          (lambda v: 0.0 <= v <= 1.0,
                       "top_p must be between 0.0 and 1.0"),
    "response_format": (lambda v: v in ("plain", "bullet_list", "numbered_list"),
                        "response_format must be one of: plain, bullet_list, numbered_list"),
    "solution_strategy": (lambda v: v in ("direct", "step_by_step", "prompt_generation", "expert_panel"),
                          "solution_strategy must be one of: direct, step_by_step, prompt_generation, expert_panel"),
}

SUPPORTED_PARAMS: frozenset[str] = frozenset(_PARAM_PARSERS)


class ConfigManager:
    """
    Mode-and-schema-aware configuration manager.

    Architecture
    ────────────
    - SUPPORTED_PARAMS: global schema of every valid parameter.
    - Mode preset: defines *default values* only — never restricts what can be set.
    - _user_overrides: parameters explicitly set by the user in this session.
    - _runtime: live view = preset.params | _user_overrides (user wins on conflict).

    config set / config update validate against SUPPORTED_PARAMS (schema),
    NOT against the active mode.  Any valid parameter may be set in any mode.

    Mode switch clears _user_overrides and reloads preset defaults.
    config reset clears _user_overrides and reloads preset defaults.
    """

    def __init__(self) -> None:
        self._preset: AssignmentPreset = load_preset(_STARTUP_MODE)
        self._user_overrides: dict[str, Any] = {}
        self._runtime: dict[str, Any] = copy.deepcopy(self._preset.params)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def runtime(self) -> dict[str, Any]:
        """The live configuration dict (preset defaults + user overrides)."""
        return self._runtime

    @property
    def active_preset(self) -> AssignmentPreset:
        return self._preset

    @property
    def active_mode(self) -> str:
        return self._preset.name

    def set_mode(self, name: str) -> str:
        """Switch mode.  Replaces preset defaults and clears user overrides."""
        preset = load_preset(name)
        self._preset = preset
        self._user_overrides = {}
        self._rebuild_runtime()

        lines = [
            f"Mode set to: {name}",
            f"  {preset.description}",
        ]
        if preset.params:
            lines.append("  Preset defaults:")
            for k, v in preset.params.items():
                lines.append(f"    {k} = {v}")
        else:
            lines.append("  Preset defaults: none (only model + messages sent)")
        return "\n".join(lines)

    def set(self, key: str, raw_value: str) -> str:
        """Set a parameter.  Valid for any key in SUPPORTED_PARAMS."""
        _require_supported(key)
        value = _parse_param(key, raw_value)
        self._user_overrides[key] = value
        self._rebuild_runtime()
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
            self._user_overrides[key] = value
        self._rebuild_runtime()
        return "\n".join(f"  {k} = {v}" for k, v in parsed)

    def reset(self) -> None:
        """Clear user overrides and restore the active mode's preset defaults."""
        self._user_overrides = {}
        self._rebuild_runtime()

    def show(self) -> str:
        lines = [
            f"Mode: {self._preset.name} — {self._preset.description}",
            "",
            "Effective configuration:",
            "",
        ]
        if self._runtime:
            max_key_len = max(len(k) for k in self._runtime)
            for k, v in self._runtime.items():
                marker = " *" if k in self._user_overrides else ""
                lines.append(f"  {k:<{max_key_len}}  =  {v}{marker}")
            if self._user_overrides:
                lines.append("")
                lines.append("  (* = explicitly set by user)")
        else:
            lines.append("  (none — only model and messages will be sent)")
        return "\n".join(lines)

    def show_modes(self) -> str:
        presets = all_presets()
        lines = [f"Active mode: {self._preset.name}", "", "Available modes:", ""]
        for name, preset in presets.items():
            marker = "  * " if name == self._preset.name else "    "
            lines.append(f"{marker}{name:<16} — {preset.description}")
            if preset.params:
                for k, v in preset.params.items():
                    lines.append(f"      {k} = {v}  (preset default)")
            else:
                lines.append("      (no preset defaults — only model + messages)")
        lines += ["", "Usage: mode <name>"]
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _rebuild_runtime(self) -> None:
        """Runtime = preset defaults, with user overrides applied on top."""
        self._runtime = {**self._preset.params, **self._user_overrides}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_supported(key: str) -> None:
    if key not in SUPPORTED_PARAMS:
        raise ValueError(
            f"Unknown parameter '{key}'. "
            f"Run 'help' to see all supported parameters."
        )


def _parse_param(key: str, raw: str) -> Any:
    """Parse *raw* string into the correct type for *key*."""
    parser = _PARAM_PARSERS[key]
    try:
        value = parser(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid value for '{key}': {exc}") from exc
    checker, msg = _PARAM_VALIDATORS.get(key, (None, ""))
    if checker is not None and not checker(value):
        raise ValueError(msg)
    return value
