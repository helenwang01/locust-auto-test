from __future__ import annotations
"""
Config loader that merges non-sensitive defaults from `config/config.yaml`
with sensitive overrides from `config/.env` (YAML). This keeps secrets out of
the repo-wide YAML while preserving a single read path for callers.

Usage:
  from utils.config import load_yaml_config
  cfg = load_yaml_config()  # dict with sections: rest, headers, locust, ...

Rules:
- `config/config.yaml` holds business defaults and non-sensitive fields.
- `config/.env` holds only sensitive values (e.g., tokens) and may also set
  section keys; values in `.env` override those from `config.yaml`.
- No environment-variable overrides; no parent directory search.
"""

from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def _parse_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not text.strip():
        return {}
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    # naive fallback parser (supports one-level nested maps)
    out: Dict[str, Any] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith(" ") and not line.startswith("\t") and line.endswith(":"):
            current = line.strip().rstrip(":").strip()
            out.setdefault(current, {})
            continue
        if current and (line.startswith(" ") or line.startswith("\t")) and ":" in line:
            k, v = line.split(":", 1)
            k = k.strip(); v = v.strip()
            if isinstance(out.get(current), dict):
                out[current][k] = v
    return out


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out: Dict[str, Any] = {k: v for k, v in base.items()}
        for key, value in override.items():
            out[key] = _deep_merge(out.get(key), value) if key in out else value
        return out
    return override


def _resolve_paths(path: Optional[Path]) -> tuple[Path, Path]:
    if path is None:
        root = Path(__file__).resolve().parents[1] / "config"
        return root / "config.yaml", root / ".env"
    p = Path(path)
    if p.is_dir():
        return p / "config.yaml", p / ".env"
    return p, p.parent / ".env"


def _selected_env(cfg: Dict[str, Any]) -> Optional[str]:
    candidate = cfg.get("active_env")
    if isinstance(candidate, str):
        name = candidate.strip()
        return name or None
    return None


def _resolve_env_section(section_name: str, section: Any, env_name: Optional[str]) -> Any:
    if not isinstance(section, dict):
        raise RuntimeError(
            f"`{section_name}` 配置必须为字典，且按环境分组。"
        )

    if not env_name:
        raise RuntimeError(
            f"config.active_env 不能为空：检测到 `{section_name}` 使用多环境配置，请在 config/config.yaml 设置 active_env。"
        )

    base: Dict[str, Any] = {}
    if isinstance(section.get("default"), dict):
        base = _deep_merge(base, section["default"])
    elif isinstance(section.get("common"), dict):
        base = _deep_merge(base, section["common"])

    # keep non-dict top-level fields (e.g., rest.authorization from .env)
    # as shared values for every environment-specific section.
    shared: Dict[str, Any] = {}
    for key, value in section.items():
        if isinstance(value, dict):
            continue
        if key in ("active_env", "env", "environment", "default_env"):
            continue
        shared[key] = value

    chosen = section.get(env_name)
    if isinstance(chosen, dict):
        return _deep_merge(_deep_merge(base, shared), chosen)

    envs = section.get("environments")
    if isinstance(envs, dict) and isinstance(envs.get(env_name), dict):
        return _deep_merge(_deep_merge(base, shared), envs[env_name])

    raise RuntimeError(
        f"config.active_env={env_name!r} 在 `{section_name}` 中不存在，且不再支持平铺单环境配置。"
    )


def load_yaml_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load merged config from `config/config.yaml` + `config/.env`.

    - No env overrides; no ancestor search.
    - `.env` values override `config.yaml`.
    - Uses top-level `active_env` to select `rest`/`locust` environment blocks.
    - Flat single-env `rest`/`locust` is no longer supported.
    - `path` may point to a config directory or `config.yaml` file.
    """
    base_path, env_path = _resolve_paths(path)
    base = _parse_yaml(base_path)
    secret = _parse_yaml(env_path)
    merged_raw = _deep_merge(base, secret)
    merged: Dict[str, Any] = merged_raw if isinstance(merged_raw, dict) else {}

    env_name = _selected_env(merged)
    for sec in ("rest", "locust"):
        if sec not in merged:
            raise RuntimeError(f"config 中缺少 `{sec}` 段配置。")
        merged[sec] = _resolve_env_section(sec, merged.get(sec), env_name)
    return merged


# ---------- Aggregated REST context (replace utils.rest_config) ----------

@dataclass(frozen=True)
class RestCtx:
    base: str
    org: str
    app: str
    app_key: Optional[str]
    authorization: Optional[str]
    accept: str
    content_type: str
    users_path_default: str = "/users"

    def token_url(self) -> str:
        return f"{self.base}/{self.org}/{self.app}/token"

    def users_url(self, users_path: Optional[str] = None) -> str:
        path = users_path or self.users_path_default or "/users"
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base}/{self.org}/{self.app}{path}"

    def headers(self, *, authorization: Optional[str] = None) -> Dict[str, str]:
        hdrs: Dict[str, str] = {
            "Accept": self.accept or "application/json",
            "Content-Type": self.content_type or "application/json",
        }
        auth = authorization if authorization is not None else self.authorization
        if auth:
            hdrs["Authorization"] = str(auth)
        return hdrs


def rest_ctx(
    cfg: Optional[Dict[str, Any]] = None,
    *,
    path: Optional[Path] = None,
) -> RestCtx:
    """Build a cohesive REST context from merged config.
    - Reads rest.*, headers.*
    - Provides token/users URLs与 headers 组装，不再散落多个小函数。
    """
    cfg = cfg or load_yaml_config(path=path)
    rest = cfg.get("rest", {}) if isinstance(cfg, dict) else {}
    headers = cfg.get("headers", {}) if isinstance(cfg, dict) else {}

    base = str(rest.get("rest_url") or rest.get("url") or "").rstrip("/")
    if not base:
        raise RuntimeError("config 中 rest.rest_url（或 rest.url）不能为空")
    org = str(rest.get("org_name") or "").strip("/")
    app = str(rest.get("app_name") or "").strip("/")
    if not org or not app:
        raise RuntimeError("config 中 rest.org_name、rest.app_name 不能为空")

    return RestCtx(
        base=base,
        org=org,
        app=app,
        app_key=str(rest.get("app_key") or "") or None,
        authorization=rest.get("authorization"),
        accept=headers.get("accept", "application/json"),
        content_type=headers.get("content_type", headers.get("content-type", "application/json")),
        users_path_default=str(rest.get("users_path", "/users")),
    )
