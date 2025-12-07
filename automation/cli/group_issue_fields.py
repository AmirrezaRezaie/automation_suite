#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.config import config_get, load_config, resolve_env_or_config
from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import JiraSettings
from automation.utils import env_str, read_issue_keys


def parse_args(config: dict) -> argparse.Namespace:
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
        default=resolve_env_or_config(
            "JIRA_TIMEOUT", config, "jira.timeout", cast=int
        ),
        help="Override Jira connection timeout in seconds (env: JIRA_TIMEOUT).",
    )
    field_primary_default = (
        env_str("JIRA_FIELD_PRIMARY")
        or config_get(config, "defaults.field_primary")
    )
    parser.add_argument(
        "--field-primary",
        dest="field_primary",
        default=field_primary_default,
        help=(
            "Jira field name for the primary value to display "
            "(env: JIRA_FIELD_PRIMARY; default: %(default)s)."
        ),
    )
    field_secondary_default = (
        env_str("JIRA_FIELD_SECONDARY")
        or config_get(config, "defaults.field_secondary")
    )
    parser.add_argument(
        "--field-secondary",
        dest="field_secondary",
        default=field_secondary_default,
        help=(
            "Jira field name used for grouping with keywords "
            "(env: JIRA_FIELD_SECONDARY; default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--group-a-label",
        default=env_str("JIRA_GROUP_A_LABEL")
        or config_get(config, "defaults.group_a_label"),
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
        default=env_str("JIRA_GROUP_B_LABEL")
        or config_get(config, "defaults.group_b_label"),
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
        default=env_str("JIRA_LABEL_OTHER")
        or config_get(config, "defaults.label_other"),
        help="Display label for unmatched group (env: JIRA_LABEL_OTHER).",
    )
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)
    if not args.field_primary or not args.field_secondary:
        print(
            "Both --field-primary and --field-secondary are required "
            "(or set via config.json / env).",
            file=sys.stderr,
        )
        return 1
    if not args.group_a_label or not args.group_b_label or not args.label_other:
        print(
            "Labels for group A/B and other are required (set via flags, env, or config).",
            file=sys.stderr,
        )
        return 1
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
        env_str("JIRA_GROUP_A_KEYWORDS")
        or config_get(config, "defaults.group_a_keywords"),
        args.group_a_keywords,
    )
    group_b_keywords = _merge_keywords(
        env_str("JIRA_GROUP_B_KEYWORDS")
        or config_get(config, "defaults.group_b_keywords"),
        args.group_b_keywords,
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


def _merge_keywords(default_value, cli_values: list[str] | None) -> list[str]:
    tokens: list[str] = []
    tokens.extend(_normalize_keywords(default_value))
    if cli_values:
        for raw in cli_values:
            tokens.extend(_split_keywords(raw))
    return tokens


def _normalize_keywords(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    return _split_keywords(str(raw))


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
