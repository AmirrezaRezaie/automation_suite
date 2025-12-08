from __future__ import annotations

from dataclasses import dataclass
import os

from .config import config_get, load_config, resolve_env_or_config


@dataclass
class JiraSettings:
    base_url: str
    username: str
    password: str
    timeout: int | None = None

    @classmethod
    def from_env(cls, *, timeout: int | None = None) -> "JiraSettings":
        config = load_config()
        return cls(
            base_url=os.getenv("JIRA_BASE_URL")
            or config_get(config, "jira.base_url"),
            username=os.getenv("JIRA_USERNAME")
            or config_get(config, "jira.username"),
            password=os.getenv("JIRA_PASSWORD")
            or config_get(config, "jira.password"),
            timeout=(
                timeout
                if timeout is not None
                else resolve_env_or_config(
                    "JIRA_TIMEOUT", config, "jira.timeout", cast=int
                )
            ),
        )


@dataclass
class ConfluenceSettings:
    base_url: str
    username: str
    password: str
    timeout: int | None = None
    is_parent: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        timeout: int | None = None,
        is_parent: bool | None = None,
    ) -> "ConfluenceSettings":
        config = load_config()

        def _bool_cast(value) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

        return cls(
            base_url=os.getenv("CONFLUENCE_BASE_URL")
            or config_get(config, "confluence.base_url"),
            username=os.getenv("CONFLUENCE_USERNAME")
            or config_get(config, "confluence.username"),
            password=os.getenv("CONFLUENCE_PASSWORD")
            or config_get(config, "confluence.password"),
            timeout=(
                timeout
                if timeout is not None
                else resolve_env_or_config(
                    "CONFLUENCE_TIMEOUT",
                    config,
                    "confluence.timeout",
                    cast=int,
                )
            ),
            is_parent=(
                is_parent
                if is_parent is not None
                else resolve_env_or_config(
                    "CONFLUENCE_IS_PARENT",
                    config,
                    "confluence.is_parent",
                    cast=_bool_cast,
                    default=False,
                )
            ),
        )
