#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.config import config_get, load_config, resolve_env_or_config
from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_str, issue_url, read_issue_keys


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move Jira tickets from a specific status to a target status."
    )
    parser.add_argument(
        "issues",
        nargs="*",
        help="Issue keys or browse URLs (e.g. https://jira.example.com/browse/PROJ-123).",
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
    only_status_default = env_str("JIRA_ONLY_STATUS") or config_get(
        config, "defaults.only_status"
    )
    parser.add_argument(
        "--only-status",
        default=only_status_default,
        help="Only transition tickets currently in this status (env: JIRA_ONLY_STATUS).",
    )
    target_status_default = env_str("JIRA_TARGET_STATUS") or config_get(
        config, "defaults.target_status"
    )
    parser.add_argument(
        "--target-status",
        default=target_status_default,
        help="Name of the status to transition to (required; env: JIRA_TARGET_STATUS).",
    )
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)
    if not args.target_status:
        print("Target status is required. Pass --target-status or set JIRA_TARGET_STATUS.", file=sys.stderr)
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
            total_processed = 0
            for key in issue_keys:
                print(f"\nProcessing {key} ({issue_url(settings.base_url, key)}):")
                try:
                    before, after, changed = service.transition_issue(
                        key,
                        required_status=args.only_status,
                        target_status=args.target_status,
                    )
                    if not changed:
                        print(
                            f"- Skipped: status is '{before}', needed '{args.only_status}'."
                        )
                        continue
                    print(f"- Status: {before} -> {after}")
                    total_processed += 1
                except IntegrationError as exc:
                    print(f"- Failed: {exc}", file=sys.stderr)
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    if total_processed == 0:
        print("No tickets were updated.", file=sys.stderr)
        return 1

    print(f"\nDone. Updated {total_processed} ticket(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
