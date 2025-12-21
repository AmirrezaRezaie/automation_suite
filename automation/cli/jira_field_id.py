#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from automation.config import load_config, resolve_env_or_config
from automation.jira.client import IntegrationError, connect_jira
from automation.settings import JiraSettings


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find Jira field ids by name.",
    )
    parser.add_argument(
        "name",
        help="Field name to search for (case-insensitive).",
    )
    parser.add_argument(
        "--contains",
        action="store_true",
        help="Match if the provided name is a substring of the field name.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=resolve_env_or_config(
            "JIRA_TIMEOUT", config, "jira.timeout", cast=int
        ),
        help="Override Jira connection timeout in seconds (env: JIRA_TIMEOUT).",
    )
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)
    target = args.name.strip().lower()
    if not target:
        print("Field name is required.", file=sys.stderr)
        return 1

    settings = JiraSettings.from_env(timeout=args.timeout)
    try:
        with connect_jira(settings) as client:
            fields = client.list_fields()
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    matches: list[dict] = []
    for field in fields:
        name = (field.get("name") or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if args.contains:
            if target in lowered:
                matches.append(field)
        elif lowered == target:
            matches.append(field)

    if not matches:
        print("No fields matched.")
        return 1

    for field in matches:
        print(f"FOUND: {field.get('id')}  ->  {field.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
