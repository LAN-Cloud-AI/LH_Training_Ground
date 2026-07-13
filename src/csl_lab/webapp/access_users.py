from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from csl_lab.webapp.config_store import load_config

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_ACCOUNT_ID = "889e913c81be632234cb26e2b75b0b9a"
DEFAULT_TRAINING_APP_ID = "a3be7d52-c771-4f5b-9807-179abb03b386"
DEFAULT_TRAINING_POLICY_ID = "86dda392-9b3b-4e70-9517-35aef1c146ba"
DEFAULT_LAUNCHER_APP_ID = "1841ba6d-94d6-4db2-8e07-9ecad6a95bf6"
DEFAULT_LAUNCHER_POLICY_ID = "09637730-a238-4eb6-8601-497b2144c74e"
DEFAULT_TEAM_DOMAIN = "long-sky-131d.cloudflareaccess.com"


class AccessUsersError(RuntimeError):
    pass


def _settings() -> dict[str, str]:
    cfg = load_config()
    token = (
        (cfg.get("cloudflare_api_token") or "").strip()
        or os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        or os.getenv("CF_API_TOKEN", "").strip()
    )
    return {
        "token": token,
        "account_id": (
            (cfg.get("cf_access_account_id") or "").strip()
            or os.getenv("CF_ACCESS_ACCOUNT_ID", DEFAULT_ACCOUNT_ID)
        ),
        "training_app_id": (
            (cfg.get("cf_access_training_app_id") or "").strip()
            or os.getenv("CF_ACCESS_TRAINING_APP_ID", DEFAULT_TRAINING_APP_ID)
        ),
        "training_policy_id": (
            (cfg.get("cf_access_training_policy_id") or "").strip()
            or os.getenv("CF_ACCESS_TRAINING_POLICY_ID", DEFAULT_TRAINING_POLICY_ID)
        ),
        "launcher_app_id": (
            (cfg.get("cf_access_launcher_app_id") or "").strip()
            or os.getenv("CF_ACCESS_LAUNCHER_APP_ID", DEFAULT_LAUNCHER_APP_ID)
        ),
        "launcher_policy_id": (
            (cfg.get("cf_access_launcher_policy_id") or "").strip()
            or os.getenv("CF_ACCESS_LAUNCHER_POLICY_ID", DEFAULT_LAUNCHER_POLICY_ID)
        ),
        "team_domain": (
            (cfg.get("cf_access_team_domain") or "").strip()
            or os.getenv("CF_ACCESS_TEAM_DOMAIN", DEFAULT_TEAM_DOMAIN)
        ),
    }


def normalize_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        raise ValueError(f"无效邮箱：{raw!r}")
    return email


def _api(method: str, path: str, *, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.cloudflare.com/client/v4{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = {"success": False, "errors": [{"message": str(exc)}]}
        raise AccessUsersError(_format_cf_error(payload, exc.code)) from exc
    except urllib.error.URLError as exc:
        raise AccessUsersError(f"Cloudflare API 网络错误：{exc}") from exc

    if not payload.get("success"):
        raise AccessUsersError(_format_cf_error(payload))
    return payload


def _format_cf_error(payload: dict[str, Any], http_code: int | None = None) -> str:
    errors = payload.get("errors") or []
    if errors:
        parts = []
        for err in errors:
            if isinstance(err, dict):
                parts.append(str(err.get("message") or err))
            else:
                parts.append(str(err))
        msg = "; ".join(parts)
    else:
        msg = "Cloudflare API 调用失败"
    if http_code:
        return f"HTTP {http_code}: {msg}"
    return msg


def _extract_emails(include: list[Any] | None) -> list[str]:
    out: list[str] = []
    for item in include or []:
        if not isinstance(item, dict):
            continue
        email_obj = item.get("email")
        if isinstance(email_obj, dict):
            email = (email_obj.get("email") or "").strip().lower()
            if email:
                out.append(email)
        elif isinstance(email_obj, str) and email_obj.strip():
            out.append(email_obj.strip().lower())
    # 去重保序
    return list(dict.fromkeys(out))


def _emails_to_include(emails: list[str]) -> list[dict[str, Any]]:
    return [{"email": {"email": e}} for e in emails]


def _get_policy(settings: dict[str, str], app_id: str, policy_id: str) -> dict[str, Any]:
    payload = _api(
        "GET",
        f"/accounts/{settings['account_id']}/access/apps/{app_id}/policies/{policy_id}",
        token=settings["token"],
    )
    return payload.get("result") or {}


def _put_policy_emails(
    settings: dict[str, str],
    *,
    app_id: str,
    policy_id: str,
    emails: list[str],
) -> dict[str, Any]:
    current = _get_policy(settings, app_id, policy_id)
    body = {
        "name": current.get("name") or "Allow users",
        "decision": current.get("decision") or "allow",
        "precedence": current.get("precedence") or 1,
        "include": _emails_to_include(emails),
        "exclude": current.get("exclude") or [],
        "require": current.get("require") or [],
    }
    payload = _api(
        "PUT",
        f"/accounts/{settings['account_id']}/access/apps/{app_id}/policies/{policy_id}",
        token=settings["token"],
        body=body,
    )
    return payload.get("result") or {}


def _targets(settings: dict[str, str]) -> list[tuple[str, str, str]]:
    """(label, app_id, policy_id)"""
    return [
        ("training", settings["training_app_id"], settings["training_policy_id"]),
        ("launcher", settings["launcher_app_id"], settings["launcher_policy_id"]),
    ]


def access_status() -> dict[str, Any]:
    s = _settings()
    return {
        "configured": bool(s["token"]),
        "team_domain": s["team_domain"],
        "account_id": s["account_id"],
        "training_app_id": s["training_app_id"],
        "launcher_app_id": s["launcher_app_id"],
        "mfa_enroll_url": f"https://{s['team_domain']}/AddMfaDevice",
        "app_launcher_url": f"https://{s['team_domain']}/",
    }


def list_access_emails() -> dict[str, Any]:
    s = _settings()
    if not s["token"]:
        raise AccessUsersError(
            "未配置 Cloudflare API Token。请在配置页填写，或设置环境变量 CLOUDFLARE_API_TOKEN。"
        )

    by_target: dict[str, list[str]] = {}
    for label, app_id, policy_id in _targets(s):
        policy = _get_policy(s, app_id, policy_id)
        by_target[label] = _extract_emails(policy.get("include"))

    # 并集展示；训练场策略为主
    emails = list(dict.fromkeys([*by_target.get("training", []), *by_target.get("launcher", [])]))
    emails.sort()
    return {
        **access_status(),
        "emails": emails,
        "by_target": by_target,
        "count": len(emails),
    }


def add_access_email(email: str) -> dict[str, Any]:
    s = _settings()
    if not s["token"]:
        raise AccessUsersError(
            "未配置 Cloudflare API Token。请在配置页填写，或设置环境变量 CLOUDFLARE_API_TOKEN。"
        )
    email = normalize_email(email)

    for _label, app_id, policy_id in _targets(s):
        policy = _get_policy(s, app_id, policy_id)
        emails = _extract_emails(policy.get("include"))
        if email not in emails:
            emails.append(email)
            _put_policy_emails(s, app_id=app_id, policy_id=policy_id, emails=emails)

    result = list_access_emails()
    result["added"] = email
    return result


def remove_access_email(email: str) -> dict[str, Any]:
    s = _settings()
    if not s["token"]:
        raise AccessUsersError(
            "未配置 Cloudflare API Token。请在配置页填写，或设置环境变量 CLOUDFLARE_API_TOKEN。"
        )
    email = normalize_email(email)

    for _label, app_id, policy_id in _targets(s):
        policy = _get_policy(s, app_id, policy_id)
        emails = _extract_emails(policy.get("include"))
        if email in emails:
            if len(emails) <= 1:
                raise AccessUsersError("至少保留一个允许邮箱，避免把自己锁在门外。")
            emails = [e for e in emails if e != email]
            _put_policy_emails(s, app_id=app_id, policy_id=policy_id, emails=emails)

    result = list_access_emails()
    result["removed"] = email
    return result
