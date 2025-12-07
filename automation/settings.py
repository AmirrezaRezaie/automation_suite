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
