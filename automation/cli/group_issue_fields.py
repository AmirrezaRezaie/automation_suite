#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_int, env_str, read_issue_keys

DEFAULT_FIELD_PRIMARY = "Custom Field 1"
DEFAULT_FIELD_SECONDARY = "Custom Field 2"

DEFAULT_GROUP_A_LABEL = "Group A"
DEFAULT_GROUP_B_LABEL = "Group B"
DEFAULT_OTHER_LABEL = "Other/Unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch two Jira fields for issues and group results by keywords."
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
        default=env_int("JIRA_TIMEOUT"),
        help="Override Jira connection timeout in seconds (env: JIRA_TIMEOUT).",
    )
    parser.add_argument(
        "--field-primary",
        dest="field_primary",
        default=env_str("JIRA_FIELD_PRIMARY") or DEFAULT_FIELD_PRIMARY,
        help=(
            "Jira field name for the primary value to display "
            "(env: JIRA_FIELD_PRIMARY; default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--field-secondary",
        dest="field_secondary",
        default=env_str("JIRA_FIELD_SECONDARY") or DEFAULT_FIELD_SECONDARY,
        help=(
            "Jira field name used for grouping with keywords "
            "(env: JIRA_FIELD_SECONDARY; default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--group-a-label",
        default=env_str("JIRA_GROUP_A_LABEL") or DEFAULT_GROUP_A_LABEL,
        help="Display label for first match group (env: JIRA_GROUP_A_LABEL).",
    )
    parser.add_argument(
        "--group-a-keyword",
        action="append",
        dest="group_a_keywords",
        metavar="TOKEN[,TOKEN...]",
        help=(
            "Keyword(s) that map to group A (repeat flag or comma-separate). "
            "Env: JIRA_GROUP_A_KEYWORDS."
        ),
    )
    parser.add_argument(
        "--group-b-label",
        default=env_str("JIRA_GROUP_B_LABEL") or DEFAULT_GROUP_B_LABEL,
        help="Display label for second match group (env: JIRA_GROUP_B_LABEL).",
    )
    parser.add_argument(
        "--group-b-keyword",
        action="append",
        dest="group_b_keywords",
        metavar="TOKEN[,TOKEN...]",
        help=(
            "Keyword(s) that map to group B (repeat flag or comma-separate). "
            "Env: JIRA_GROUP_B_KEYWORDS."
        ),
    )
    parser.add_argument(
        "--label-other",
        default=env_str("JIRA_LABEL_OTHER") or DEFAULT_OTHER_LABEL,
        help="Display label for unmatched group (env: JIRA_LABEL_OTHER).",
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
    field_primary = args.field_primary
    field_secondary = args.field_secondary
    other_label = args.label_other
    group_a_label = args.group_a_label
    group_b_label = args.group_b_label
    group_a_keywords = _merge_keywords(
        env_str("JIRA_GROUP_A_KEYWORDS"), args.group_a_keywords
    )
    group_b_keywords = _merge_keywords(
        env_str("JIRA_GROUP_B_KEYWORDS"), args.group_b_keywords
    )
    try:
        with connect_jira(settings) as client:
            service = JiraService(client, settings.base_url)
            records, failed = service.fetch_issue_fields(
                issue_keys, [field_primary, field_secondary]
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

    grouped = {group_a_label: [], group_b_label: [], other_label: []}
    for entry in records:
        fields = entry.get("fields") or {}
        primary_raw = fields.get(field_primary)
        secondary_raw = fields.get(field_secondary)
        secondary_value = _normalize_value(secondary_raw)
        group = _categorize_value(
            secondary_value,
            [
                (group_a_label, group_a_keywords),
                (group_b_label, group_b_keywords),
            ],
            other_label,
        )
        grouped[group].append(
            {
                "primary_value": _normalize_value(primary_raw),
                "secondary_value": secondary_value,
                "key": entry.get("key"),
                "url": entry.get("url"),
            }
        )

    ordered_groups = [group_a_label, group_b_label, other_label]
    print(f"Fetched {sum(len(v) for v in grouped.values())} issues.")
    for group_name in ordered_groups:
        entries = grouped.get(group_name, [])
        if not entries:
            continue
        print(f"\n{group_name}:")
        for entry in entries:
            primary_text = entry["primary_value"] or "<no value>"
            print(f"- {primary_text}")

    return 0


def _normalize_value(raw_value) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        return raw_value.strip()
    if isinstance(raw_value, (list, tuple, set)):
        return ", ".join(str(item) for item in raw_value if item)
    return str(raw_value)


def _merge_keywords(env_value: str | None, cli_values: list[str] | None) -> list[str]:
    tokens: list[str] = []
    tokens.extend(_split_keywords(env_value))
    if cli_values:
        for raw in cli_values:
            tokens.extend(_split_keywords(raw))
    return tokens


def _split_keywords(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip().lower() for token in raw.split(",") if token.strip()]


def _categorize_value(
    value: str | None,
    groups: list[tuple[str, list[str]]],
    other_label: str,
) -> str:
    if not value:
        return other_label
    lowered = value.lower()
    for label, keywords in groups:
        for keyword in keywords:
            if keyword and keyword.lower() in lowered:
                return label
    return other_label


if __name__ == "__main__":
    raise SystemExit(main())
