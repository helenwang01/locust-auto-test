from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.config import load_yaml_config, rest_ctx


def _is_missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


@dataclass(frozen=True)
class SpeechHttpConfig:
    base_url: str
    org: str
    app: str
    headers: dict[str, str]
    username: str
    file_id: str
    target_qps: float | None


@dataclass(frozen=True)
class LongConnScenarioConfig:
    total_users: int
    offline_at_s: int
    offline_count: int
    online1_at_s: int
    online1_count: int
    online2_at_s: int
    online2_count: int
    duration_s: int
    message_interval_s: float
    spawn_rate: int
    user_prefix: str
    pad: int
    password: str
    message: str
    app_key: str
    host: str
    port: int
    mode: str
    use_ssl: bool
    path: str
    client_resource: str
    debug: bool
    console_log: bool
    token_url: str
    token_headers: dict[str, str]


class LoadtestConfigCenter:
    _instance: "LoadtestConfigCenter | None" = None

    def __init__(self) -> None:
        self.cfg = load_yaml_config()
        self.loc = self._require_dict(self.cfg, "locust", "locust")
        self.rest = rest_ctx(self.cfg)
        self.authorization = self._require_str(self.rest.authorization, "rest.authorization")

    @classmethod
    def get(cls) -> "LoadtestConfigCenter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def speech_http(self) -> SpeechHttpConfig:
        qps_val = self.loc.get("speech_target_qps")
        target_qps = None if _is_missing(qps_val) else self._as_float(qps_val, "locust.speech_target_qps")
        return SpeechHttpConfig(
            base_url=self._require_str(self.rest.base, "rest.rest_url"),
            org=self._require_str(self.rest.org, "rest.org_name"),
            app=self._require_str(self.rest.app, "rest.app_name"),
            headers=self.rest.headers(authorization=self.authorization),
            username=self._require_str(self.loc.get("speech_username"), "locust.speech_username"),
            file_id=self._require_str(self.loc.get("speech_file_id"), "locust.speech_file_id"),
            target_qps=target_qps,
        )

    def longconn(self) -> LongConnScenarioConfig:
        return LongConnScenarioConfig(
            total_users=self._require_int(self.loc.get("singlechat_total_users"), "locust.singlechat_total_users"),
            offline_at_s=self._require_int(self.loc.get("singlechat_offline_at_s"), "locust.singlechat_offline_at_s"),
            offline_count=self._require_int(self.loc.get("singlechat_offline_count"), "locust.singlechat_offline_count"),
            online1_at_s=self._require_int(self.loc.get("singlechat_online1_at_s"), "locust.singlechat_online1_at_s"),
            online1_count=self._require_int(self.loc.get("singlechat_online1_count"), "locust.singlechat_online1_count"),
            online2_at_s=self._require_int(self.loc.get("singlechat_online2_at_s"), "locust.singlechat_online2_at_s"),
            online2_count=self._require_int(self.loc.get("singlechat_online2_count"), "locust.singlechat_online2_count"),
            duration_s=self._require_int(self.loc.get("singlechat_duration_s"), "locust.singlechat_duration_s"),
            message_interval_s=self._require_float(
                self.loc.get("singlechat_message_interval_s"), "locust.singlechat_message_interval_s"
            ),
            spawn_rate=self._require_int(self.loc.get("singlechat_spawn_rate"), "locust.singlechat_spawn_rate"),
            user_prefix=self._require_str(self.loc.get("user_prefix"), "locust.user_prefix"),
            pad=self._require_int(self.loc.get("pad"), "locust.pad"),
            password=self._require_str(self.loc.get("user_password"), "locust.user_password"),
            message=self._require_str(self.loc.get("message"), "locust.message"),
            app_key=self._require_str(self.rest.app_key, "rest.app_key"),
            host=self._require_str(self.loc.get("host"), "locust.host"),
            port=self._require_int(self.loc.get("port"), "locust.port"),
            mode=self._require_str(self.loc.get("mode"), "locust.mode").lower(),
            use_ssl=self._require_bool(self.loc.get("use_ssl"), "locust.use_ssl"),
            path=self._require_str(self.loc.get("path"), "locust.path"),
            client_resource=self._require_str(self.loc.get("client_resource"), "locust.client_resource"),
            debug=self._require_bool(self.loc.get("debug"), "locust.debug"),
            console_log=self._require_bool(self.loc.get("console_log"), "locust.console_log"),
            token_url=self.rest.token_url(),
            token_headers=self.rest.headers(authorization=self.authorization),
        )

    @staticmethod
    def _require_dict(root: dict[str, Any], key: str, path: str) -> dict[str, Any]:
        v = root.get(key)
        if not isinstance(v, dict):
            raise RuntimeError(f"{path} 缺失或类型错误，必须为字典")
        return v

    @staticmethod
    def _require_str(v: Any, path: str) -> str:
        if _is_missing(v):
            raise RuntimeError(f"{path} 缺失，且不允许默认值")
        return str(v)

    @staticmethod
    def _as_int(v: Any, path: str) -> int:
        try:
            return int(v)
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"{path} 类型错误，期望 int，实际值={v!r}") from e

    @staticmethod
    def _as_float(v: Any, path: str) -> float:
        try:
            return float(v)
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"{path} 类型错误，期望 float，实际值={v!r}") from e

    @classmethod
    def _require_int(cls, v: Any, path: str) -> int:
        if _is_missing(v):
            raise RuntimeError(f"{path} 缺失，且不允许默认值")
        return cls._as_int(v, path)

    @classmethod
    def _require_float(cls, v: Any, path: str) -> float:
        if _is_missing(v):
            raise RuntimeError(f"{path} 缺失，且不允许默认值")
        return cls._as_float(v, path)

    @staticmethod
    def _require_bool(v: Any, path: str) -> bool:
        if _is_missing(v):
            raise RuntimeError(f"{path} 缺失，且不允许默认值")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            low = v.lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off"):
                return False
        raise RuntimeError(f"{path} 类型错误，期望 bool，实际值={v!r}")
