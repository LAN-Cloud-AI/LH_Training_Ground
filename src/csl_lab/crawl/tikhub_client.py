from __future__ import annotations

import ipaddress
import os
from typing import Any
from urllib.parse import urlsplit

import httpx


ENDPOINTS = {
    "xhs_search_notes": {"required": ["keyword"]},
    "xhs_note_detail": {"required": ["note_id"]},
}
GATEWAY_PATH = "/api/internal/tikhub/request"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:3000"


class TikHubError(RuntimeError):
    pass


def validate_gateway_url(value: str) -> str:
    """Service credentials may only be sent to the local/internal gateway."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise TikHubError("TikHub gateway must be a local/internal HTTP origin")
    hostname = parsed.hostname.lower()
    allowed = hostname in {"localhost", "host.docker.internal", "gateway.docker.internal", "app", "crawler-launcher"}
    try:
        address = ipaddress.ip_address(hostname)
        allowed = address.is_loopback or address.is_private
    except ValueError:
        pass
    if not allowed:
        raise TikHubError("TikHub gateway must be a loopback or private-network address")
    return value.rstrip("/")


class TikHubClient:
    """Use the main service's reviewed APIs, automatic admission and retries.

    Legacy token/base_url/rpm arguments remain accepted for callers migrating
    their configuration, but never enable direct paid provider requests.
    """

    def __init__(
        self,
        *,
        gateway_url: str | None = None,
        gateway_token: str | None = None,
        timeout: float = 90.0,
        transport: httpx.BaseTransport | None = None,
        token: str | None = None,
        base_url: str | None = None,
        rpm: int | None = None,
        max_retries: int | None = None,
    ):
        self.base_url = validate_gateway_url(gateway_url or os.getenv("TIKHUB_GATEWAY_URL") or DEFAULT_GATEWAY_URL)
        self._gateway_token = gateway_token or os.getenv("TIKHUB_GATEWAY_TOKEN", "")
        if not self._gateway_token:
            raise TikHubError("TikHub 自动调用服务未授权，请配置 TIKHUB_GATEWAY_TOKEN")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False, follow_redirects=False, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TikHubClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        defn = ENDPOINTS.get(endpoint)
        if not defn:
            raise TikHubError(f"unknown endpoint: {endpoint}")
        for key in defn["required"]:
            if params.get(key) in (None, ""):
                raise TikHubError(f"missing required param: {key}")
        # The gateway owns retry/limit accounting; a client retry could duplicate
        # a billable request when the gateway's response was lost.
        try:
            response = self._client.post(
                GATEWAY_PATH,
                json={"endpointKey": endpoint, "params": {k: v for k, v in params.items() if v is not None}},
                headers={"Authorization": f"Bearer {self._gateway_token}", "Accept": "application/json"},
            )
        except httpx.RequestError as exc:
            raise TikHubError("TikHub 自动调用服务连接失败；未切换到收费直连") from exc
        if response.status_code != 200:
            raise TikHubError(f"TikHub gateway returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TikHubError("TikHub gateway returned invalid JSON") from exc
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(meta, dict) or not isinstance(payload.get("body"), dict):
            raise TikHubError("TikHub gateway returned an invalid response envelope")
        if meta.get("ok") is not True or meta.get("businessStatus") != "ok":
            raise TikHubError(f"TikHub request failed: {meta.get('errorCode') or meta.get('businessStatus') or 'unknown'}")
        # Preserve the provider body and gateway meta; additive aliases support
        # existing crawl logs without rebuilding or stripping the response.
        return {**payload, "http_status": meta.get("httpStatus"), "endpoint": endpoint, "params": params}

    def search_notes_page(self, *, keyword: str, page: int = 1) -> dict[str, Any]:
        return self.request("xhs_search_notes", {"keyword": keyword, "page": page})

    def note_detail(self, *, note_id: str, xsec_token: str | None = None) -> dict[str, Any]:
        # App V2 needs only the note identity. Old optional xsec input is ignored.
        return self.request("xhs_note_detail", {"note_id": note_id})

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
