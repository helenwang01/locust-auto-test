from __future__ import annotations
import requests
from typing import Any, Optional, Dict

from utils.config import rest_ctx


def get_token(
    username: str,
    secret: str,
    *,
    url: Optional[str] = None,
    ttl: int = 6000000,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    session: Any = None,
) -> str:
    """
    获取用户登录 Token。

    - 若传入 ``url`` 则使用之，否则从配置推导 ``{rest_url}/{org}/{app}/token``。
    - Header：默认使用 ``config.headers`` 的 Accept/Content-Type，并自动注入
      ``rest.authorization``（如果存在）。外部传入 ``headers`` 则按来者为准。
    - Body：``grant_type=password``，携带 ``username``/``password``/``ttl``。
    - 返回响应 JSON 的 ``access_token`` 字段。
    """
    target = url
    hdrs = headers
    if target is None or hdrs is None:
        ctx = rest_ctx()
        if target is None:
            target = ctx.token_url()
        if hdrs is None:
            hdrs = ctx.headers()

    body = {
        "grant_type": "password",
        "username": username,
        "password": secret,
        "ttl": ttl,
    }

    if session is not None:
        resp = session.post(target, headers=hdrs, json=body, timeout=timeout)
    else:
        resp = requests.post(target, headers=hdrs, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("token missing or invalid in response")
    return token
