#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_int, read_issue_keys

FIELD_FQDN = "Monitoring Dependencies (FQDN)"
FIELD_DB_TYPE = "Monitoring Dependencies (DB Type)"

MYSQL_LABEL = "MySQL/MariaDB"
POSTGRES_LABEL = "PostgreSQL"
OTHER_LABEL = "Other/Unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Monitoring Dependencies (FQDN/DB Type) for Jira issues "
            "and group them by DB type."
        )
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
            records, failed = service.fetch_issue_fields(
                issue_keys, [FIELD_FQDN, FIELD_DB_TYPE]
            )
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    if failed:
        print("Failed to fetch some issues:", file=sys.stderr)
        for key, reason in failed:
            print(f"- {key}: {reason}", file=sys.stderr)

    if not records:
        print("No issue details fetched.")
        return 1

    grouped = {MYSQL_LABEL: [], POSTGRES_LABEL: [], OTHER_LABEL: []}
    for entry in records:
        fields = entry.get("fields") or {}
        fqdn_raw = fields.get(FIELD_FQDN)
        db_type_raw = fields.get(FIELD_DB_TYPE)
        db_type_str = _normalize_value(db_type_raw)
        group = _categorize_db_type(db_type_str)
        grouped[group].append(
            {
                "fqdn": _normalize_value(fqdn_raw),
                "db_type": db_type_str,
                "key": entry.get("key"),
                "url": entry.get("url"),
            }
        )

    ordered_groups = [MYSQL_LABEL, POSTGRES_LABEL, OTHER_LABEL]
    print(f"Fetched {sum(len(v) for v in grouped.values())} issues.")
    for group_name in ordered_groups:
        entries = grouped.get(group_name, [])
        if not entries:
            continue
        print(f"\n{group_name}:")
        for entry in entries:
            fqdn_text = entry["fqdn"] or "<no FQDN>"
            print(f"- {fqdn_text}")

    return 0


def _normalize_value(raw_value) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        return raw_value.strip()
    if isinstance(raw_value, (list, tuple, set)):
        return ", ".join(str(item) for item in raw_value if item)
    return str(raw_value)


def _categorize_db_type(db_type: str | None) -> str:
    if not db_type:
        return OTHER_LABEL
    lowered = db_type.lower()
    if "mysql" in lowered or "mariadb" in lowered:
        return MYSQL_LABEL
    if "postgres" in lowered:
        return POSTGRES_LABEL
    return OTHER_LABEL


if __name__ == "__main__":
    raise SystemExit(main())
