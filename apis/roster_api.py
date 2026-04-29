from __future__ import annotations
"""
Minimal roster (friend) management helpers using Easemob REST.

Endpoints (management token required):
  POST /{org}/{app}/users/{owner}/contacts/users/{friend}
"""

from typing import Optional
import requests

from utils.config import rest_ctx


def _base_url() -> str:
    ctx = rest_ctx()
    return f"{ctx.base}/{ctx.org}/{ctx.app}"


def add_friend(
    owner: str,
    friend: str,
    *,
    authorization: Optional[str] = None,
    timeout: float = 10.0,
) -> None:
    base = _base_url()
    url = f"{base}/users/{owner}/contacts/users/{friend}"
    headers = rest_ctx().headers(authorization=authorization)
    resp = requests.post(url, headers=headers, timeout=timeout)
    # 200/201 OK; 409 already exists; 4xx/5xx raise
    if resp.status_code in (200, 201, 409):
        return
    resp.raise_for_status()
