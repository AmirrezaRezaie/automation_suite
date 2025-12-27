#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.config import config_get, load_config, resolve_env_or_config
from automation.jira.client import FieldNotFoundError, IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_str


def _normalize_issue_type(value: str | None) -> str:
    return (value or "").strip().lower()


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _stringify_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "key", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if candidate is not None and not isinstance(candidate, (list, dict, tuple, set)):
                return str(candidate).strip()
        return str(value).strip()
    if isinstance(value, (list, tuple, set)):
        parts = [_stringify_value(item) for item in value]
        return ", ".join([part for part in parts if part])
    return str(value).strip()


def _build_jql(project: str | None, issue_type: str | None, extra_jql: str | None) -> str:
    parts: list[str] = []
    if project:
        parts.append(f'project = "{project}"')
    if issue_type:
        parts.append(f'issuetype = "{issue_type}"')
    base = " AND ".join(parts)
    if extra_jql:
        if base:
            return f"({base}) AND ({extra_jql})"
        return extra_jql
    return base


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy a Jira field value from a source field to a target field."
    )
    parser.add_argument(
        "--project",
        default=resolve_env_or_config(
            "JIRA_PROJECT", config, "defaults.project", default="SRECORE"
        ),
        help="Jira project key to filter (env: JIRA_PROJECT).",
    )
    parser.add_argument(
        "--issue-type",
        dest="issue_type",
        default=resolve_env_or_config(
            "JIRA_COPY_ISSUE_TYPE",
            config,
            "defaults.copy_field.issue_type",
            default="Sub-task",
        ),
        help="Only update issues matching this issue type.",
    )
    parser.add_argument(
        "--source-field",
        required=True,
        help="Field name/id to copy from.",
    )
    parser.add_argument(
        "--target-field",
        required=True,
        help="Field name/id to copy to.",
    )
    parser.add_argument(
        "--jql",
        help="Additional JQL filter to combine with project/type.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=200,
        help="Maximum number of issues to fetch (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=resolve_env_or_config(
            "JIRA_TIMEOUT", config, "jira.timeout", cast=int
        ),
        help="Override Jira connection timeout in seconds (env: JIRA_TIMEOUT).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print updates without sending changes to Jira.",
    )
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)

    project = args.project or env_str("JIRA_PROJECT")
    issue_type = args.issue_type
    source_field = args.source_field
    target_field = args.target_field
    jql = _build_jql(project, issue_type, args.jql)

    if not jql:
        print("Project or JQL filter is required.", file=sys.stderr)
        return 1
    if not source_field or not target_field:
        print("Both --source-field and --target-field are required.", file=sys.stderr)
        return 1

    settings = JiraSettings.from_env(timeout=args.timeout)

    try:
        with connect_jira(settings) as client:
            service = JiraService(client, settings.base_url)
            issue_keys = service.search_issue_keys(jql=jql, max_results=args.max_results)
            if not issue_keys:
                print("No matching Jira issues found.")
                return 0

            updated: list[str] = []
            skipped_type: list[str] = []
            skipped_empty: list[str] = []
            skipped_same: list[str] = []
            failures: list[tuple[str, str]] = []

            for key in issue_keys:
                try:
                    issue = service.get_issue(key)
                    if issue_type and _normalize_issue_type(issue.issue_type) != _normalize_issue_type(issue_type):
                        skipped_type.append(key)
                        continue
                    try:
                        source_value = issue.get(source_field)
                    except FieldNotFoundError:
                        failures.append((key, f"source field '{source_field}' not found"))
                        continue
                    source_text = _stringify_value(source_value)
                    if _is_empty(source_text):
                        skipped_empty.append(key)
                        continue
                    try:
                        target_value = issue.get(target_field)
                    except FieldNotFoundError:
                        failures.append((key, f"target field '{target_field}' not found"))
                        continue
                    target_text = _stringify_value(target_value)
                    if source_text == target_text:
                        skipped_same.append(key)
                        continue
                    if args.dry_run:
                        print(f"[dry-run] {key} -> {target_field}")
                    else:
                        service.update_fields(key, {target_field: source_text})
                        print(f"[ok] {key}")
                    updated.append(key)
                except IntegrationError as exc:
                    failures.append((key, str(exc)))
                    print(f"[fail] {key}: {exc}", file=sys.stderr)
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    if updated:
        print(f"Updated {len(updated)} issue(s): {', '.join(updated)}")
    if skipped_type:
        print(f"Skipped (issue type mismatch): {len(skipped_type)}")
    if skipped_empty:
        print(f"Skipped (empty source field): {len(skipped_empty)}")
    if skipped_same:
        print(f"Skipped (same value): {len(skipped_same)}")
    if failures:
        print("Failed updates:", file=sys.stderr)
        for key, reason in failures:
            print(f"- {key}: {reason}", file=sys.stderr)
        return 1
    if args.dry_run:
        print("Dry-run enabled. No changes were sent to Jira.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
