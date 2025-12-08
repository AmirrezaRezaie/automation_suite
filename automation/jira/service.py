from __future__ import annotations

import requests
from typing import Iterable, Sequence

from .client import FieldNotFoundError, IntegrationError, JiraClient

from ..utils import issue_url

SERVICE_DESK_PAGE_LIMIT = 50


class JiraService:
    def __init__(self, client: JiraClient, base_url: str):
        self.client = client
        self.base_url = base_url

    # ----- List open issues -------------------------------------------------
    def list_open_issues(
        self,
        *,
        project: str,
        max_results: int,
        queue_id: str | None,
        service_desk_id: int | None,
        use_jql: bool,
        statuses: set[str] | None,
    ) -> tuple[list, dict | None]:
        jql = (
            f'project = "{project}" AND statusCategory != Done '
            "ORDER BY created DESC"
        )

        if use_jql or not queue_id:
            issues = self.client.search_issues(jql=jql, max_results=max_results)
            return self._filter_by_status(issues, statuses), None

        issues, queue_info = self._fetch_queue_issues(
            project_key=project,
            queue_identifier=queue_id,
            service_desk_id=service_desk_id,
            limit=max_results,
        )
        return self._filter_by_status(issues, statuses), queue_info

    def _filter_by_status(self, issues: list, statuses: set[str] | None) -> list:
        if not statuses:
            return issues
        wanted = {s.lower() for s in statuses}
        return [issue for issue in issues if issue.status and issue.status.lower() in wanted]

    # ----- Issue helpers ---------------------------------------------------
    def get_issue(self, issue_key: str):
        return self.client.get_issue(issue_key)

    def fetch_issue_fields(
        self,
        issue_keys: Iterable[str],
        field_names: Sequence[str],
    ) -> tuple[list[dict], list[tuple[str, str]]]:
        """Fetch specified fields for a list of issues."""
        results: list[dict] = []
        failed: list[tuple[str, str]] = []
        normalized_field_names = [name for name in field_names if name]

        for key in issue_keys:
            try:
                issue = self.client.get_issue(key)
                entry = {
                    "key": issue.key,
                    "url": issue_url(self.base_url, issue.key),
                    "status": issue.status,
                    "fields": {},
                }
                for name in normalized_field_names:
                    try:
                        entry["fields"][name] = issue.get(name)
                    except FieldNotFoundError:
                        entry["fields"][name] = None
                results.append(entry)
            except IntegrationError as exc:
                failed.append((key, str(exc)))

        return results, failed

    # ----- Transition issues ----------------------------------------------
    def transition_issue(
        self,
        issue_key: str,
        *,
        required_status: str | None,
        target_status: str,
    ) -> tuple[str, str, bool]:
        issue = self.client.get_issue(issue_key)
        before = issue.status or ""
        if required_status and before.lower() != required_status.lower():
            return before, before, False
        if before.lower() == target_status.lower():
            return before, before, False
        issue.update(Status=target_status)
        issue.refresh()
        after = issue.status or target_status
        return before, after, True

    # ----- Update issues --------------------------------------------------
    def update_fields(self, issue_key: str, fields_by_name: dict) -> None:
        """
        Update issue fields by display name or field id.
        """
        if not fields_by_name:
            return
        resolved: dict = {}
        for name, value in fields_by_name.items():
            if not name:
                continue
            field_id = self.client.resolve_field_id(name) or name
            resolved[field_id] = value
        if not resolved:
            raise IntegrationError("No valid fields to update.")
        self.client.update_issue(issue_key, fields=resolved, updates=None)

    def update_labels(
        self,
        issue_key: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> None:
        updates: list = []
        add_list = [label for label in (add or []) if label]
        remove_list = [label for label in (remove or []) if label]
        updates.extend({"add": label} for label in add_list)
        updates.extend({"remove": label} for label in remove_list)
        if not updates:
            return
        self.client.update_issue(issue_key, fields=None, updates={"labels": updates})

    def assign_issue(self, issue_key: str, account_id: str) -> None:
        self.client.assign_issue(issue_key, account_id)

    # ----- Service desk helpers -------------------------------------------
    def _fetch_queue_issues(
        self,
        *,
        project_key: str,
        queue_identifier: str,
        service_desk_id: int | None,
        limit: int,
    ) -> tuple[list, dict]:
        if not queue_identifier:
            raise IntegrationError("Queue ID is required to fetch queue issues.")

        sd_id_str = (
            str(service_desk_id)
            if service_desk_id is not None
            else self._find_service_desk_id(project_key)
        )
        queue_info = self._find_queue_info(sd_id_str, str(queue_identifier))
        issues = []
        queue_jql = queue_info.get("jql")
        if queue_jql:
            issues = self.client.search_issues(
                jql=queue_jql,
                max_results=limit,
            )
        if not issues:
            issue_keys = self._fetch_queue_issue_keys(
                service_desk_id=sd_id_str,
                queue_id=str(queue_info.get("queueId")),
                limit=limit,
            )
            for key in issue_keys:
                try:
                    issues.append(self.client.get_issue(key))
                except IntegrationError:
                    continue
        return issues, queue_info

    def _servicedesk_api_base(self) -> tuple:
        session = getattr(self.client, "session", None)
        if session is None:
            raise IntegrationError("Jira client session is unavailable.")
        api_base = f"{self.client.base_url.rstrip('/')}/rest/servicedeskapi"
        return session, api_base

    def _servicedesk_get(
        self,
        session,
        url: str,
        *,
        params: dict | None = None,
    ) -> dict:
        headers = {
            "Accept": "application/json",
            "X-ExperimentalApi": "opt-in",
        }
        try:
            response = session.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise IntegrationError(f"Service Desk API call failed: {exc}") from exc

    def _find_service_desk_id(
        self,
        project_key: str,
    ) -> str:
        session, api_base = self._servicedesk_api_base()
        start = 0
        while True:
            data = self._servicedesk_get(
                session,
                f"{api_base}/servicedesk",
                params={"start": start, "limit": SERVICE_DESK_PAGE_LIMIT},
            )
            values = data.get("values", [])
            for entry in values:
                if entry.get("projectKey") == project_key:
                    sd_id = entry.get("id")
                    if sd_id is not None:
                        return str(sd_id)
            if data.get("isLastPage") or not values:
                break
            start += len(values)
        raise IntegrationError(
            f"Unable to locate service desk for project {project_key}."
        )

    def _find_queue_info(
        self,
        service_desk_id: str,
        queue_identifier: str,
    ) -> dict:
        session, api_base = self._servicedesk_api_base()
        wanted_raw = queue_identifier.strip()
        candidate_tokens = {wanted_raw.lower()}
        if "/" in wanted_raw:
            candidate_tokens.add(wanted_raw.split("/")[-1].lower())
        if wanted_raw.lower().startswith("custom/"):
            candidate_tokens.add(wanted_raw.split("custom/", 1)[1].lower())
        candidate_tokens.add(f"custom/{wanted_raw}".lower())

        start = 0
        while True:
            data = self._servicedesk_get(
                session,
                f"{api_base}/servicedesk/{service_desk_id}/queue",
                params={"start": start, "limit": SERVICE_DESK_PAGE_LIMIT},
            )
            values = data.get("values", [])
            for entry in values:
                entry_id = str(entry.get("id") or "")
                entry_queue_id = str(entry.get("queueId") or entry_id)
                entry_name = (entry.get("name") or "").strip()
                entry_tokens = {
                    entry_id.lower(),
                    entry_queue_id.lower(),
                    entry_name.lower(),
                    f"custom/{entry_queue_id}".lower(),
                    f"queue/{entry_queue_id}".lower(),
                }
                if entry_tokens & candidate_tokens:
                    entry["queueId"] = entry_queue_id
                    entry["serviceDeskId"] = service_desk_id
                    return entry
            if data.get("isLastPage") or not values:
                break
            start += len(values)
        raise IntegrationError(
            f"Queue '{queue_identifier}' not found in service desk {service_desk_id}."
        )

    def _fetch_queue_issue_keys(
        self,
        *,
        service_desk_id: str,
        queue_id: str,
        limit: int,
    ) -> list[str]:
        session, api_base = self._servicedesk_api_base()
        collected: list[str] = []
        start = 0
        while len(collected) < limit:
            page_limit = min(SERVICE_DESK_PAGE_LIMIT, limit - len(collected))
            data = self._servicedesk_get(
                session,
                f"{api_base}/servicedesk/{service_desk_id}/queue/{queue_id}/issue",
                params={"start": start, "limit": page_limit},
            )
            values = data.get("values", [])
            for entry in values:
                issue_key = entry.get("issueKey")
                if issue_key:
                    collected.append(issue_key)
            if data.get("isLastPage") or not values:
                break
            start += len(values)
        return collected
