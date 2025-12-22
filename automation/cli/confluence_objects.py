#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from automation.confluence import ConfluenceService, connect_confluence
from automation.confluence.client import ConfluenceError
from automation.confluence.service import extract_page_id
from automation.settings import ConfluenceSettings
from automation.config import load_config, resolve_env_or_config


def _bool_cast(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Confluence page objects (titles, headers, tables, macros)."
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
            default=False,
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
        "--timeout",
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
        "--output",
        help="Write JSON cache to a file instead of stdout.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser.parse_args()


def _dump_json(payload: object, *, pretty: bool, output_path: str | None) -> None:
    if pretty:
        text = json.dumps(payload, indent=2, sort_keys=False)
    else:
        text = json.dumps(payload, separators=(",", ":"))
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
    else:
        print(text)


def main() -> int:
    config = load_config()
    args = parse_args(config)
    page_id = extract_page_id(args.page)
    if not page_id:
        print("Unable to determine page id from the provided value.", file=sys.stderr)
        return 1

    settings = ConfluenceSettings.from_env(
        timeout=args.timeout,
        is_parent=args.is_parent,
    )

    try:
        with connect_confluence(settings) as client:
            service = ConfluenceService(client, settings.base_url)
            pages, failed = service.fetch_targets(
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

    cache_records = [service.build_cache_record(page) for page in pages]
    _dump_json(cache_records, pretty=args.pretty, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
