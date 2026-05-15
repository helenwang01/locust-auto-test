from __future__ import annotations
"""
Pytest: batch-create users via REST (real HTTP).
- 从 data_seed + rest 读取配置，真实调用接口按批创建用户。

运行：
  pytest -q -s tests/test_create_users.py
关键配置：
  data_seed.create_users_start / create_users_end / create_users_batch
  data_seed.user_prefix / user_password / user_timeout_s
"""

import math
from typing import Dict, Iterable, List, Any

import pytest
import requests

def _chunk(lst: List[Dict[str, str]], size: int) -> Iterable[List[Dict[str, str]]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@pytest.mark.create_users
def test_create_users_batches(config_center, data_seed_config, rest_client):
    """遵循主规范：仅读 config/.env，真实 HTTP，批量 ≤50，脱敏输出。"""
    del config_center

    prefix = data_seed_config.user_prefix
    start = data_seed_config.create_users_start
    end = data_seed_config.create_users_end
    if end < start:
        pytest.fail(f"配置错误：user_end({end}) 不能小于 user_start({start})")
    count = end - start + 1
    password = data_seed_config.user_password
    batch = data_seed_config.create_users_batch
    timeout = data_seed_config.user_timeout_s

    # 目标 URL 与 Token（非敏感来自 config.yaml，敏感 Authorization 来自 .env）
    users_path = rest_client.users_path
    assert 1 <= batch <= 50, "CREATE_USERS_BATCH 必须在 1..50 之间"

    users: List[Dict[str, str]] = [
        {"username": f"{prefix}{i}", "password": password}
        for i in range(start, start + count)
    ]

    total_batches = math.ceil(count / batch)
    print(f"[create-users] range={prefix}{start}..{prefix}{end}, count={count}, batch={batch}, total_batches={total_batches}")

    done = 0
    for idx, group in enumerate(_chunk(users, batch), 1):
        print(f"[create-users] batch {idx}/{total_batches}, size={len(group)}")
        url = users_path
        # 幂等：若已存在返回 400/409，视为成功；其他错误失败
        resp: requests.Response | None = None
        req_err: Exception | None = None
        body: Any = None
        text = ""
        try:
            resp = rest_client.post(url, json=list(group), timeout=timeout)
        except Exception as e:
            req_err = e

        try:
            body = resp.json() if resp is not None else None
        except Exception:
            body = None
        text = (resp.text or "") if resp is not None else ""

        success = resp is not None and (200 <= resp.status_code < 300)

        if not success:
            msg = ""
            if isinstance(body, dict):
                # 兼容常见字段：code/message/error/desc
                code = body.get("code")
                message = body.get("message") or body.get("error") or body.get("desc")
                msg = f"code={code}, message={message}"
                # 0/200 视为成功
                if code in (0, 200):
                    success = True
            if not success and resp is not None and resp.status_code in (400, 409):
                # 文本包含 exist/duplicate 视为幂等成功
                low = (text or "").lower()
                if "exist" in low or "duplicate" in low:
                    success = True
            if not success:
                status = resp.status_code if resp is not None else "NO_RESPONSE"
                body_text = text[:1000] if text else ""
                req_sample = [u.get("username") for u in group[:3]]
                req_err_text = f"{type(req_err).__name__}: {req_err}" if req_err is not None else "-"
                pytest.fail(
                    "create_users failed "
                    f"(batch={idx}/{total_batches}, size={len(group)}, sample_users={req_sample}, "
                    f"url={rest_client.build_url(url)}, status={status}, err={req_err_text}, detail={msg or body_text})"
                )

        done += len(group)

    assert done == count, f"Expected to create {count}, actually {done}"
