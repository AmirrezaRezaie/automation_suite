#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_int, env_str, issue_url

DEFAULT_PROJECT = "PROJECT"
DEFAULT_QUEUE_ID = 213


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List open Jira tickets for a project."
    )
    parser.add_argument(
        "--project",
        default=env_str("JIRA_PROJECT") or DEFAULT_PROJECT,
        help="Jira project key to search (default: %(default)s)",
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
        default=env_int("JIRA_TIMEOUT"),
        help="Override Jira connection timeout in seconds (env: JIRA_TIMEOUT).",
    )
    parser.add_argument(
        "--queue-id",
        type=str,
        default=env_str("JIRA_QUEUE_ID") or str(DEFAULT_QUEUE_ID),
        help="Queue identifier or name (accepts 'custom/213', numeric ID, or name).",
    )
    parser.add_argument(
        "--service-desk-id",
        type=int,
        default=env_int("JIRA_SERVICE_DESK_ID"),
        help="Explicit service desk ID (auto-detected from project key if omitted).",
    )
    parser.add_argument(
        "--use-jql",
        action="store_true",
        help="Use classic JQL search instead of service desk queue API.",
    )
    parser.add_argument(
        "--status",
        action="append",
        help="Filter issues by status name (use multiple --status for OR).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = JiraSettings.from_env(timeout=args.timeout)

    try:
        with connect_jira(settings) as client:
            service = JiraService(client, settings.base_url)
            issues, queue_info = service.list_open_issues(
                project=args.project,
                max_results=args.max_results,
                queue_id=args.queue_id,
                service_desk_id=args.service_desk_id,
                use_jql=args.use_jql,
                statuses=set(args.status) if args.status else None,
            )
    except IntegrationError as exc:
        print(f"Failed to fetch issues: {exc}", file=sys.stderr)
        return 1

    if not issues:
        print(f"No open issues found in project {args.project}.")
        return 0

    if queue_info:
        queue_name = queue_info.get("name") or args.queue_id
        print(
            f"Queue '{queue_name}' "
            f"(ID {queue_info.get('queueId')}, Service Desk {queue_info.get('serviceDeskId', 'n/a')})"
        )
    print(f"Found {len(issues)} open issues in project {args.project}:")
    total = len(issues)
    groups = 5
    chunk_size = max(1, (total + groups - 1) // groups)
    for idx, issue in enumerate(issues, start=1):
        print(issue_url(settings.base_url, issue.key))
        if idx % chunk_size == 0 and idx != total:
            print("-----")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
