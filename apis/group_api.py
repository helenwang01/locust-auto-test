from __future__ import annotations
"""
Group management API helper.

Create chat groups through Easemob REST:
POST /{org}/{app}/chatgroups
"""

from typing import Any, Dict

import requests

from utils.config import rest_ctx


def create_group(
    payload: Dict[str, Any],
    authorization: str,
    *,
    timeout: float = 15.0,
) -> requests.Response:
    ctx = rest_ctx()
    url = f"{ctx.base}/{ctx.org}/{ctx.app}/chatgroups"
    headers = ctx.headers(authorization=authorization)
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp
