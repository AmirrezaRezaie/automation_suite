from __future__ import annotations

import re
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET

from .client import ConfluenceClient, ConfluenceError
from ..utils import extract_issue_key

# Namespaces used by Confluence storage format
NS_AC = "http://atlassian.com/content"
NS_RI = "http://atlassian.com/resource/identifier"
ET.register_namespace("ac", NS_AC)
ET.register_namespace("ri", NS_RI)



def _wrap_storage(raw: str) -> str:
    return (
        f'<root xmlns:ac="{NS_AC}" xmlns:ri="{NS_RI}">'
        f"{raw}"
        "</root>"
    )


def _parse_storage(raw: str | None) -> ET.Element | None:
    if not raw:
        return None
    try:
        return ET.fromstring(_wrap_storage(raw))
    except ET.ParseError:
        return None


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def _strip_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if tag else ""


def _iter_headings(root: ET.Element):
    heading_tags = {f"h{idx}" for idx in range(1, 7)}
    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            tag = _strip_tag(child.tag)
            if tag.lower() not in heading_tags:
                continue
            yield parent, index, child


def _serialize_elements(elements: Sequence[ET.Element]) -> str:
    return "".join(ET.tostring(elem, encoding="unicode") for elem in elements)


def extract_heading_section(storage: str, title: str) -> str | None:
    """
    Return the HTML for a heading and its following siblings until the next heading.
    """
    root = _parse_storage(storage)
    if root is None:
        return None
    target = _normalize_text(title).lower()
    for parent, index, heading in _iter_headings(root):
        heading_text = _normalize_text("".join(heading.itertext())).lower()
        if heading_text != target:
            continue
        siblings = list(parent)
        collected = [heading]
        for sibling in siblings[index + 1 :]:
            tag = sibling.tag.split("}", 1)[-1]
            if tag.lower().startswith("h") and len(tag) == 2:
                break
            collected.append(sibling)
        return _serialize_elements(collected)
    return None


def extract_macro_contents(storage: str, macro_name: str) -> list[str]:
    root = _parse_storage(storage)
    if root is None:
        return []
    results: list[str] = []
    wanted = macro_name.lower()
    for node in root.findall(".//ac:structured-macro", {"ac": NS_AC}):
        name_attr = node.attrib.get(f"{{{NS_AC}}}name") or node.attrib.get("ac:name")
        if not name_attr or name_attr.lower() != wanted:
            continue
        results.append(ET.tostring(node, encoding="unicode"))
    return results


def _collect_issue_keys_from_params(params: dict[str, str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for candidate_name in ["key", "issuekey", "issuekeys", "issues"]:
        raw = params.get(candidate_name)
        if not raw:
            continue
        for token in re.split(r"[,\n;]+", raw):
            key = extract_issue_key(token)
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys


def _extract_headers(root: ET.Element) -> list[dict]:
    titles: list[dict] = []
    for node in root.iter():
        tag = _strip_tag(node.tag).lower()
        if tag not in {f"h{idx}" for idx in range(1, 7)}:
            continue
        text = _normalize_text("".join(node.itertext()))
        if not text:
            continue
        level = int(tag[1])
        entry = {"level": level, "text": text}
        if level == 1:
            titles.append(entry)
    return titles


def _merge_key_value(target: dict, key: str, value: str) -> None:
    if key not in target:
        target[key] = value
        return
    existing = target[key]
    if existing == value:
        return
    if isinstance(existing, list):
        existing.append(value)
    else:
        target[key] = [existing, value]


def _extract_tables(root: ET.Element) -> list[dict]:
    tables: list[dict] = []
    for node in root.iter():
        if _strip_tag(node.tag).lower() != "table":
            continue
        table_data = {
            "key_value": {},
        }
        for row in node.findall(".//tr"):
            cells: list[str] = []
            is_header_row = False
            for cell in list(row):
                cell_tag = _strip_tag(cell.tag).lower()
                if cell_tag not in {"th", "td"}:
                    continue
                cells.append(_normalize_text("".join(cell.itertext())))
                if cell_tag == "th":
                    is_header_row = True
            if not cells:
                continue
            if is_header_row:
                continue
            if len(cells) < 2:
                continue
            key = cells[0]
            value = cells[1]
            if key:
                _merge_key_value(table_data["key_value"], key, value)
        if table_data["key_value"]:
            tables.append(table_data)
    return tables


def _extract_macro_params(node: ET.Element) -> dict[str, str]:
    params: dict[str, str] = {}
    for param in node.findall("ac:parameter", {"ac": NS_AC}):
        name = param.attrib.get(f"{{{NS_AC}}}name") or param.attrib.get("ac:name")
        if not name:
            continue
        params[name.strip().lower()] = _normalize_text("".join(param.itertext()))
    return params


def _extract_macros(root: ET.Element) -> list[dict]:
    macros: list[dict] = []
    for node in root.findall(".//ac:structured-macro", {"ac": NS_AC}):
        name = node.attrib.get(f"{{{NS_AC}}}name") or node.attrib.get("ac:name")
        if not name:
            continue
        params = _extract_macro_params(node)
        entry = {
            "name": name,
            "parameters": params,
        }
        if name.lower() == "jira":
            jql = []
            for candidate in ("jql", "jqlquery"):
                raw = params.get(candidate)
                if raw:
                    jql.append(raw)
            issue_keys = _collect_issue_keys_from_params(params)
            entry["jira"] = {
                "issue_keys": issue_keys,
                "jql": jql,
            }
        macros.append(entry)
    return macros


def extract_storage_objects(storage: str) -> dict:
    root = _parse_storage(storage)
    if root is None:
        return {"titles": [], "tables": [], "macros": []}
    titles = _extract_headers(root)
    return {
        "titles": titles,
        "tables": _extract_tables(root),
        "macros": _extract_macros(root),
    }


def build_cache_payload(page: dict, objects: dict, *, base_url: str) -> dict:
    version = page.get("version") or {}
    return {
        "page": {
            "id": page.get("id"),
            "title": page.get("title"),
            "url": page_url(base_url, page),
            "version": {
                "number": version.get("number"),
                "when": version.get("when"),
            },
        },
        "objects": objects,
    }


def page_url(base_url: str, content: dict) -> str:
    link = (content.get("_links") or {}).get("webui")
    if link:
        return f"{base_url.rstrip('/')}{link}"
    return f"{base_url.rstrip('/')}/pages/{content.get('id')}"


def extract_page_id(raw: str) -> str | None:
    if not raw:
        return None
    match = re.search(r"pageId=(\d+)", raw)
    if match:
        return match.group(1)
    match = re.search(r"/pages/(\d+)", raw)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    return None


class ConfluenceService:
    def __init__(self, client: ConfluenceClient, base_url: str):
        self.client = client
        self.base_url = base_url.rstrip("/")

    def fetch_targets(
        self,
        *,
        root_page_id: str,
        is_parent: bool,
        expand: Iterable[str] | None = None,
        max_children: int | None = None,
    ) -> tuple[list[dict], list[tuple[str, str]]]:
        """Return child pages when is_parent is True; otherwise the root page."""
        failures: list[tuple[str, str]] = []
        if not is_parent:
            try:
                return [self.client.get_page(root_page_id, expand=expand)], failures
            except ConfluenceError as exc:
                failures.append((root_page_id, str(exc)))
                return [], failures

        try:
            children = self.client.get_child_pages(
                root_page_id,
                expand=expand,
                limit=max_children,
            )
            return children, failures
        except ConfluenceError as exc:
            failures.append((root_page_id, str(exc)))
            return [], failures

    def extract_section_or_macro(
        self,
        page: dict,
        *,
        section_title: str | None,
        macro_names: Iterable[str] | None,
    ) -> dict:
        """Pull section and macro blocks from a page payload."""
        storage = (
            page.get("body", {}).get("storage", {}).get("value")  # type: ignore[call-arg]
        )
        data = {
            "id": page.get("id"),
            "title": page.get("title"),
            "url": page_url(self.base_url, page),
            "section": None,
            "macros": {},
        }
        if not storage:
            return data

        if section_title:
            data["section"] = extract_heading_section(storage, section_title)

        if macro_names:
            for name in macro_names:
                if not name:
                    continue
                data["macros"][name] = extract_macro_contents(storage, name)
        return data

    def extract_page_objects(self, page: dict) -> dict:
        storage = (
            page.get("body", {}).get("storage", {}).get("value")  # type: ignore[call-arg]
        )
        if not storage:
            return {"titles": [], "tables": [], "macros": []}
        return extract_storage_objects(storage)

    def build_cache_record(self, page: dict) -> dict:
        objects = self.extract_page_objects(page)
        return build_cache_payload(page, objects, base_url=self.base_url)

    def fetch_pages_with_content(
        self,
        *,
        root_page_id: str,
        is_parent: bool,
        section_title: str | None,
        macro_names: Iterable[str] | None,
        expand: Iterable[str] | None = None,
        max_children: int | None = None,
    ) -> tuple[list[dict], list[tuple[str, str]]]:
        pages, failures = self.fetch_targets(
            root_page_id=root_page_id,
            is_parent=is_parent,
            expand=expand,
            max_children=max_children,
        )
        enriched = [
            self.extract_section_or_macro(
                page,
                section_title=section_title,
                macro_names=macro_names,
            )
            for page in pages
        ]
        return enriched, failures
