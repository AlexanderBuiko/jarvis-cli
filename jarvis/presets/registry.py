import json
from pathlib import Path

from .schema import AssignmentPreset

_DATA_DIR = Path(__file__).parent / "data"

PRESET_NAMES: tuple[str, ...] = ("basic", "response_control", "prompting", "temperature")


def load_preset(name: str) -> AssignmentPreset:
    """Load and validate a preset by name. Raises ValueError for unknown names."""
    if name not in PRESET_NAMES:
        raise ValueError(
            f"Unknown mode '{name}'. Available modes: {', '.join(PRESET_NAMES)}"
        )
    path = _DATA_DIR / f"{name}.json"
    data = json.loads(path.read_text())
    return AssignmentPreset.from_dict(data)


def all_presets() -> dict[str, AssignmentPreset]:
    return {name: load_preset(name) for name in PRESET_NAMES}
