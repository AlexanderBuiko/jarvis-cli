import json
import os
from pathlib import Path

from .schema import JarvisConfig

CONFIG_PATH = Path.home() / ".jarvis" / "config.json"


class ConfigManager:
    """Manages three-layer configuration: defaults → persisted → runtime overrides."""

    def __init__(self):
        self._defaults = JarvisConfig()
        self._persisted = self._load_persisted()
        # Runtime config starts as a copy of persisted (which layered on defaults)
        self._runtime = JarvisConfig.from_dict(self._persisted.to_dict())

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def current(self) -> JarvisConfig:
        """The effective config for this session (runtime layer)."""
        return self._runtime

    def set(self, key: str, raw_value: str) -> str:
        """Set a key on the runtime config and persist the change."""
        confirmation = self._runtime.set_field(key, raw_value)
        self._save_persisted()
        return confirmation

    def reset(self) -> None:
        """Reset all config to defaults and clear the persisted file."""
        self._runtime = JarvisConfig()
        self._persisted = JarvisConfig()
        self._save_persisted()

    def show(self) -> str:
        lines = ["Current configuration:", ""]
        data = self._runtime.to_dict()
        max_key_len = max(len(k) for k in data)
        for k, v in data.items():
            default_v = getattr(self._defaults, k)
            marker = "" if v == default_v else " *"
            lines.append(f"  {k:<{max_key_len}}  =  {v}{marker}")
        lines.append("")
        lines.append("  (* = changed from default)")
        return "\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_persisted(self) -> JarvisConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return JarvisConfig.from_dict(data)
            except Exception:
                pass  # Corrupt file — fall back to defaults
        return JarvisConfig()

    def _save_persisted(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self._runtime.to_dict(), indent=2))
