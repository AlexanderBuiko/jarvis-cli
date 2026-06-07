from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssignmentPreset:
    """
    A complete, isolated configuration snapshot for one assignment mode.

    ``params`` is the single source of truth: it defines exactly which
    parameters exist in this mode and their default values.  Nothing outside
    ``params`` is visible to the rest of the system while this preset is active.
    """

    name: str
    description: str
    params: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict) -> "AssignmentPreset":
        return cls(
            name=data["name"],
            description=data["description"],
            params=data.get("params", {}),
        )
