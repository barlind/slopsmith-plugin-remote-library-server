from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .models import utc_now_iso


def _default_settings() -> dict:
    return {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8765,
        "sourceName": "",
        "publicUrl": "",
    }


class RemoteLibraryServerStore:
    def __init__(self, config_dir: Path) -> None:
        self.root = Path(config_dir) / "remote_library_server"
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.root / "settings.json"
        self.state_path = self.root / "state.json"
        self._lock = RLock()

    def load_settings(self) -> dict:
        settings = _default_settings()
        if self.settings_path.exists():
            try:
                loaded = json.loads(self.settings_path.read_text())
                if isinstance(loaded, dict):
                    settings.update(loaded)
            except json.JSONDecodeError:
                pass
        return settings

    def save_settings(self, data: dict) -> dict:
        settings = self.load_settings()
        settings.update({key: value for key, value in data.items() if value is not None})
        with self._lock:
            self.settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True))
        return settings

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"activity": []}
        try:
            state = json.loads(self.state_path.read_text())
        except json.JSONDecodeError:
            return {"activity": []}
        if not isinstance(state, dict):
            return {"activity": []}
        state.setdefault("activity", [])
        return state

    def _save_state(self, state: dict) -> None:
        with self._lock:
            self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def add_activity(self, event_type: str, outcome: str, message: str, **extra) -> None:
        state = self._load_state()
        activity = list(state.get("activity", []))
        activity.append({
            "eventType": event_type,
            "outcome": outcome,
            "message": message,
            "createdAt": utc_now_iso(),
            **extra,
        })
        state["activity"] = activity[-200:]
        self._save_state(state)

    def list_activity(self) -> list[dict]:
        return list(reversed(self._load_state().get("activity", [])))