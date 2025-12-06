import os
import re
import sys
from typing import Iterable


def env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def env_str(name: str) -> str | None:
    value = os.getenv(name)
    return value if value else None


def issue_url(base_url: str, issue_key: str) -> str:
    """Return a clickable Jira issue URL."""
    return f"{base_url.rstrip('/')}/browse/{issue_key}"


def extract_issue_key(raw: str) -> str | None:
    """Pull a Jira issue key from a key or URL."""
    if not raw:
        return None
    match = re.search(r"[A-Z][A-Z0-9]+-\d+", raw.strip(), flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def read_issue_keys(values: Iterable[str], file_path: str | None = None) -> list[str]:
    """Collect unique issue keys from CLI args, optional file, or piped stdin."""
    collected: list[str] = []
    if file_path:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                collected.extend(line.strip() for line in handle if line.strip())
        except OSError as exc:
            raise RuntimeError(f"Failed to read issue list from {file_path}: {exc}")

    collected.extend(values or [])

    if not collected and not sys.stdin.isatty():
        collected.extend(line.strip() for line in sys.stdin if line.strip())

    keys: list[str] = []
    seen: set[str] = set()
    for ref in collected:
        key = extract_issue_key(ref)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    if not keys:
        raise RuntimeError("No valid issue keys found. Provide URLs or keys.")
    return keys
