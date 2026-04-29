from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

import requests

from .config import Config

log = logging.getLogger(__name__)


def _render_body(body_template: str, username: str, secret: str) -> str:
    t = body_template.replace("{{username}}", username).replace("{{secret}}", secret)
    return t


def _load_api_spec_from_dir(api_dir: Path, name: str = "token") -> Optional[Dict[str, Any]]:
    # try JSON then YAML
    json_path = api_dir / f"{name}.json"
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))
    yml_path = api_dir / f"{name}.yaml"
    if yml_path.exists():
        import yaml  # type: ignore
        return yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    return None


def _default_api_dir(cfg: Optional[Config] = None) -> Path:
    # precedence: cfg.run.api_dir -> cwd/apis -> repo_root/apis
    if cfg is not None and cfg.run.api_dir:
        return Path(cfg.run.api_dir)
    cwd = Path.cwd() / "apis"
    if cwd.exists():
        return cwd
    here = Path(__file__).resolve().parents[2] / "apis"
    return here


def get_token_via_rest(cfg: Config, username: str, secret: str) -> str:
    """Get token via HTTP (requests).
    Priority order:
      1) cfg.run.token_url（YAML ``run.token_url``）
      2) cfg.security.token_service -> {url}/{org_name}/{app_name}/token
      3) token_api default URL
    """
    from apis.token_api import get_token as _http_get_token
    url = cfg.run.token_url
    if not url:
        ts = getattr(cfg.security, "token_service", None)
        if ts and getattr(ts, "url", None) and getattr(ts, "org_name", None) and getattr(ts, "app_name", None):
            base = str(ts.url).rstrip('/')
            url = f"{base}/{ts.org_name}/{ts.app_name}/token"
    return _http_get_token(username, secret, url=url)


def perform_login_payload(cfg: Config, username: str, token: Optional[str]):
    """
    Build protobuf payload dict for login message.
    NOTE: This depends on the login message fields used by Easemob PB; please
    update the mapping here after providing proto definitions.
    """
    # Placeholder fields; must be aligned with actual .proto
    if token is None and cfg.security.auth == "token":
        raise RuntimeError("token is required for token auth")
    fields = {"username": username}
    if token:
        fields["token"] = token
    return fields
