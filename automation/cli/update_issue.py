#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from automation.config import load_config, resolve_env_or_config
from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import read_issue_keys


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
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)

    actions = any(
        [
            args.add_labels,
            args.remove_labels,
            args.set_summary,
            args.fields,
            args.assignee,
        ]
    )
    if not actions:
        print("No updates specified. Use --add-label/--remove-label/--set-summary/--set-field/--assignee.", file=sys.stderr)
        return 1

    try:
        issue_keys = read_issue_keys(args.issues, args.file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    settings = JiraSettings.from_env(timeout=args.timeout)
    field_updates = _parse_field_assignments(args.fields)
    if args.set_summary:
        field_updates["summary"] = args.set_summary

    add_labels = args.add_labels or []
    remove_labels = args.remove_labels or []
    assignee = args.assignee

    try:
        with connect_jira(settings) as client:
            service = JiraService(client, settings.base_url)
            successes: list[str] = []
            failures: list[tuple[str, str]] = []

            for key in issue_keys:
                try:
                    if field_updates:
                        service.update_fields(key, field_updates)
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
    if failures:
        print("Failed updates:", file=sys.stderr)
        for key, reason in failures:
            print(f"- {key}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
