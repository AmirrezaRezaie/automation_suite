#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from automation.config import config_get, load_config, resolve_env_or_config
from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_str, read_issue_keys


def _parse_field_assignments(raw_values: Iterable[str] | None) -> dict:
    """
    Parse KEY=VALUE entries into a dict.
    """
    assignments: dict[str, str] = {}
    if not raw_values:
        return assignments
    for raw in raw_values:
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            continue
        assignments[key] = value.strip()
    return assignments


def _split_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    tokens = []
    for part in raw.split(","):
        token = part.strip()
        if token:
            tokens.append(token)
    return tokens


def _merge_labels(config_value, env_raw: str | None, cli_values: Iterable[str] | None) -> list[str]:
    merged: list[str] = []
    if isinstance(config_value, (list, tuple, set)):
        merged.extend(str(item).strip() for item in config_value if str(item).strip())
    elif config_value:
        merged.extend(_split_tokens(str(config_value)))
    merged.extend(_split_tokens(env_raw))
    if cli_values:
        merged.extend([value for value in cli_values if value])
    # Preserve order but drop empties
    return [value for value in merged if value]


def _merge_fields(config_fields, env_raw: str | None, cli_values: Iterable[str] | None) -> dict:
    merged: dict[str, str] = {}
    if isinstance(config_fields, dict):
        merged.update({str(k): str(v) for k, v in config_fields.items() if str(k).strip()})
    elif config_fields:
        merged.update(_parse_field_assignments(_split_tokens(str(config_fields))))
    merged.update(_parse_field_assignments(_split_tokens(env_raw)))
    if cli_values:
        merged.update(_parse_field_assignments(cli_values))
    return merged


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update Jira issues (labels, summary, fields, assignee)."
    )
    parser.add_argument(
        "issues",
        nargs="*",
        help="Issue keys or browse URLs.",
    )
    parser.add_argument(
        "-f",
        "--file",
        help="Path to a file containing issue keys or URLs (one per line).",
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
        "--add-label",
        action="append",
        dest="add_labels",
        metavar="LABEL",
        help="Label to add (repeatable).",
    )
    parser.add_argument(
        "--remove-label",
        action="append",
        dest="remove_labels",
        metavar="LABEL",
        help="Label to remove (repeatable).",
    )
    parser.add_argument(
        "--set-summary",
        help="Update the issue summary/title.",
    )
    parser.add_argument(
        "--set-field",
        action="append",
        dest="fields",
        metavar="NAME=VALUE",
        help="Set a field by display name or field id (repeatable).",
    )
    parser.add_argument(
        "--assignee",
        help="Set assignee by accountId.",
    )
    parser.add_argument(
        "--issue-type",
        dest="issue_type",
        help="Only update issues matching this issue type (e.g. Task, Sub-task).",
    )
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)

    default_add_labels = config_get(config, "defaults.update.add_labels")
    default_remove_labels = config_get(config, "defaults.update.remove_labels")
    default_fields = config_get(config, "defaults.update.fields")
    default_summary = config_get(config, "defaults.update.summary")
    default_assignee = config_get(config, "defaults.update.assignee")
    default_issue_type = config_get(config, "defaults.update.issue_type")

    add_labels = _merge_labels(
        default_add_labels,
        env_str("JIRA_UPDATE_ADD_LABELS"),
        args.add_labels,
    )
    remove_labels = _merge_labels(
        default_remove_labels,
        env_str("JIRA_UPDATE_REMOVE_LABELS"),
        args.remove_labels,
    )
    field_updates = _merge_fields(
        default_fields,
        env_str("JIRA_UPDATE_FIELDS"),
        args.fields,
    )
    summary = args.set_summary or env_str("JIRA_UPDATE_SUMMARY") or default_summary
    assignee = args.assignee or env_str("JIRA_UPDATE_ASSIGNEE") or default_assignee
    issue_type = args.issue_type or env_str("JIRA_UPDATE_ISSUE_TYPE") or default_issue_type
    issue_type_normalized = issue_type.lower() if issue_type else None

    actions = any(
        [
            add_labels,
            remove_labels,
            summary,
            field_updates,
            assignee,
        ]
    )
    if not actions:
        print(
            "No updates specified. Use config/defaults or flags: "
            "--add-label/--remove-label/--set-summary/--set-field/--assignee.",
            file=sys.stderr,
        )
        return 1

    try:
        issue_keys = read_issue_keys(args.issues, args.file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    settings = JiraSettings.from_env(timeout=args.timeout)

    try:
        with connect_jira(settings) as client:
            service = JiraService(client, settings.base_url)
            successes: list[str] = []
            failures: list[tuple[str, str]] = []
            skipped: list[str] = []

            for key in issue_keys:
                try:
                    if issue_type_normalized:
                        issue = service.get_issue(key)
                        current_type = (issue.issue_type or "").lower()
                        if current_type != issue_type_normalized:
                            skipped.append(key)
                            continue
                    if field_updates:
                        service.update_fields(key, field_updates)
                    if summary:
                        service.update_fields(key, {"summary": summary})
                    if add_labels or remove_labels:
                        service.update_labels(key, add=add_labels, remove=remove_labels)
                    if assignee:
                        service.assign_issue(key, assignee)
                    successes.append(key)
                except IntegrationError as exc:
                    failures.append((key, str(exc)))
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    if successes:
        print(f"Updated {len(successes)} issue(s): {', '.join(successes)}")
    if skipped:
        print(
            f"Skipped {len(skipped)} issue(s) that did not match type '{issue_type}': {', '.join(skipped)}"
        )
    if failures:
        print("Failed updates:", file=sys.stderr)
        for key, reason in failures:
            print(f"- {key}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
