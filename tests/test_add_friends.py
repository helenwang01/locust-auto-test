from __future__ import annotations
"""
Pytest: import friends via REST (real HTTP).
- Reads rest.* from config/.env
- Imports usernames in batches (fixed max 10 each request)

Run:
  pytest -q -s -m add_friends tests/test_add_friends.py
"""

from typing import Any, Dict, Iterable, List
import pytest
import requests
from utils.config import load_yaml_config


def _pick(d: Dict[str, Any], keys: Iterable[str], default):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _headers_from_cfg(cfg: Dict[str, Any], token: str) -> Dict[str, str]:
    headers_cfg = cfg.get("headers", {}) if isinstance(cfg, dict) else {}
    accept = headers_cfg.get("accept", headers_cfg.get("Accept", None))
    content_type = headers_cfg.get("content_type", headers_cfg.get("content-type", None))
    h: Dict[str, str] = {"Authorization": token}
    if accept is not None:
        h["Accept"] = str(accept)
    if content_type is not None:
        h["Content-Type"] = str(content_type)
    return h


def _metadata_headers(rest_sec: Dict[str, Any], token: str) -> Dict[str, str]:
    # 按接口示例使用 metadata 专用请求头
    return {
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "Easemob-Org": str(rest_sec.get("metadata_org", "easemob-demo")),
        "Easemob-App": str(rest_sec.get("metadata_app", rest_sec.get("app_name", ""))),
        "Easemob-Role": str(rest_sec.get("metadata_role", "admin-user")),
    }


def _chunk(lst: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@pytest.mark.add_friends
def test_add_friends_import():
    # 读取合并配置（config/config.yaml + config/.env），.env 覆盖敏感字段
    cfg = load_yaml_config()
    rest_sec: Dict[str, Any] = cfg.get("rest", {}) if isinstance(cfg, dict) else {}
    loc: Dict[str, Any] = cfg.get("locust", {}) if isinstance(cfg, dict) else {}

    missing = [
        k
        for k in ("rest_url", "org_name", "app_name", "authorization", "friends_count", "user_prefix")
        if not rest_sec.get(k)
    ]
    if missing:
        pytest.fail("config/.env 缺失字段: " + ", ".join(f"rest.{k}" for k in missing))

    rest_url = str(rest_sec["rest_url"]).rstrip("/")
    org_name = str(rest_sec["org_name"]).strip("/")
    app_name = str(rest_sec["app_name"]).strip("/")
    users_path = str(rest_sec.get("users_path", "/users"))
    token = str(rest_sec["authorization"])  # already includes scheme, e.g., Bearer

    prefix = str(rest_sec["user_prefix"])
    count = int(rest_sec["friends_count"])
    owner = str(rest_sec.get("friends_owner", "tst00"))
    timeout = float(_pick(loc, ["user_timeout", "timeout"], 15))
    batch_size = 10

    if count <= 0:
        pytest.fail(f"配置错误：rest.friends_count 必须 > 0，当前 {count}")
    if not prefix:
        pytest.fail("配置错误：rest.user_prefix 不能为空")

    base = f"{rest_url}/{org_name}/{app_name}"
    import_url = f"{base}{users_path}/{owner}/contacts/import?isSendNotice=false"
    headers = _headers_from_cfg(cfg, token)

    usernames = [f"{prefix}{i}" for i in range(1, count + 1)]
    total_batches = (count + batch_size - 1) // batch_size
    print(
        f"[import-friends] owner={owner}, range={prefix}1..{prefix}{count}, "
        f"count={count}, batch_size={batch_size}, total_batches={total_batches}"
    )

    done = 0
    for idx, group in enumerate(_chunk(usernames, batch_size), 1):
        payload = {"usernames": group}
        print(f"[import-friends] batch {idx}/{total_batches}, size={len(group)}")
        try:
            resp = requests.post(import_url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(
                f"Request error (batch={idx}/{total_batches}, size={len(group)}, "
                f"sample={group[:3]}, url={import_url}): {e}"
            )

        ok = 200 <= resp.status_code < 300
        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None

        if not ok:
            text = (resp.text or "")
            msg = ""
            if isinstance(body, dict):
                code = body.get("code")
                message = body.get("message") or body.get("error") or body.get("desc")
                msg = f"code={code}, message={message}"
                if code in (0, 200):
                    ok = True
            if not ok and resp.status_code in (400, 409):
                low = text.lower()
                if any(k in low for k in ("exist", "duplicate", "already", "present")):
                    ok = True

        if not ok:
            snippet = (resp.text or "")[:200]
            pytest.fail(
                f"HTTP {resp.status_code} import failed "
                f"(batch={idx}/{total_batches}, size={len(group)}, sample={group[:3]}): "
                f"{msg or snippet}"
            )

        done += len(group)
        if idx % 5 == 0 or idx == total_batches:
            print(f"[import-friends] done {done}/{count}")

    assert done == count, f"Expected to import {count} friends, actually {done}"


@pytest.mark.add_friends
def test_set_user_metadata_batch():
    # 读取合并配置（config/config.yaml + config/.env），.env 覆盖敏感字段
    cfg = load_yaml_config()
    rest_sec: Dict[str, Any] = cfg.get("rest", {}) if isinstance(cfg, dict) else {}
    loc: Dict[str, Any] = cfg.get("locust", {}) if isinstance(cfg, dict) else {}

    missing = [k for k in ("rest_url", "org_name", "app_name", "authorization", "friends_count", "user_prefix") if not rest_sec.get(k)]
    if missing:
        pytest.fail("config/.env 缺失字段: " + ", ".join(f"rest.{k}" for k in missing))

    rest_url = str(rest_sec["rest_url"]).rstrip("/")
    org_name = str(rest_sec["org_name"]).strip("/")
    app_name = str(rest_sec["app_name"]).strip("/")
    token = str(rest_sec["authorization"])
    prefix = str(rest_sec["user_prefix"])
    count = int(rest_sec["friends_count"])
    timeout = float(_pick(loc, ["user_timeout", "timeout"], 15))

    if count <= 0:
        pytest.fail(f"配置错误：rest.friends_count 必须 > 0，当前 {count}")
    if not prefix:
        pytest.fail("配置错误：rest.user_prefix 不能为空")

    base = f"{rest_url}/{org_name}/{app_name}"
    headers = _metadata_headers(rest_sec, token)

    print(f"[set-metadata] range={prefix}1..{prefix}{count}, count={count}")
    done = 0
    for i in range(1, count + 1):
        username = f"{prefix}{i}"
        url = f"{base}/metadata/user/{username}?notify=false"
        form_data = {
            "aaa": f"111_{i}",
            "age": f"222_{i}",
            "ext": f"扩展信息_{i}",
        }
        try:
            resp = requests.put(url, headers=headers, data=form_data, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(f"Request error for user={username}, url={url}: {e}")

        ok = 200 <= resp.status_code < 300
        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None

        if not ok and isinstance(body, dict):
            code = body.get("code")
            if code in (0, 200):
                ok = True

        if not ok:
            snippet = (resp.text or "")[:300]
            pytest.fail(
                f"HTTP {resp.status_code} set metadata failed "
                f"(user={username}, url={url}, body={snippet})"
            )

        done += 1
        if done % 100 == 0 or done == count:
            print(f"[set-metadata] done {done}/{count}")

    assert done == count, f"Expected to set metadata for {count} users, actually {done}"


@pytest.mark.add_friends
def test_set_friend_remark_batch():
    # 读取合并配置（config/config.yaml + config/.env），.env 覆盖敏感字段
    cfg = load_yaml_config()
    rest_sec: Dict[str, Any] = cfg.get("rest", {}) if isinstance(cfg, dict) else {}
    loc: Dict[str, Any] = cfg.get("locust", {}) if isinstance(cfg, dict) else {}

    missing = [k for k in ("rest_url", "org_name", "app_name", "authorization", "friends_count", "user_prefix") if not rest_sec.get(k)]
    if missing:
        pytest.fail("config/.env 缺失字段: " + ", ".join(f"rest.{k}" for k in missing))

    rest_url = str(rest_sec["rest_url"]).rstrip("/")
    org_name = str(rest_sec["org_name"]).strip("/")
    app_name = str(rest_sec["app_name"]).strip("/")
    token = str(rest_sec["authorization"])
    prefix = str(rest_sec["user_prefix"])
    count = int(rest_sec["friends_count"])
    owner = str(rest_sec.get("friends_owner", "tst"))
    timeout = float(_pick(loc, ["user_timeout", "timeout"], 15))

    if count <= 0:
        pytest.fail(f"配置错误：rest.friends_count 必须 > 0，当前 {count}")
    if not prefix:
        pytest.fail("配置错误：rest.user_prefix 不能为空")

    base = f"{rest_url}/{org_name}/{app_name}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    print(f"[set-remark] owner={owner}, range={prefix}1..{prefix}{count}, count={count}")
    done = 0
    for i in range(1, count + 1):
        friend = f"{prefix}{i}"
        url = f"{base}/user/{owner}/contacts/users/{friend}"
        payload = {"remark": f"测试{i}"}
        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(f"Request error for owner={owner}, friend={friend}, url={url}: {e}")

        ok = 200 <= resp.status_code < 300
        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None

        if not ok and isinstance(body, dict):
            code = body.get("code")
            if code in (0, 200):
                ok = True

        if not ok:
            snippet = (resp.text or "")[:300]
            pytest.fail(
                f"HTTP {resp.status_code} set friend remark failed "
                f"(owner={owner}, friend={friend}, url={url}, body={snippet})"
            )

        done += 1
        if done % 100 == 0 or done == count:
            print(f"[set-remark] done {done}/{count}")

    assert done == count, f"Expected to set remarks for {count} friends, actually {done}"
