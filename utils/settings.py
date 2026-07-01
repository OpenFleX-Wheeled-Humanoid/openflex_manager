"""Application settings persistence."""

from pathlib import Path
from typing import Any

import yaml


DEFAULT_SETTINGS = {
    "language": "zh_CN",
    "theme": "dark",
    "sudo_password": None,
    "can_driver": "kcan",
    "log_font_family": "Monospace",
    "log_font_size": 12,
}


class SettingsManager:
    def __init__(self, path: Path | None = None):
        self.path = path or (Path(__file__).resolve().parent.parent / "config" / "app_settings.yaml")
        self._settings: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}

        self._settings = {**DEFAULT_SETTINGS, **data}
        self.save()
        return self._settings

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self._settings, f, allow_unicode=True, sort_keys=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._settings[key] = value
        self.save()
