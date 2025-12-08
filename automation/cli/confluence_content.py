#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from automation.config import config_get, load_config, resolve_env_or_config
from automation.confluence import ConfluenceService, connect_confluence
from automation.confluence.client import ConfluenceError
from automation.confluence.service import extract_page_id
from automation.settings import ConfluenceSettings
from automation.utils import env_str


def _bool_cast(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    tokens = []
    for part in raw.split(","):
        token = part.strip()
        if token:
            tokens.append(token)
    return tokens


def _merge_list(default_value, cli_values: Iterable[str] | None) -> list[str]:
    values: list[str] = []
    if isinstance(default_value, (list, tuple, set)):
        values.extend(str(item) for item in default_value if str(item).strip())
    elif default_value is not None:
        values.extend(_split_tokens(str(default_value)))
    if cli_values:
        for raw in cli_values:
            values.extend(_split_tokens(raw))
    return [value for value in values if value]


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Confluence content for a page, optionally traversing children."
    )
    parser.add_argument(
        "page",
        help="Confluence page id or URL.",
    )
    parser.add_argument(
        "--section",
        dest="section_title",
        help="Heading/section title to extract.",
    )
    parser.add_argument(
        "--macro",
        action="append",
        dest="macros",
        metavar="NAME[,NAME...]",
        help="Macro name(s) to extract (repeat flag or comma-separate).",
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
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)
    page_id = extract_page_id(args.page)
    if not page_id:
        print(
            "Unable to determine page id from the provided value.",
            file=sys.stderr,
        )
        return 1

    default_macros = config_get(config, "confluence.macros")
    macro_names = _merge_list(
        env_str("CONFLUENCE_MACROS") or default_macros,
        args.macros,
    )

    settings = ConfluenceSettings.from_env(
        timeout=args.timeout,
        is_parent=args.is_parent,
    )

    try:
        with connect_confluence(settings) as client:
            service = ConfluenceService(client, settings.base_url)
            pages, failed = service.fetch_pages_with_content(
                root_page_id=page_id,
                is_parent=args.is_parent,
                section_title=args.section_title,
                macro_names=macro_names,
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
        print("No Confluence content fetched.")
        return 1

    print(f"Fetched {len(pages)} page(s) from Confluence.")
    for page in pages:
        title = page.get("title") or page.get("id") or "<unknown>"
        print(f"\n=== {title} ===")
        print(page.get("url"))

        if args.section_title:
            print(f"\nSection '{args.section_title}':")
            section_html = page.get("section")
            if section_html:
                print(section_html)
            else:
                print("  <section not found>")

        if macro_names:
            for name in macro_names:
                print(f"\nMacro '{name}':")
                macro_blocks = (page.get("macros") or {}).get(name, [])
                if macro_blocks:
                    for idx, block in enumerate(macro_blocks, 1):
                        print(f"-- {name} #{idx} --")
                        print(block)
                else:
                    print("  <macro not found>")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
