from dataclasses import dataclass, field, asdict
from typing import Literal


@dataclass
class JarvisConfig:
    # Generation parameters
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    max_tokens: int = 200
    seed: int | None = None

    # Prompt-level formatting
    response_format: Literal["plain", "bullet_list", "numbered_list"] = "plain"
    max_words: int = 200

    # Clarification questions
    clarification_questions: int = 0

    # Stop controls
    prompt_stop_enabled: bool = False
    api_stop_enabled: bool = False
    stop_sequence: str = "###END###"

    # Control mode
    control_mode: Literal["prompt", "api", "both"] = "both"

    # Prompting strategy
    solution_strategy: Literal["direct", "step_by_step", "prompt_generation", "expert_panel"] = "direct"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "JarvisConfig":
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def set_field(self, key: str, raw_value: str) -> str:
        """Parse raw string value and set the field. Returns a human-readable confirmation."""
        import typing
        fields = self.__dataclass_fields__
        if key not in fields:
            raise ValueError(f"Unknown config key: '{key}'. Run 'config show' to see available keys.")

        # get_type_hints() always returns resolved type objects, regardless of
        # Python version or whether annotations are stored as strings or types.
        hints = typing.get_type_hints(self.__class__)
        hint = hints[key]

        # Map resolved type hints to converters
        type_map = {
            float: float,
            int: int,
            bool: _parse_bool,
            str: str,
        }

        # Handle Optional / union types (e.g. int | None)
        import types as _types
        origin = getattr(hint, "__origin__", None)
        is_union = origin is typing.Union or isinstance(hint, _types.UnionType)
        if is_union:
            inner_args = [a for a in hint.__args__ if a is not type(None)]
            base_type = inner_args[0] if inner_args else str
            converter = _parse_optional_int if base_type is int else type_map.get(base_type, str)
        else:
            converter = type_map.get(hint, str)
        value = converter(raw_value)

        # Validate specific fields
        if key == "response_format" and value not in ("plain", "bullet_list", "numbered_list"):
            raise ValueError("response_format must be one of: plain, bullet_list, numbered_list")
        if key == "control_mode" and value not in ("prompt", "api", "both"):
            raise ValueError("control_mode must be one of: prompt, api, both")
        if key == "solution_strategy" and value not in ("direct", "step_by_step", "prompt_generation", "expert_panel"):
            raise ValueError("solution_strategy must be one of: direct, step_by_step, prompt_generation, expert_panel")
        if key == "temperature" and not (0.0 <= float(raw_value) <= 2.0):
            raise ValueError("temperature must be between 0.0 and 2.0")
        if key == "top_p" and not (0.0 <= float(raw_value) <= 1.0):
            raise ValueError("top_p must be between 0.0 and 1.0")

        setattr(self, key, value)
        return f"{key} = {value}"


def _parse_bool(value: str) -> bool:
    if value.lower() in ("true", "yes", "1", "on"):
        return True
    if value.lower() in ("false", "no", "0", "off"):
        return False
    raise ValueError(f"Cannot convert '{value}' to bool. Use true/false.")


def _parse_optional_int(value: str) -> int | None:
    if value.lower() in ("none", "null", ""):
        return None
    return int(value)
