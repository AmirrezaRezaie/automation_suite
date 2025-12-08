from __future__ import annotations

import csv
from typing import Dict, Iterable, List


class Exporter:
    """Base exporter strategy."""

    def export(
        self,
        *,
        grouped: Dict[str, List[dict]],
        ordered_groups: Iterable[str],
    ) -> None:
        raise NotImplementedError


class TxtExporter(Exporter):
    def __init__(self, path: str, field_primary: str, field_secondary: str) -> None:
        self.path = path
        self.field_primary = field_primary
        self.field_secondary = field_secondary

    def export(
        self,
        *,
        grouped: Dict[str, List[dict]],
        ordered_groups: Iterable[str],
    ) -> None:
        lines: list[str] = []
        total = sum(len(v) for v in grouped.values())
        lines.append(f"Total issues: {total}")
        for group_name in ordered_groups:
            entries = grouped.get(group_name, [])
            if not entries:
                continue
            lines.append(f"\n{group_name}:")
            for entry in entries:
                primary_value = entry["primary_value"] or "<no value>"
                secondary_value = entry["secondary_value"] or "<no value>"
                lines.append(
                    f"- {entry['key']}: {self.field_primary}={primary_value}; "
                    f"{self.field_secondary}={secondary_value}"
                )
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))


class CsvExporter(Exporter):
    def __init__(self, path: str, field_primary: str, field_secondary: str) -> None:
        self.path = path
        self.field_primary = field_primary or "primary_field"
        self.field_secondary = field_secondary or "secondary_field"

    def export(
        self,
        *,
        grouped: Dict[str, List[dict]],
        ordered_groups: Iterable[str],
    ) -> None:
        header = ["parameter_name", "parameter_value"]
        rows: list[tuple[str, str]] = []
        for group_name in ordered_groups:
            entries = grouped.get(group_name, [])
            for entry in entries:
                rows.append(("key", entry.get("key") or ""))
                rows.append(("url", entry.get("url") or ""))
                rows.append((self.field_primary, entry["primary_value"] or ""))
                rows.append((self.field_secondary, entry["secondary_value"] or ""))
                rows.append(("group", group_name))
                rows.append(("", ""))
        with open(self.path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)


def get_exporter(
    fmt: str,
    path: str,
    *,
    field_primary: str,
    field_secondary: str,
) -> Exporter:
    fmt_lower = (fmt or "txt").lower()
    if fmt_lower == "csv":
        return CsvExporter(path, field_primary, field_secondary)
    return TxtExporter(path, field_primary, field_secondary)
