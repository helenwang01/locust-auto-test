from __future__ import annotations
"""
Pytest: import friends via REST (real HTTP).
- Reads rest.* + data_seed.*
- Imports usernames in batches (fixed max 10 each request)

Run:
  pytest -q -s -m add_friends tests/test_add_friends.py
"""

from typing import Any, Iterable, List
import pytest
import requests


def _metadata_headers(*, token: str, metadata_org: str, metadata_app: str, metadata_role: str):
    return {
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "Easemob-Org": metadata_org,
        "Easemob-App": metadata_app,
        "Easemob-Role": metadata_role,
    }


def _chunk(lst: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@pytest.mark.add_friends
def test_add_friends_import(data_seed_config, rest_client):
    users_path = rest_client.users_path

    prefix = data_seed_config.user_prefix
    count = data_seed_config.friends_count
    owner = data_seed_config.friends_owner
    timeout = data_seed_config.user_timeout_s
    batch_size = 10

    if count <= 0:
        pytest.fail(f"配置错误：data_seed.friends_count 必须 > 0，当前 {count}")
    if not prefix:
        pytest.fail("配置错误：data_seed.user_prefix 不能为空")

    import_url = f"{users_path}/{owner}/contacts/import"

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
            resp = rest_client.post(import_url, params={"isSendNotice": "false"}, json=payload, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(
                f"Request error (batch={idx}/{total_batches}, size={len(group)}, "
                f"sample={group[:3]}, url={rest_client.build_url(import_url)}): {e}"
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
def test_set_user_metadata_batch(data_seed_config, rest_client):
    prefix = data_seed_config.user_prefix
    count = data_seed_config.friends_count
    timeout = data_seed_config.user_timeout_s

    if count <= 0:
        pytest.fail(f"配置错误：data_seed.friends_count 必须 > 0，当前 {count}")
    if not prefix:
        pytest.fail("配置错误：data_seed.user_prefix 不能为空")

    headers = _metadata_headers(
        token=rest_client.authorization,
        metadata_org=data_seed_config.metadata_org,
        metadata_app=data_seed_config.metadata_app or rest_client.app_name,
        metadata_role=data_seed_config.metadata_role,
    )

    print(f"[set-metadata] range={prefix}1..{prefix}{count}, count={count}")
    done = 0
    for i in range(1, count + 1):
        username = f"{prefix}{i}"
        url = f"/metadata/user/{username}"
        form_data = {
            "aaa": f"111_{i}",
            "age": f"222_{i}",
            "ext": f"扩展信息_{i}",
        }
        try:
            resp = rest_client.put(url, params={"notify": "false"}, headers=headers, data=form_data, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(f"Request error for user={username}, url={rest_client.build_url(url)}: {e}")

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
def test_set_friend_remark_batch(data_seed_config, rest_client):
    prefix = data_seed_config.user_prefix
    count = data_seed_config.friends_count
    owner = data_seed_config.friends_owner
    timeout = data_seed_config.user_timeout_s

    if count <= 0:
        pytest.fail(f"配置错误：data_seed.friends_count 必须 > 0，当前 {count}")
    if not prefix:
        pytest.fail("配置错误：data_seed.user_prefix 不能为空")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    print(f"[set-remark] owner={owner}, range={prefix}1..{prefix}{count}, count={count}")
    done = 0
    for i in range(1, count + 1):
        friend = f"{prefix}{i}"
        url = f"/user/{owner}/contacts/users/{friend}"
        payload = {"remark": f"测试{i}"}
        try:
            resp = rest_client.put(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(f"Request error for owner={owner}, friend={friend}, url={rest_client.build_url(url)}: {e}")

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
