from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from utils.config import load_yaml_config, rest_ctx

# loadtests/longconn/locustfile_chatroom_online.py：未设置 LOCUST_CHATROOM_SCENE 时使用的场景名
DEFAULT_CHATROOM_LONGCONN_SCENE_NAME = "chatroom-online-small"


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
class DataSeedConfig:
    user_prefix: str
    user_password: str
    user_pad: int
    user_timeout_s: float
    create_users_start: int
    create_users_end: int
    create_users_batch: int
    friends_count: int
    friends_owner: str
    metadata_org: str
    metadata_app: str
    metadata_role: str
    room_id: str


@dataclass(frozen=True)
class RoomTierConfig:
    room_ratio: float
    user_target: int | None
    user_target_min: int | None
    user_target_max: int | None


@dataclass(frozen=True)
class ChatroomSceneConfig:
    name: str
    room_count: int
    room_ids: tuple[str, ...]
    room_tiers: dict[str, RoomTierConfig]
    surge_window_s: int
    surge_curve: str
    peak_target_users: int


@dataclass(frozen=True)
class ChatroomLongConnSceneConfig:
    """聊天室摸高压测场景（locustfile_chatroom_online）。并发规模由 locust -u 决定。"""

    name: str
    room_count: int
    room_ids: tuple[str, ...]
    users_per_room: int
    sender_per_room: int
    room_msg_rps: float
    send_pause_interval_s: float
    send_batch_duration_s: float
    message: str


@dataclass(frozen=True)
class LongConnScenarioConfig:
    offline_at_s: int
    offline_count: int
    online1_at_s: int
    online1_count: int
    online2_at_s: int
    online2_count: int
    message_interval_s: float
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
    rest_base_url: str
    rest_org_name: str
    rest_app_name: str
    rest_users_path: str
    chatroom_ids: tuple[str, ...]


class LoadtestConfigCenter:
    _instance: "LoadtestConfigCenter | None" = None

    def __init__(self) -> None:
        self.cfg = load_yaml_config()
        self.loc = self._require_dict(self.cfg, "locust", "locust")
        self.seed = self._require_dict(self.cfg, "data_seed", "data_seed")
        self.loc_env = self.loc
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

    def data_seed_config(self) -> DataSeedConfig:
        return DataSeedConfig(
            user_prefix=self._require_str(self.seed.get("user_prefix"), "data_seed.user_prefix"),
            user_password=self._require_str(self.seed.get("user_password"), "data_seed.user_password"),
            user_pad=self._require_int(self.seed.get("user_pad"), "data_seed.user_pad"),
            user_timeout_s=self._require_float(self.seed.get("user_timeout_s"), "data_seed.user_timeout_s"),
            create_users_start=self._require_int(self.seed.get("create_users_start"), "data_seed.create_users_start"),
            create_users_end=self._require_int(self.seed.get("create_users_end"), "data_seed.create_users_end"),
            create_users_batch=self._require_int(self.seed.get("create_users_batch"), "data_seed.create_users_batch"),
            friends_count=self._require_int(self.seed.get("friends_count"), "data_seed.friends_count"),
            friends_owner=self._require_str(self.seed.get("friends_owner"), "data_seed.friends_owner"),
            metadata_org=self._require_str(self.seed.get("metadata_org"), "data_seed.metadata_org"),
            metadata_app=self._require_str(self.seed.get("metadata_app"), "data_seed.metadata_app"),
            metadata_role=self._require_str(self.seed.get("metadata_role"), "data_seed.metadata_role"),
            room_id=self._require_str(self.seed.get("room_id"), "data_seed.room_id"),
        )

    def chatroom_scene(self, name: str = "jingqi-chatroom") -> ChatroomSceneConfig:
        scenes = self.loc.get("scenes")
        if not isinstance(scenes, list):
            raise RuntimeError("locust.scenes 缺失或类型错误，必须为数组")

        selected: dict[str, Any] | None = None
        for item in scenes:
            if not isinstance(item, dict):
                continue
            if str(item.get("name", "")).strip() == name:
                selected = item
                break
        if selected is None:
            raise RuntimeError(f"locust.scenes 中未找到场景: {name}")

        room_count = self._require_int(selected.get("room_count"), f"locust.scenes[{name}].room_count")
        seed_cfg = self.data_seed_config()
        room_ids = self._build_room_ids(seed_cfg.room_id, room_count)

        tiers_raw = selected.get("room_tiers")
        if not isinstance(tiers_raw, dict):
            raise RuntimeError(f"locust.scenes[{name}].room_tiers 缺失或类型错误，必须为字典")
        room_tiers: dict[str, RoomTierConfig] = {}
        for tier_name, tier_val in tiers_raw.items():
            if not isinstance(tier_val, dict):
                raise RuntimeError(f"locust.scenes[{name}].room_tiers.{tier_name} 类型错误，必须为字典")
            room_tiers[str(tier_name)] = RoomTierConfig(
                room_ratio=self._require_float(
                    tier_val.get("room_ratio"),
                    f"locust.scenes[{name}].room_tiers.{tier_name}.room_ratio",
                ),
                user_target=(
                    None
                    if _is_missing(tier_val.get("user_target"))
                    else self._require_int(
                        tier_val.get("user_target"),
                        f"locust.scenes[{name}].room_tiers.{tier_name}.user_target",
                    )
                ),
                user_target_min=(
                    None
                    if _is_missing(tier_val.get("user_target_min"))
                    else self._require_int(
                        tier_val.get("user_target_min"),
                        f"locust.scenes[{name}].room_tiers.{tier_name}.user_target_min",
                    )
                ),
                user_target_max=(
                    None
                    if _is_missing(tier_val.get("user_target_max"))
                    else self._require_int(
                        tier_val.get("user_target_max"),
                        f"locust.scenes[{name}].room_tiers.{tier_name}.user_target_max",
                    )
                ),
            )

        return ChatroomSceneConfig(
            name=name,
            room_count=room_count,
            room_ids=room_ids,
            room_tiers=room_tiers,
            surge_window_s=self._require_int(
                selected.get("surge_window_s"),
                f"locust.scenes[{name}].surge_window_s",
            ),
            surge_curve=self._require_str(
                selected.get("surge_curve"),
                f"locust.scenes[{name}].surge_curve",
            ),
            peak_target_users=self._require_int(
                selected.get("peak_target_users"),
                f"locust.scenes[{name}].peak_target_users",
            ),
        )

    def chatroom_longconn_scene(self, name: str | None = None) -> ChatroomLongConnSceneConfig:
        """读取聊天室摸高压测场景。

        解析顺序：参数 name → 环境变量 LOCUST_CHATROOM_SCENE → 默认 chatroom-online-small。
        """
        env_pick = str(os.environ.get("LOCUST_CHATROOM_SCENE") or "").strip()
        resolved = (name or env_pick or DEFAULT_CHATROOM_LONGCONN_SCENE_NAME).strip()

        scenes = self.loc.get("scenes")
        if not isinstance(scenes, list):
            raise RuntimeError("locust.scenes 缺失或类型错误，必须为数组")

        selected: dict[str, Any] | None = None
        for item in scenes:
            if not isinstance(item, dict):
                continue
            if str(item.get("name", "")).strip() == resolved:
                selected = item
                break
        if selected is None:
            raise RuntimeError(f"locust.scenes 中未找到聊天室压测场景: {resolved}")

        if isinstance(selected.get("room_tiers"), dict):
            raise RuntimeError(
                f"场景 {resolved!r} 含 room_tiers，属于直播分层模型；"
                "聊天室摸高压测请使用独立场景（勿指向 jingqi-chatroom）"
            )

        base = f"locust.scenes[{resolved}]"
        seed_cfg = self.data_seed_config()
        room_count = self._require_int(selected.get("room_count"), f"{base}.room_count")
        room_ids = self._build_room_ids(seed_cfg.room_id, room_count)

        msg_raw = selected.get("message")
        if _is_missing(msg_raw):
            msg_raw = self.loc.get("message")
        message = str(msg_raw).strip() if not _is_missing(msg_raw) else "chatroom-custom"

        def _opt_float(key: str, default: float) -> float:
            v = selected.get(key)
            if _is_missing(v):
                return default
            return self._as_float(v, f"{base}.{key}")

        def _opt_int(key: str, default: int) -> int:
            v = selected.get(key)
            if _is_missing(v):
                return default
            return self._require_int(v, f"{base}.{key}")

        users_per_room = _opt_int("users_per_room", 120)
        sender_per_room = _opt_int("sender_per_room", 1)
        if users_per_room < 1:
            raise RuntimeError(f"{base}.users_per_room 必须 >= 1，当前={users_per_room}")
        if sender_per_room < 1 or sender_per_room > users_per_room:
            raise RuntimeError(
                f"{base}.sender_per_room 必须在 1..users_per_room 范围内，当前={sender_per_room}, users_per_room={users_per_room}"
            )

        room_msg_rps = _opt_float("room_msg_rps", 18.0)
        if room_msg_rps <= 0:
            raise RuntimeError(f"{base}.room_msg_rps 必须 > 0，当前={room_msg_rps}")

        send_pause_interval_s = _opt_float("send_pause_interval_s", 300.0)
        if send_pause_interval_s < 0:
            raise RuntimeError(f"{base}.send_pause_interval_s 必须 >= 0，当前={send_pause_interval_s}")

        send_batch_duration_s = _opt_float("send_batch_duration_s", 30.0)
        if send_batch_duration_s <= 0:
            raise RuntimeError(f"{base}.send_batch_duration_s 必须 > 0，当前={send_batch_duration_s}")

        return ChatroomLongConnSceneConfig(
            name=resolved,
            room_count=room_count,
            room_ids=room_ids,
            users_per_room=users_per_room,
            sender_per_room=sender_per_room,
            room_msg_rps=room_msg_rps,
            send_pause_interval_s=send_pause_interval_s,
            send_batch_duration_s=send_batch_duration_s,
            message=message,
        )

    def longconn(self) -> LongConnScenarioConfig:
        seed_cfg = self.data_seed_config()
        chatroom_ids: tuple[str, ...] = tuple()
        try:
            chatroom_ids = self.chatroom_scene().room_ids
        except Exception:
            # 单聊脚本不强依赖聊天室场景，缺失时保持兼容。
            chatroom_ids = tuple()
        return LongConnScenarioConfig(
            offline_at_s=self._require_int(
                self.loc.get("singlechat_offline_at_s"),
                "locust.singlechat_offline_at_s",
            ),
            offline_count=self._require_int(
                self.loc.get("singlechat_offline_count"),
                "locust.singlechat_offline_count",
            ),
            online1_at_s=self._require_int(
                self.loc.get("singlechat_online1_at_s"),
                "locust.singlechat_online1_at_s",
            ),
            online1_count=self._require_int(
                self.loc.get("singlechat_online1_count"),
                "locust.singlechat_online1_count",
            ),
            online2_at_s=self._require_int(
                self.loc.get("singlechat_online2_at_s"),
                "locust.singlechat_online2_at_s",
            ),
            online2_count=self._require_int(
                self.loc.get("singlechat_online2_count"),
                "locust.singlechat_online2_count",
            ),
            message_interval_s=self._require_float(
                self.loc.get("singlechat_message_interval_s"),
                "locust.singlechat_message_interval_s",
            ),
            user_prefix=seed_cfg.user_prefix,
            pad=seed_cfg.user_pad,
            password=seed_cfg.user_password,
            message=self._require_str(self.loc.get("message"), "locust.message"),
            app_key=self._require_str(self.rest.app_key, "rest.app_key"),
            host=self._require_str(self.loc_env.get("host"), "locust.host"),
            port=self._require_int(self.loc_env.get("port"), "locust.port"),
            mode=self._require_str(self.loc_env.get("mode"), "locust.mode").lower(),
            use_ssl=self._require_bool(self.loc_env.get("use_ssl"), "locust.use_ssl"),
            path=self._require_str(self.loc_env.get("path"), "locust.path"),
            client_resource=self._require_str(self.loc.get("client_resource"), "locust.client_resource"),
            debug=self._require_bool(self.loc.get("debug"), "locust.debug"),
            console_log=self._require_bool(self.loc.get("console_log"), "locust.console_log"),
            token_url=self.rest.token_url(),
            token_headers=self.rest.headers(authorization=self.authorization),
            rest_base_url=self._require_str(self.rest.base, "rest.rest_url"),
            rest_org_name=self._require_str(self.rest.org, "rest.org_name"),
            rest_app_name=self._require_str(self.rest.app, "rest.app_name"),
            rest_users_path=self._require_str(self.rest.users_path_default, "rest.users_path"),
            chatroom_ids=chatroom_ids,
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

    @staticmethod
    def _build_room_ids(seed_room_id: str, room_count: int) -> tuple[str, ...]:
        if room_count <= 0:
            raise RuntimeError(f"room_count 必须大于 0，实际值={room_count}")
        val = str(seed_room_id).strip()
        if not val:
            raise RuntimeError("data_seed.room_id 不能为空")

        m = re.match(r"^(.*?)(\d+)$", val)
        if m:
            prefix = m.group(1)
            start = int(m.group(2))
            return tuple(f"{prefix}{start + i}" for i in range(room_count))

        # 未带数字后缀时，默认补 `_1.._N`。
        base = val if val.endswith("_") else f"{val}_"
        return tuple(f"{base}{i}" for i in range(1, room_count + 1))
