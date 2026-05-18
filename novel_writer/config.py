import json
import os
from pathlib import Path
from typing import Any


CONFIG_FILE = Path(__file__).with_name("config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-pro",
    "max_tokens": 32768,
    "thinking": {
        "type": "enabled",
        "effort": "max",
    },
}


def _merge_config(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = defaults.copy()
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_config_file() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_config() -> dict[str, Any]:
    cfg = _merge_config(DEFAULT_CONFIG, _read_config_file())

    if not str(cfg.get("api_key", "")).strip():
        cfg["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "").strip()

    cfg["max_tokens"] = int(cfg["max_tokens"])
    return cfg
