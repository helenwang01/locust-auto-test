from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from utils.config import RestCtx, rest_ctx


def _require_str(v: Optional[str], path: str) -> str:
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"{path} 缺失，且不允许默认值")
    return str(v)


@dataclass(frozen=True)
class RestClient:
    ctx: RestCtx
    authorization: str

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]] = None) -> "RestClient":
        ctx = rest_ctx(cfg)
        auth = _require_str(ctx.authorization, "rest.authorization")
        return cls(ctx=ctx, authorization=auth)

    @property
    def base_app_url(self) -> str:
        return f"{self.ctx.base}/{self.ctx.org}/{self.ctx.app}"

    @property
    def users_path(self) -> str:
        return self.ctx.users_path_default or "/users"

    @property
    def app_name(self) -> str:
        return self.ctx.app

    @property
    def org_name(self) -> str:
        return self.ctx.org

    def token_url(self) -> str:
        return self.ctx.token_url()

    def users_url(self) -> str:
        return self.ctx.users_url()

    def headers(self, *, authorization: Optional[str] = None) -> Dict[str, str]:
        auth = self.authorization if authorization is None else authorization
        return self.ctx.headers(authorization=auth)

    def build_url(self, biz_url: str) -> str:
        path = str(biz_url or "").strip()
        if not path:
            raise RuntimeError("biz_url 不能为空")
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_app_url}{path}"

    def request(
        self,
        method: str,
        biz_url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        authorization: Optional[str] = None,
        timeout: float = 10.0,
    ) -> requests.Response:
        url = self.build_url(biz_url)
        merged_headers = self.headers(authorization=authorization)
        if headers:
            merged_headers.update(headers)
        return requests.request(
            method=method.upper(),
            url=url,
            params=params,
            json=json,
            data=data,
            headers=merged_headers,
            timeout=timeout,
        )

    def get(self, biz_url: str, **kwargs) -> requests.Response:
        return self.request("GET", biz_url, **kwargs)

    def post(self, biz_url: str, **kwargs) -> requests.Response:
        return self.request("POST", biz_url, **kwargs)

    def put(self, biz_url: str, **kwargs) -> requests.Response:
        return self.request("PUT", biz_url, **kwargs)
