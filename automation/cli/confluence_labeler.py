#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import Iterable
from xml.etree import ElementTree as ET

from automation.config import config_get, load_config, resolve_env_or_config
from automation.confluence import ConfluenceService, connect_confluence
from automation.confluence.client import ConfluenceError
from automation.confluence.service import extract_page_id
from automation.jira.client import IntegrationError, connect_jira
from automation.jira.service import JiraService
from automation.settings import ConfluenceSettings, JiraSettings
from automation.utils import env_str, extract_issue_key

# Namespaces for Confluence storage content
NS_AC = "http://atlassian.com/content"


def _parse_macro_params(raw_macro: str) -> dict[str, str]:
    """
    Parse macro XML snippet and return parameter dict.
    """
    try:
        root = ET.fromstring(f"<root>{raw_macro}</root>")
    except ET.ParseError:
        return {}
    params: dict[str, str] = {}
    for node in root.findall(".//ac:parameter", {"ac": NS_AC}):
        name = node.attrib.get(f"{{{NS_AC}}}name") or node.attrib.get("ac:name") or node.attrib.get("name")
        if not name:
            continue
        params[name.strip().lower()] = "".join(node.itertext()).strip()
    return params


def _collect_issue_keys(params: dict[str, str]) -> list[str]:
    keys: list[str] = []
    for candidate_name in ["key", "issuekey", "issuekeys", "issues"]:
        raw = params.get(candidate_name)
        if not raw:
            continue
        for token in raw.replace(";", ",").split(","):
            key = extract_issue_key(token)
            if key:
                keys.append(key)
    return keys


def _collect_jql(params: dict[str, str]) -> list[str]:
    queries: list[str] = []
    for candidate_name in ["jql", "jqlquery"]:
        raw = params.get(candidate_name)
        if raw:
            queries.append(raw.strip())
    return queries


def _merge_labels(config_value, env_raw: str | None, cli_values: Iterable[str] | None) -> list[str]:
    merged: list[str] = []
    if isinstance(config_value, (list, tuple, set)):
        merged.extend(str(item).strip() for item in config_value if str(item).strip())
    elif config_value:
        merged.extend([str(config_value).strip()])
    if env_raw:
        merged.extend([token.strip() for token in env_raw.split(",") if token.strip()])
    if cli_values:
        merged.extend([value for value in cli_values if value])
    return [value for value in merged if value]


def _merge_macro(config_value, env_raw: str | None, cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    if env_raw:
        return env_raw.strip()
    if config_value:
        return str(config_value).strip()
    return "jira"


def parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Jira issues referenced in Confluence macros and update labels."
    )
    parser.add_argument(
        "page",
        help="Confluence page id or URL.",
    )
    parser.add_argument(
        "--macro",
        dest="macro_name",
        help="Macro name to parse for Jira references (default: jira).",
    )
    parser.add_argument(
        "--is-parent",
        action=argparse.BooleanOptionalAction,
        default=resolve_env_or_config(
            "CONFLUENCE_IS_PARENT",
            config,
            "confluence.is_parent",
            cast=lambda v: str(v).strip().lower() in {"1", "true", "yes", "y", "on"},
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
        "--issue-type",
        dest="issue_type",
        help="Only update issues matching this issue type (e.g. Task, Sub-task).",
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
        "--timeout",
        type=int,
        default=resolve_env_or_config(
            "JIRA_TIMEOUT", config, "jira.timeout", cast=int
        ),
        help="Override Jira connection timeout in seconds.",
    )
    return parser.parse_args()


def main() -> int:
    config = load_config()
    args = parse_args(config)

    page_id = extract_page_id(args.page)
    if not page_id:
        print("Unable to determine page id from the provided value.", file=sys.stderr)
        return 1

    default_macro = config_get(config, "defaults.confluence_labeler.macro")
    macro_name = _merge_macro(default_macro, env_str("CONFLUENCE_LABEL_MACRO"), args.macro_name)

    default_add_labels = config_get(config, "defaults.confluence_labeler.add_labels")
    default_remove_labels = config_get(config, "defaults.confluence_labeler.remove_labels")
    default_issue_type = config_get(config, "defaults.confluence_labeler.issue_type")

    add_labels = _merge_labels(
        default_add_labels,
        env_str("CONFLUENCE_LABEL_ADD"),
        args.add_labels,
    )
    remove_labels = _merge_labels(
        default_remove_labels,
        env_str("CONFLUENCE_LABEL_REMOVE"),
        args.remove_labels,
    )
    issue_type = args.issue_type or env_str("CONFLUENCE_LABEL_ISSUE_TYPE") or default_issue_type
    issue_type_normalized = issue_type.lower() if issue_type else None

    if not add_labels and not remove_labels:
        print("No label changes specified. Use --add-label/--remove-label or set defaults.", file=sys.stderr)
        return 1

    try:
        with connect_confluence(ConfluenceSettings.from_env()) as conf_client:
            conf_service = ConfluenceService(conf_client, conf_client.base_url)
            pages, failed = conf_service.fetch_pages_with_content(
                root_page_id=page_id,
                is_parent=args.is_parent,
                section_title=None,
                macro_names=[macro_name],
                expand=["body.storage"],
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

    macro_issue_keys: set[str] = set()
    jql_queries: set[str] = set()
    for page in pages:
        macro_blocks = (page.get("macros") or {}).get(macro_name, [])
        for raw in macro_blocks:
            params = _parse_macro_params(raw)
            macro_issue_keys.update(_collect_issue_keys(params))
            jql_queries.update(_collect_jql(params))

    if not macro_issue_keys and not jql_queries:
        print("No issue keys or JQL queries found in macros.")
        return 1

    settings = JiraSettings.from_env(timeout=args.timeout)
    issue_keys: set[str] = set(macro_issue_keys)

    try:
        with connect_jira(settings) as jira_client:
            jira_service = JiraService(jira_client, settings.base_url)
            for query in jql_queries:
                try:
                    for key in jira_service.search_issue_keys(jql=query, max_results=200):
                        issue_keys.add(key)
                except IntegrationError as exc:
                    print(f"Failed JQL '{query}': {exc}", file=sys.stderr)

            successes: list[str] = []
            skipped: list[str] = []
            failures: list[tuple[str, str]] = []
            for key in sorted(issue_keys):
                try:
                    issue = jira_service.get_issue(key)
                    current_type = (issue.issue_type or "").lower()
                    if issue_type_normalized and current_type != issue_type_normalized:
                        skipped.append(key)
                        print(f"[skip] {key} (type: {issue.issue_type or 'unknown'})")
                        continue
                    jira_service.update_labels(key, add=add_labels, remove=remove_labels)
                    successes.append(key)
                    applied = []
                    if add_labels:
                        applied.append(f"add={','.join(add_labels)}")
                    if remove_labels:
                        applied.append(f"remove={','.join(remove_labels)}")
                    detail = f" ({'; '.join(applied)})" if applied else ""
                    print(f"[ok] {key}{detail}")
                except IntegrationError as exc:
                    failures.append((key, str(exc)))
                    print(f"[fail] {key}: {exc}", file=sys.stderr)
    except IntegrationError as exc:
        print(f"Failed to connect to Jira: {exc}", file=sys.stderr)
        return 1

    if successes:
        print(f"Updated labels on {len(successes)} issue(s): {', '.join(successes)}")
    if skipped:
        reason = f"issue type != {issue_type}" if issue_type else "issue type filter"
        print(f"Skipped {len(skipped)} issue(s) due to {reason}: {', '.join(skipped)}")
    if failures:
        print("Failed updates:", file=sys.stderr)
        for key, reason in failures:
            print(f"- {key}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
