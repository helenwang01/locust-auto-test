from __future__ import annotations
"""
User batch-creation API helper.

URL/Headers：通过 ``utils.config.rest_ctx()`` 构建（如：``rest_ctx().users_url()``、``rest_ctx().headers(authorization=...)``）。
"""

from typing import Any, Dict, Iterable

import requests

from utils.config import rest_ctx


def create_users(
    url: str,
    token: str,
    users: Iterable[Dict[str, Any]],
    *,
    timeout: float = 10.0,
) -> requests.Response:
    headers = rest_ctx().headers(authorization=token)
    resp = requests.post(url, headers=headers, json=list(users), timeout=timeout)
    resp.raise_for_status()
    return resp
