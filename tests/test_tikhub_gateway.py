from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from csl_lab.crawl import crawl_scenario
from csl_lab.crawl.merge_note import extract_note_from_detail_body, extract_notes_from_search_body
from csl_lab.crawl.tikhub_client import TikHubClient, TikHubError
from csl_lab.paths import load_scenario


def note(note_id="synthetic-note"):
    return {"id": note_id, "title": "合成标题", "desc": "完整的合成笔记内容", "time": 1700000000,
            "liked_count": 12, "comments_count": 3, "shared_count": 2, "collected_count": 5,
            "user": {"id": "synthetic-user", "nickname": "合成作者", "image": "https://example.invalid/avatar"}}


def app_body(notes=None):
    return {"code": 200, "data": {"code": 0, "success": True, "data": [{"note_list": [note()] if notes is None else notes}]}}


def envelope(body):
    return {"meta": {"ok": True, "businessStatus": "ok", "httpStatus": 200, "requestId": "synthetic-request", "queueMs": 3},
            "body": body, "cacheUrl": "https://example.invalid/cache"}


def test_missing_gateway_authorization_never_uses_legacy_provider_credentials(monkeypatch):
    monkeypatch.delenv("TIKHUB_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("TIKHUB_API_TOKEN", "synthetic-legacy-provider-key")
    with pytest.raises(TikHubError, match="GATEWAY_TOKEN"):
        TikHubClient(token="synthetic-old-key", base_url="https://api.tikhub.io", rpm=999)
    with pytest.raises(TikHubError, match="private-network"):
        TikHubClient(gateway_url="https://api.tikhub.io", gateway_token="synthetic-service-key")


def test_gateway_preserves_envelope_and_only_sends_service_token_and_reviewed_keys():
    requests = []
    expected = envelope(app_body())
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=expected)
    with TikHubClient(gateway_url="http://127.0.0.1:3000", gateway_token="synthetic-service-key", transport=httpx.MockTransport(handler)) as client:
        result = client.note_detail(note_id="synthetic-note", xsec_token="obsolete-not-sent")
        assert result["meta"] == expected["meta"]
        assert result["body"] == expected["body"]
        assert result["cacheUrl"] == expected["cacheUrl"]
        assert result["http_status"] == 200
        assert requests[0].url == "http://127.0.0.1:3000/api/internal/tikhub/request"
        assert requests[0].method == "POST"
        assert requests[0].headers["authorization"] == "Bearer synthetic-service-key"
        assert json.loads(requests[0].content) == {"endpointKey": "xhs_note_detail", "params": {"note_id": "synthetic-note"}}
        with pytest.raises(TikHubError, match="unknown endpoint"):
            client.request("https://api.tikhub.io/other", {})
        with pytest.raises(TikHubError, match="missing required"):
            client.note_detail(note_id="")
        assert len(requests) == 1


@pytest.mark.parametrize("fault", ["timeout", "500", "401", "redirect", "invalid_json", "invalid_envelope", "upstream_error"])
def test_gateway_failures_are_not_retried_or_fallen_back(fault):
    calls = []
    def handler(request):
        calls.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if fault in {"500", "401"}:
            return httpx.Response(int(fault), json={"error": "synthetic"})
        if fault == "redirect":
            return httpx.Response(302, headers={"location": "https://api.tikhub.io"})
        if fault == "invalid_json":
            return httpx.Response(200, text="not json")
        if fault == "invalid_envelope":
            return httpx.Response(200, json={"body": {}})
        return httpx.Response(200, json={"meta": {"ok": False, "businessStatus": "tikhub_error_429", "httpStatus": 429}, "body": {"code": 429}})
    with TikHubClient(gateway_token="synthetic-service-key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TikHubError):
            client.search_notes_page(keyword="synthetic")
    assert len(calls) == 1
    assert calls[0].url.host == "127.0.0.1"


def test_app_v2_detail_retains_content_metrics_author_and_selects_expected_identity():
    body = app_body([note("other-note"), note()])
    actual = extract_note_from_detail_body(body, expected_note_id="synthetic-note")
    assert actual["id"] == "synthetic-note"
    assert actual["desc"] == "完整的合成笔记内容"
    assert actual["user"]["userid"] == "synthetic-user"
    assert actual["liked_count"] == 12
    assert actual["comments_count"] == 3
    assert actual["shared_count"] == 2
    assert actual["collected_count"] == 5
    assert extract_note_from_detail_body(body, expected_note_id="missing-note") is None
    for invalid in [{"code": 500, "data": body["data"]}, {"code": 200, "data": {}}, app_body([]), app_body([{"id": "synthetic-note"}]), app_body([{"desc": "missing identity"}])]:
        assert extract_note_from_detail_body(invalid) is None
    for patch in [{"code": -1}, {"success": False}, {"ok": False}]:
        broken = app_body(); broken["data"].update(patch)
        assert extract_note_from_detail_body(broken) is None
    with pytest.raises(ValueError):
        extract_notes_from_search_body({"code": 200, "data": {"code": 500, "data": {"items": []}}})
    with pytest.raises(ValueError):
        extract_notes_from_search_body({})


def test_synthetic_crawl_gets_app_v2_details_without_xsec_and_persists_raw_meta(monkeypatch, tmp_path):
    import csl_lab.crawl as crawl
    monkeypatch.setattr(crawl, "DATA_DIR", tmp_path)
    monkeypatch.setattr(crawl, "ensure_data_dirs", lambda: None)
    calls = []
    search_body = {"code": 200, "data": {"next_page": None, "data": {"items": [{"note": {"id": "synthetic-note", "desc": "搜索摘要"}}]}}}
    detail_body = app_body()
    def handler(request):
        call = json.loads(request.content); calls.append(call)
        return httpx.Response(200, json=envelope(search_body if call["endpointKey"] == "xhs_search_notes" else detail_body))
    scenario = load_scenario("new_car", product_id="mona_l03")
    with TikHubClient(gateway_token="synthetic-service-key", transport=httpx.MockTransport(handler)) as client:
        result = crawl_scenario(scenario, client=client, keywords=["synthetic"], run_id="synthetic-gateway-run")
    assert result.detail_ok == 1 and result.detail_failed == 0
    assert result.posts[0].body_complete is True
    assert result.posts[0].body == "完整的合成笔记内容"
    assert calls == [{"endpointKey": "xhs_search_notes", "params": {"keyword": "synthetic", "page": 1}}, {"endpointKey": "xhs_note_detail", "params": {"note_id": "synthetic-note"}}]
    logs = [json.loads(line) for line in result.log_path.read_text().splitlines()]
    detail = next(row for row in logs if row["event"] == "detail_response")
    assert detail["raw_body"] == detail_body
    assert detail["meta"]["requestId"] == "synthetic-request"


def test_web_configuration_is_automatic_and_does_not_expose_or_persist_gateway_secret(monkeypatch, tmp_path):
    from csl_lab.webapp import config_store
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("TIKHUB_GATEWAY_TOKEN", "synthetic-service-secret")
    config_store.CONFIG_PATH.write_text(json.dumps({"tikhub_rpm": 3, "tikhub_api_token": "synthetic-retired-secret"}))
    public = config_store.public_config()
    assert public["tikhub_limit_mode"] == "auto"
    assert public["tikhub_gateway_configured"] is True
    assert "tikhub_rpm" not in public
    assert "synthetic-service-secret" not in json.dumps(public)
    config_store.save_config({"tikhub_rpm": 1, "tikhub_api_token": "ignored", "deepseek_model": "deepseek-v4-pro"})
    saved = json.loads(config_store.CONFIG_PATH.read_text())
    assert "tikhub_rpm" not in saved and "tikhub_api_token" not in saved and "tikhub_gateway_token" not in saved
    html = (Path(config_store.__file__).parent / "static" / "index.html").read_text()
    assert 'id="tikhub_rpm"' not in html and 'id="tikhub_token"' not in html
