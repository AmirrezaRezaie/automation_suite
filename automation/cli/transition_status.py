#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_int, env_str, issue_url, read_issue_keys

DEFAULT_TARGET_STATUS = "Resolved this issue"
DEFAULT_REQUIRED_STATUS = "Waiting for support"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move Jira tickets from a specific status to a target status."
    )
    parser.add_argument(
        "issues",
        nargs="*",
        help="Issue keys or browse URLs (e.g. https://jira.snapp.ir/browse/SREAUTO-3208).",
    )
    parser.add_argument(
        "-f",
        "--file",
        help="Path to a file containing issue keys or URLs (one per line).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=env_int("JIRA_TIMEOUT"),
        help="Override Jira connection timeout in seconds (env: JIRA_TIMEOUT).",
    )
    parser.add_argument(
        "--only-status",
        default=env_str("JIRA_ONLY_STATUS") or DEFAULT_REQUIRED_STATUS,
        help="Only transition tickets currently in this status (default: %(default)s).",
    )
    parser.add_argument(
        "--target-status",
        default=env_str("JIRA_TARGET_STATUS") or DEFAULT_TARGET_STATUS,
        help="Name of the status to transition to (default: %(default)s).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
