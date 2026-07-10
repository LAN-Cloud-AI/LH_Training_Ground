from __future__ import annotations

import time
from typing import Any

import httpx


ENDPOINTS = {
    "xhs_search_notes": {
        "method": "GET",
        "path": "/api/v1/xiaohongshu/app_v2/search_notes",
        "required": ["keyword"],
    },
    "xhs_note_detail": {
        "method": "GET",
        "path": "/api/v1/xiaohongshu/web_v3/fetch_note_detail",
        "required": ["note_id", "xsec_token"],
    },
}

# Transient network failures common on macOS when system proxy (e.g. 7897) is flaky.
_RETRYABLE = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


class TikHubError(RuntimeError):
    pass


class TikHubClient:
    """Thin TikHub HTTP client for lab crawl (search + note detail)."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.tikhub.io",
        rpm: int = 20,
        timeout: float = 45.0,
        max_retries: int = 3,
    ):
        if not token:
            raise TikHubError("TIKHUB_API_TOKEN is empty")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.min_interval = 60.0 / max(1, rpm)
        self._last_call = 0.0
        self.max_retries = max(1, int(max_retries))
        # trust_env=False: ignore HTTP(S)_PROXY / macOS proxy env that often
        # breaks SSL handshake to api.tikhub.io via local clash ports.
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TikHubClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()

    def request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        defn = ENDPOINTS.get(endpoint)
        if not defn:
            raise TikHubError(f"unknown endpoint: {endpoint}")
        for key in defn["required"]:
            if params.get(key) in (None, ""):
                raise TikHubError(f"missing required param: {key}")

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(
                    defn["path"],
                    params={k: v for k, v in params.items() if v is not None},
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                return {
                    "http_status": response.status_code,
                    "body": response.json(),
                    "endpoint": endpoint,
                    "params": params,
                }
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(2.0 * attempt, 6.0))
        assert last_exc is not None
        raise last_exc

    def search_notes_page(self, *, keyword: str, page: int = 1) -> dict[str, Any]:
        return self.request("xhs_search_notes", {"keyword": keyword, "page": page})

    def note_detail(self, *, note_id: str, xsec_token: str) -> dict[str, Any]:
        return self.request(
            "xhs_note_detail",
            {"note_id": note_id, "xsec_token": xsec_token},
        )

    @staticmethod
    def next_search_page(body: dict[str, Any] | None) -> int | None:
        if not body:
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        next_page = data.get("next_page")
        if next_page in (None, "", 0, "0", False):
            return None
        try:
            return int(next_page)
        except (TypeError, ValueError):
            return None
