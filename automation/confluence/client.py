from __future__ import annotations

import contextlib
from typing import Generator, Iterable

import requests


class ConfluenceError(RuntimeError):
    """Raised when a Confluence call fails or configuration is invalid."""


class ConfluenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout: int | None = None,
    ):
        if not base_url or not username or not password:
            raise ConfluenceError(
                "CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, and CONFLUENCE_PASSWORD are required."
            )
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout or 10
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({"Accept": "application/json"})

    def connect(self) -> None:
        """Validate connectivity and credentials."""
        self._request("GET", "/rest/api/space", params={"limit": 1})

    def close(self) -> None:
        self.session.close()

    def get_page(self, page_id: str, *, expand: Iterable[str] | None = None) -> dict:
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
        return self._request("GET", f"/rest/api/content/{page_id}", params=params)

    def get_child_pages(
        self,
        parent_page_id: str,
        *,
        expand: Iterable[str] | None = None,
        limit: int | None = None,
        page_size: int = 50,
    ) -> list[dict]:
        """Fetch child pages with optional pagination cap."""
        collected: list[dict] = []
        start = 0
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
        while True:
            if limit is not None and len(collected) >= limit:
                break
            batch_size = page_size
            if limit is not None:
                batch_size = min(batch_size, limit - len(collected))
            params["limit"] = batch_size
            params["start"] = start
            data = self._request(
                "GET",
                f"/rest/api/content/{parent_page_id}/child/page",
                params=params,
            )
            entries = data.get("results", [])
            collected.extend(entries)
            next_link = (data.get("_links") or {}).get("next")
            if not next_link or not entries:
                break
            start += len(entries)
        return collected

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = self._build_url(path)
        timeout = kwargs.pop("timeout", self.timeout)
        try:
            response = self.session.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}
        except requests.HTTPError as exc:
            message = self._extract_error(response)
            raise ConfluenceError(message) from exc
        except requests.RequestException as exc:
            raise ConfluenceError(f"Confluence request failed: {exc}") from exc

    def _build_url(self, path: str) -> str:
        cleaned_path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{cleaned_path}"

    def _extract_error(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("reason")
            if message:
                return str(message)
        except ValueError:
            pass
        return f"Confluence API call failed ({response.status_code})"


@contextlib.contextmanager
def connect_confluence(settings) -> Generator[ConfluenceClient, None, None]:
    """
    Create a Confluence client with the provided settings and close it afterwards.
    """
    client = ConfluenceClient(
        base_url=settings.base_url,
        username=settings.username,
        password=settings.password,
        timeout=settings.timeout,
    )
    client.connect()
    try:
        yield client
    finally:
        with contextlib.suppress(ConfluenceError):
            client.close()
