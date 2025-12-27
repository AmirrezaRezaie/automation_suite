#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.config import load_config, resolve_env_or_config
from automation.confluence import ConfluenceService, connect_confluence
from automation.confluence.client import ConfluenceError
from automation.confluence.service import extract_page_id
from automation.jira.client import FieldNotFoundError, IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import ConfluenceSettings, JiraSettings


def _bool_cast(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_key(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def _normalize_issue_type(value: str) -> str:
    cleaned = value.strip().lower()
    return cleaned.replace("-", "").replace(" ", "")


def _normalize_field_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "value" in value:
            return str(value["value"] or "").strip()
        if "name" in value:
            return str(value["name"] or "").strip()
    return str(value).strip()


def _find_table_value(tables: list[dict], key: str) -> str | None:
    wanted = _normalize_key(key)
    for table in tables or []:
        entries = table.get("key_value") or {}
        for entry_key, entry_value in entries.items():
            if _normalize_key(entry_key) == wanted:
                return str(entry_value).strip()
    return None


def _collect_jira_keys(macros: list[dict]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for macro in macros or []:
        name = (macro.get("name") or "").lower()
        if name != "jira":
            continue
        jira_data = macro.get("jira") or {}
        for key in jira_data.get("issue_keys") or []:
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Jira Report Related Team from Confluence child pages."
    )
    parser.add_argument(
        "page",
        help="Confluence page id or URL.",
    )
    parser.add_argument(
        "--is-parent",
        action=argparse.BooleanOptionalAction,
        default=resolve_env_or_config(
            "CONFLUENCE_IS_PARENT",
            config,
            "confluence.is_parent",
            cast=_bool_cast,
            default=True,
        ),
        help="Treat the provided page as a parent and iterate over its child pages.",
    )
    parser.add_argument(
        "--max-children",
        type=int,
        default=resolve_env_or_config(
            "CONFLUENCE_MAX_CHILDREN",
            config,
            "confluence.max_children",
            cast=int,
        ),
        help="Limit the number of child pages to fetch when --is-parent is set.",
    )
    parser.add_argument(
        "--confluence-timeout",
        type=int,
        default=resolve_env_or_config(
            "CONFLUENCE_TIMEOUT",
            config,
            "confluence.timeout",
            cast=int,
        ),
        help="Override Confluence connection timeout in seconds.",
    )
    parser.add_argument(
        "--jira-timeout",
        type=int,
        default=resolve_env_or_config(
            "JIRA_TIMEOUT",
            config,
            "jira.timeout",
            cast=int,
        ),
        help="Override Jira connection timeout in seconds.",
    )
    parser.add_argument(
        "--table-key",
        default="Related Team/Vertical",
        help="Table key to read from Confluence (default: %(default)s).",
    )
    parser.add_argument(
        "--jira-field",
        default="Report Related Team",
        help="Jira field name/id to update (default: %(default)s).",
    )
    parser.add_argument(
        "--issue-type",
        default="Task",
        help="Only update issues matching this issue type (default: %(default)s).",
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

    page_id = extract_page_id(args.page)
    if not page_id:
        print("Unable to determine page id from the provided value.", file=sys.stderr)
        return 1

    conf_settings = ConfluenceSettings.from_env(
        timeout=args.confluence_timeout,
        is_parent=args.is_parent,
    )

    try:
        with connect_confluence(conf_settings) as conf_client:
            conf_service = ConfluenceService(conf_client, conf_client.base_url)
            pages, failed = conf_service.fetch_targets(
                root_page_id=page_id,
                is_parent=args.is_parent,
                expand=["body.storage", "version", "ancestors"],
                max_children=args.max_children,
            )
    except ConfluenceError as exc:
        print(f"Failed to connect to Confluence: {exc}", file=sys.stderr)
        return 1

    if failed:
        print("Failed to fetch some pages:", file=sys.stderr)
        for ref, reason in failed:
            print(f"- {ref}: {reason}", file=sys.stderr)

    if not pages:
        print("No Confluence content fetched.", file=sys.stderr)
        return 1

    jira_settings = JiraSettings.from_env(timeout=args.jira_timeout)
    dry_run = args.dry_run
    updated: list[str] = []
    skipped_type: list[str] = []
    skipped_same: list[str] = []
    failures: list[tuple[str, str]] = []

    try:
        with connect_jira(jira_settings) as jira_client:
            jira_service = JiraService(jira_client, jira_settings.base_url)
            for page in pages:
                objects = conf_service.extract_page_objects(page)
                related_value = _find_table_value(objects.get("tables", []), args.table_key)
                issue_keys = _collect_jira_keys(objects.get("macros", []))
                if not related_value or not issue_keys:
                    continue
                for issue_key in issue_keys:
                    try:
                        issue = jira_service.get_issue(issue_key)
                    except IntegrationError as exc:
                        failures.append((issue_key, str(exc)))
                        continue
                    issue_type = issue.issue_type or ""
                    if _normalize_issue_type(issue_type) != _normalize_issue_type(args.issue_type):
                        skipped_type.append(issue_key)
                        continue
                    try:
                        current_value = issue.get(args.jira_field)
                    except FieldNotFoundError:
                        current_value = None
                    if _normalize_field_value(current_value) == _normalize_field_value(related_value):
                        skipped_same.append(issue_key)
                        continue
                    if dry_run:
                        print(f"[dry-run] {issue_key} -> {args.jira_field}='{related_value}'")
                        updated.append(issue_key)
                        continue
                    try:
                        jira_service.update_fields(issue_key, {args.jira_field: related_value})
                        print(f"{issue_key} -> {args.jira_field}='{related_value}'")
                        updated.append(issue_key)
                    except IntegrationError as exc:
                        failures.append((issue_key, str(exc)))
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    if not updated and not failures:
        print("No matching Jira issues found to update.")
        return 0

    print(f"Updated {len(updated)} issue(s).")
    if dry_run:
        print("Dry-run enabled. No changes were sent to Jira.")
    if skipped_type:
        print(f"Skipped (issue type mismatch): {len(skipped_type)}")
    if skipped_same:
        print(f"Skipped (already set): {len(skipped_same)}")
    if failures:
        print("Failures:", file=sys.stderr)
        for key, reason in failures:
            print(f"- {key}: {reason}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
