from __future__ import annotations

from dataclasses import dataclass
import os

from .utils import env_int


@dataclass
class JiraSettings:
    base_url: str
    username: str
    password: str
    timeout: int | None = None

    @classmethod
    def from_env(cls, *, timeout: int | None = None) -> "JiraSettings":
        return cls(
            base_url=os.getenv("JIRA_BASE_URL"),
            username=os.getenv("JIRA_USERNAME"),
            password=os.getenv("JIRA_PASSWORD"),
            timeout=timeout if timeout is not None else env_int("JIRA_TIMEOUT"),
        )
