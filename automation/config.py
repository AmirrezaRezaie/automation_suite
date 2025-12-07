from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_CONFIG_FILE = "config.json"
CONFIG_PATH_ENV = "JIRA_CONFIG_FILE"


def load_config(path: str | None = None) -> dict:
    """
    Load config from JSON. Uses env JIRA_CONFIG_FILE or config.json in repo root by default.
    Missing or invalid files return an empty dict.
    """
    target = path or os.getenv(CONFIG_PATH_ENV) or DEFAULT_CONFIG_FILE
    if not target or not os.path.isfile(target):
        return {}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def config_get(config: dict, dotted_path: str, default: Any = None) -> Any:
    """Fetch a value from nested dictionaries using dot notation."""
    current: Any = config
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return default if current is None else current


def resolve_env_or_config(
    env_name: str,
    config: dict,
    dotted_path: str,
    *,
    default: Any = None,
    cast=None,
) -> Any:
    """
    Prefer an environment variable; fall back to a config value; finally use the default.
    Optional cast is applied when possible (e.g. int).
    """
    env_val = os.getenv(env_name)
    if env_val not in (None, ""):
        return _maybe_cast(env_val, cast, default)
    value = config_get(config, dotted_path, default)
    return _maybe_cast(value, cast, default)


def _maybe_cast(value: Any, cast, default: Any) -> Any:
    if cast is None or value is None:
        return value
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default
