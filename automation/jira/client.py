from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Generator

import requests

from ..settings import JiraSettings


class IntegrationError(RuntimeError):
    """Raised when a Jira call fails or configuration is invalid."""


class FieldNotFoundError(IntegrationError):
    """Raised when a requested Jira field cannot be resolved."""


class JiraIssue:
    def __init__(self, client: "JiraClient", payload: dict):
        self.client = client
        self.key = payload.get("key")
        self.fields = payload.get("fields") or {}

    @property
    def status(self) -> str | None:
        status_field = self.fields.get("status") or {}
        if isinstance(status_field, dict):
            return status_field.get("name")
        return None

    def get(self, field_name: str):
        """Return a field value by Jira display name or raw field id."""
        if field_name in self.fields:
            return self.fields[field_name]

        field_id = self.client.resolve_field_id(field_name)
        if not field_id or field_id not in self.fields:
            raise FieldNotFoundError(f"Field '{field_name}' not found on issue {self.key}.")
        return self.fields[field_id]

    def update(self, **fields) -> None:
        """Currently supports transitioning an issue by Status name."""
        status_target = fields.pop("Status", None)
        if fields:
            raise IntegrationError("Only status updates are supported.")
        if not status_target:
            return
        self.client.transition_issue(self.key, status_target)

    def refresh(self) -> None:
        refreshed = self.client.get_issue(self.key)
        self.fields = refreshed.fields


class JiraClient:
    def __init__(self, *, base_url: str, username: str, password: str, timeout: int | None = None):
        if not base_url or not username or not password:
            raise IntegrationError("JIRA_BASE_URL, JIRA_USERNAME, and JIRA_PASSWORD are required.")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout or 10
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({"Accept": "application/json"})
        self._field_id_by_name: dict[str, str] = {}

    def connect(self) -> None:
        """Validate connectivity and credentials."""
        self._request("GET", "/rest/api/2/myself")

    def close(self) -> None:
        self.session.close()

    def connection(self) -> SimpleNamespace:
        """Compatibility shim for service desk helpers."""
        return SimpleNamespace(_session=self.session, _options={"server": self.base_url})

    def search_issues(self, *, jql: str, max_results: int = 50) -> list[JiraIssue]:
        payload = self._request(
            "GET",
            "/rest/api/2/search",
            params={"jql": jql, "maxResults": max_results, "fields": "*all"},
        )
        issues = payload.get("issues", [])
        return [JiraIssue(self, issue) for issue in issues]

    def get_issue(self, key: str) -> JiraIssue:
        payload = self._request(
            "GET",
            f"/rest/api/2/issue/{key}",
            params={"fields": "*all"},
        )
        return JiraIssue(self, payload)

    def transition_issue(self, key: str, target_status: str) -> None:
        transitions = self._request("GET", f"/rest/api/2/issue/{key}/transitions").get(
            "transitions", []
        )
        target_id = None
        for entry in transitions:
            name = entry.get("name") or entry.get("to", {}).get("name")
            if name and name.lower() == target_status.lower():
                target_id = entry.get("id")
                break
        if not target_id:
            raise IntegrationError(
                f"No transition to '{target_status}' found for issue {key}."
            )
        self._request(
            "POST",
            f"/rest/api/2/issue/{key}/transitions",
            json={"transition": {"id": target_id}},
        )

    def update_issue(
        self,
        key: str,
        *,
        fields: dict | None = None,
        updates: dict | None = None,
    ) -> None:
        if not fields and not updates:
            raise IntegrationError("No updates provided for issue edit.")
        payload: dict = {}
        if fields:
            payload["fields"] = fields
        if updates:
            payload["update"] = updates
        self._request("PUT", f"/rest/api/2/issue/{key}", json=payload)

    def assign_issue(self, key: str, account_id: str) -> None:
        if not account_id:
            raise IntegrationError("Assignee account id is required.")
        self._request(
            "PUT",
            f"/rest/api/2/issue/{key}/assignee",
            json={"accountId": account_id},
        )

    def resolve_field_id(self, field_name: str) -> str | None:
        """Map a human-friendly field name to its Jira field id."""
        if not field_name:
            return None
        lowered = field_name.lower()
        if lowered in self._field_id_by_name:
            return self._field_id_by_name[lowered]
        # Allow direct usage of an existing field key
        if field_name.startswith("customfield_") or field_name in {"summary", "status"}:
            return field_name
        fields = self._request("GET", "/rest/api/2/field")
        for entry in fields:
            name = (entry.get("name") or "").lower()
            field_id = entry.get("id")
            if not name or not field_id:
                continue
            self._field_id_by_name[name] = field_id
        return self._field_id_by_name.get(lowered)

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        url = self._build_url(path)
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}
        except requests.HTTPError as exc:
            message = self._extract_error(response)
            raise IntegrationError(message) from exc
        except requests.RequestException as exc:
            raise IntegrationError(f"Jira request failed: {exc}") from exc

    def _build_url(self, path: str) -> str:
        cleaned_path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{cleaned_path}"

    def _extract_error(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            messages = payload.get("errorMessages") or payload.get("errors")
            if isinstance(messages, list):
                return "; ".join(messages)
            if isinstance(messages, dict):
                return "; ".join(f"{k}: {v}" for k, v in messages.items())
        except ValueError:
            pass
        return f"Jira API call failed ({response.status_code})"


@contextlib.contextmanager
def connect_jira(settings: JiraSettings) -> Generator[JiraClient, None, None]:
    """
    Create a Jira client with the provided settings and close it afterwards.
    """
    client = JiraClient(
        base_url=settings.base_url,
        username=settings.username,
        password=settings.password,
        timeout=settings.timeout,
    )
    client.connect()
    try:
        yield client
    finally:
        with contextlib.suppress(IntegrationError):
            client.close()
