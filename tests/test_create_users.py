from __future__ import annotations
"""
Pytest: batch-create users via REST (real HTTP, reads config/.env).
- 从 config/.env 读取 create_users.* 与 rest.*，真实调用接口按批创建用户。

运行：
  pytest -q -s tests/test_create_users.py
可配置（config/.env -> create_users: 块）：
  user_start, user_end(或 user_count 作为 user_end), user_prefix, user_password, user_batch, user_timeout
"""

import math
from typing import Dict, Iterable, List, Any

import pytest
import requests
from utils.config import load_yaml_config
from pathlib import Path

from apis.user_api import create_users


def _chunk(lst: List[Dict[str, str]], size: int) -> Iterable[List[Dict[str, str]]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@pytest.mark.create_users
def test_create_users_batches():
    """遵循主规范：仅读 config/.env，真实 HTTP，批量 ≤50，脱敏输出。"""
    # 读取合并配置（config/config.yaml + config/.env），.env 覆盖敏感字段
    cfg = load_yaml_config()
    rest_sec: Dict[str, Any] = cfg.get("rest", {}) if isinstance(cfg, dict) else {}
    loc: Dict[str, Any] = cfg.get("locust", {}) if isinstance(cfg, dict) else {}

    # 配置校验（SSOT 必填）
    missing = [k for k in ("rest_url", "org_name", "app_name", "authorization") if not rest_sec.get(k)]
    if missing:
        pytest.fail("config/.env 缺失字段: " + ", ".join(f"rest.{k}" for k in missing))

    # 从 locust 段读取；优先 user_*，其次非前缀键；缺失使用默认
    def pick(d: Dict[str, Any], keys, default):
        for k in keys:
            if k in d and d[k] not in (None, ""):
                return d[k]
        return default

    # 固定使用区间语义：user_start..user_end（含）
    # 兼容：若未配置 user_end，则把 user_count 当作 user_end 使用
    prefix = str(pick(loc, ["user_prefix", "prefix"], "yc"))
    start = int(pick(loc, ["user_start", "start"], 1))
    end_raw = pick(loc, ["user_end", "end"], None)
    if end_raw in (None, ""):
        end_raw = pick(loc, ["user_count", "count"], None)
    if end_raw in (None, ""):
        pytest.fail("配置错误：locust.user_end 或 locust.user_count（二者其一）必填")

    end = int(end_raw)
    if end < start:
        pytest.fail(f"配置错误：user_end({end}) 不能小于 user_start({start})")
    count = end - start + 1
    password = str(pick(loc, ["user_password", "password"], "1"))
    batch = int(pick(loc, ["user_batch", "batch"], 2))
    timeout = float(pick(loc, ["user_timeout", "timeout"], 15))

    # 目标 URL 与 Token（非敏感来自 config.yaml，敏感 Authorization 来自 .env）
    rest_url = str(rest_sec.get("rest_url"))
    org_name = str(rest_sec.get("org_name"))
    app_name = str(rest_sec.get("app_name"))
    users_path = str(rest_sec.get("users_path", "/users"))
    authorization = str(rest_sec.get("authorization"))
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
        url = f"{rest_url.rstrip('/')}/{org_name}/{app_name}{users_path}"
        # 幂等：若已存在返回 400/409，视为成功；其他错误失败
        resp: requests.Response | None = None
        req_err: Exception | None = None
        body: Any = None
        text = ""
        try:
            resp = create_users(url, authorization, group, timeout=timeout)
        except requests.HTTPError as e:
            resp = e.response
            req_err = e
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
                    f"url={url}, status={status}, err={req_err_text}, detail={msg or body_text})"
                )

        done += len(group)

    assert done == count, f"Expected to create {count}, actually {done}"
