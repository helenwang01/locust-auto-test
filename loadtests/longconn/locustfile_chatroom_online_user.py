from __future__ import annotations

import json
import queue
import random
import re
import string
import sys
import threading
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Optional, TypedDict

from gevent import sleep as gevent_sleep
from locust import User, events, task

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from apis.token_api import get_token as http_get_token
from loadtests.common.config_center import LoadtestConfigCenter
from loadtests.common.locust_runtime import require_cli_num_users
from utils.msync_client import MsyncClient


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--room-count", type=int, default=None, help="聊天室数量；不传则读取 locust.scenes 默认值")
    parser.add_argument("--users-per-room", type=int, default=None, help="每个聊天室在线人数；不传则读取场景默认值")
    parser.add_argument("--sender-per-room", type=int, default=None, help="每个聊天室发送者人数；不传则读取场景默认值")
    parser.add_argument("--room-msg-rps", type=float, default=None, help="每个聊天室目标发送速率（条/秒）；不传则读取场景默认值")
    parser.add_argument("--send-pause-interval-s", type=float, default=None, help="每批发送后的静默时长（秒）；不传则读取场景默认值，默认 300 秒")
    parser.add_argument("--send-batch-duration-s", type=float, default=None, help="每批连续发送时长（秒）；不传则读取场景默认值，默认 30 秒")
    parser.add_argument("--chatroom-message", type=str, default="", help="聊天室消息正文，空则使用 config 中默认")
    parser.add_argument("--enable-receive-metrics", action="store_true", help="开启下行收包解析指标；默认关闭以减少压测机开销")
    parser.add_argument("--enable-ack-metrics", action="store_true", help="开启 send_to_ack 指标；默认关闭以减少压测机开销")


_CENTER = LoadtestConfigCenter.get()
_SEED = _CENTER.data_seed_config()


@dataclass(frozen=True)
class ChatroomScenarioConfig:
    room_count: int
    users_per_room: int
    sender_per_room: int
    room_msg_rps: float
    task_interval_s: float
    send_pause_interval_s: float
    send_batch_duration_s: float
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
    chatroom_ids: tuple[str, ...]
    enable_receive_metrics: bool
    enable_ack_metrics: bool


@dataclass(frozen=True)
class ChatroomCustomPayloadTemplate:
    prefix: str
    suffix: str

    @classmethod
    def build(cls, *, room_id: str, sender: str, body: str) -> "ChatroomCustomPayloadTemplate":
        body_json = json.dumps(str(body), ensure_ascii=True, separators=(",", ":"))
        prefix = (
            '{"type":"chatroom_custom","room_id":'
            + json.dumps(str(room_id), ensure_ascii=True, separators=(",", ":"))
            + ',"sender":'
            + json.dumps(str(sender), ensure_ascii=True, separators=(",", ":"))
            + ',"seq":'
        )
        suffix = ',"ts_ms":' + 'TS_PLACEHOLDER' + ',"body":' + body_json + "}"
        return cls(prefix=prefix, suffix=suffix)

    def render(self, *, seq: int, ts_ms: int) -> str:
        return self.prefix + str(seq) + self.suffix.replace("TS_PLACEHOLDER", str(ts_ms), 1)


@dataclass(frozen=True)
class BurstWindow:
    cycle_index: int
    cycle_start_mono: float
    window_start_mono: float
    window_end_mono: float
    active: bool


class ConnectKwargs(TypedDict):
    ip: str
    port: int
    transport: str
    use_ssl: bool


_USER_COUNTER = count(1)
_ONLINE_USERS: set[str] = set()
_ONLINE_USERS_SNAPSHOT: tuple[str, ...] = ()
_ONLINE_USERS_LOCK = threading.Lock()
_JOINED_USERS: set[str] = set()
_JOINED_USERS_LOCK = threading.Lock()
_SEND_WINDOW_STARTED_AT_MONO: float | None = None
_SEND_WINDOW_STARTED_AT_LOCK = threading.Lock()
_SEND_WINDOW_START_LOGGED = False
_SEND_WINDOW_START_LOGGED_LOCK = threading.Lock()
_ONLINE_USERS_READY_REPORTED = False
_ONLINE_USERS_READY_LOCK = threading.Lock()
_CONNECT_RETRY_COOLDOWN_S = 1.0
_SCENARIO_CACHE: ChatroomScenarioConfig | None = None
_SCENARIO_CACHE_LOCK = threading.Lock()


def _fmt_user(prefix: str, idx: int, pad: int) -> str:
    if pad > 0:
        return f"{prefix}{idx:0{pad}d}"
    return f"{prefix}{idx}"


def _mask_token(token: Optional[str]) -> str:
    if not token:
        return "<empty>"
    if len(token) <= 12:
        return f"{token[:2]}***{token[-2:]}(len={len(token)})"
    return f"{token[:6]}...{token[-6:]}(len={len(token)})"


def _refresh_online_users_snapshot_locked() -> None:
    global _ONLINE_USERS_SNAPSHOT
    _ONLINE_USERS_SNAPSHOT = tuple(_ONLINE_USERS)


def _mark_online_users_ready_reported() -> bool:
    global _ONLINE_USERS_READY_REPORTED
    with _ONLINE_USERS_READY_LOCK:
        if _ONLINE_USERS_READY_REPORTED:
            return False
        _ONLINE_USERS_READY_REPORTED = True
        return True


def _mark_send_window_start_logged() -> bool:
    global _SEND_WINDOW_START_LOGGED
    with _SEND_WINDOW_START_LOGGED_LOCK:
        if _SEND_WINDOW_START_LOGGED:
            return False
        _SEND_WINDOW_START_LOGGED = True
        return True


def _build_room_ids(seed_room_id: str, room_count: int) -> tuple[str, ...]:
    m = re.match(r"^(.*?)(\d+)$", seed_room_id.strip())
    if m:
        prefix = m.group(1)
        start = int(m.group(2))
        return tuple(f"{prefix}{start + i}" for i in range(room_count))
    base = seed_room_id if seed_room_id.endswith("_") else f"{seed_room_id}_"
    return tuple(f"{base}{i}" for i in range(1, room_count + 1))


def resolve_sender_task_interval_s(*, room_msg_rps: float) -> float:
    return 1.0 / float(room_msg_rps)


def calculate_target_send_rps(*, room_count: int, room_msg_rps: float) -> float:
    return float(room_count) * float(room_msg_rps)


def is_in_send_window(*, now_mono: float, started_at_mono: float, batch_duration_s: float, pause_interval_s: float) -> bool:
    cycle_s = float(batch_duration_s) + float(pause_interval_s)
    if cycle_s <= 0:
        return True
    elapsed_s = max(0.0, float(now_mono) - float(started_at_mono))
    return (elapsed_s % cycle_s) < float(batch_duration_s)


def resolve_burst_window(
    *,
    now_mono: float,
    started_at_mono: float,
    batch_duration_s: float,
    pause_interval_s: float,
) -> BurstWindow:
    cycle_s = float(batch_duration_s) + float(pause_interval_s)
    if cycle_s <= 0:
        return BurstWindow(
            cycle_index=0,
            cycle_start_mono=float(started_at_mono),
            window_start_mono=float(started_at_mono),
            window_end_mono=float(started_at_mono) + float(batch_duration_s),
            active=True,
        )

    elapsed_s = max(0.0, float(now_mono) - float(started_at_mono))
    cycle_index = int(elapsed_s // cycle_s)
    cycle_start_mono = float(started_at_mono) + (cycle_index * cycle_s)
    window_start_mono = cycle_start_mono
    window_end_mono = cycle_start_mono + float(batch_duration_s)
    active = float(now_mono) < window_end_mono
    return BurstWindow(
        cycle_index=cycle_index,
        cycle_start_mono=cycle_start_mono,
        window_start_mono=window_start_mono,
        window_end_mono=window_end_mono,
        active=active,
    )


def plan_next_send_time(
    *,
    now_mono: float,
    next_send_at_mono: float | None,
    interval_s: float,
) -> tuple[float, float]:
    send_at_mono = float(now_mono)
    next_scheduled_at_mono = next_send_at_mono
    if next_scheduled_at_mono is None:
        return send_at_mono, send_at_mono + float(interval_s)

    if next_scheduled_at_mono > send_at_mono:
        send_at_mono = float(next_scheduled_at_mono)
    next_scheduled_at_mono = float(next_scheduled_at_mono) + float(interval_s)
    if next_scheduled_at_mono < send_at_mono:
        next_scheduled_at_mono = send_at_mono + float(interval_s)
    return send_at_mono, next_scheduled_at_mono


def resolve_send_window_started_at(
    *,
    existing_started_at_mono: float | None,
    all_joined: bool,
    now_mono: float,
) -> float | None:
    if existing_started_at_mono is not None:
        return existing_started_at_mono
    if not all_joined:
        return None
    return float(now_mono)


def _client_options(cfg: ChatroomScenarioConfig) -> dict[str, object]:
    return {
        "app_key": cfg.app_key,
        "device_uuid": "locust-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
        "client_resource": cfg.client_resource,
        "using_https": cfg.use_ssl,
        "os_type": 2,
        "sdk_version": "4.16.0",
        "debug_mode": cfg.debug,
        "enable_console_log": cfg.console_log,
        "websocket_path": cfg.path,
    }


def _connect_kwargs(cfg: ChatroomScenarioConfig) -> ConnectKwargs:
    transport = "websocket" if cfg.mode in ("ws", "wss", "websocket") else "tcp"
    return {
        "ip": cfg.host,
        "port": cfg.port,
        "transport": transport,
        "use_ssl": bool(cfg.use_ssl),
    }


def _load_runtime_scenario(environment) -> ChatroomScenarioConfig:
    global _SCENARIO_CACHE
    with _SCENARIO_CACHE_LOCK:
        if _SCENARIO_CACHE is not None:
            return _SCENARIO_CACHE

        lc = _CENTER.longconn()
        parsed = getattr(environment, "parsed_options", None)
        if parsed is None:
            raise RuntimeError("locust runtime options not initialized")

        cr = _CENTER.chatroom_longconn_scene()

        room_count_raw = getattr(parsed, "room_count", None)
        users_per_room_raw = getattr(parsed, "users_per_room", None)
        sender_per_room_raw = getattr(parsed, "sender_per_room", None)
        room_msg_rps_raw = getattr(parsed, "room_msg_rps", None)
        send_pause_interval_s_raw = getattr(parsed, "send_pause_interval_s", None)
        send_batch_duration_s_raw = getattr(parsed, "send_batch_duration_s", None)
        enable_receive_metrics = bool(getattr(parsed, "enable_receive_metrics", False))
        enable_ack_metrics = bool(getattr(parsed, "enable_ack_metrics", False))

        def _is_blank(v: object) -> bool:
            return v is None or (isinstance(v, str) and v.strip() == "")

        room_count = int(cr.room_count) if _is_blank(room_count_raw) else int(room_count_raw)
        users_per_room = int(cr.users_per_room) if _is_blank(users_per_room_raw) else int(users_per_room_raw)
        sender_per_room = int(cr.sender_per_room) if _is_blank(sender_per_room_raw) else int(sender_per_room_raw)
        room_msg_rps = float(cr.room_msg_rps) if _is_blank(room_msg_rps_raw) else float(room_msg_rps_raw)
        send_pause_interval_s = (
            float(cr.send_pause_interval_s) if _is_blank(send_pause_interval_s_raw) else float(send_pause_interval_s_raw)
        )
        send_batch_duration_s = (
            float(cr.send_batch_duration_s) if _is_blank(send_batch_duration_s_raw) else float(send_batch_duration_s_raw)
        )
        msg = str(getattr(parsed, "chatroom_message", "") or "").strip()

        if room_count < 1:
            raise RuntimeError("--room-count 必须 >= 1")
        if users_per_room < 1:
            raise RuntimeError("--users-per-room 必须 >= 1")
        if sender_per_room < 1 or sender_per_room > users_per_room:
            raise RuntimeError("--sender-per-room 必须在 1..users-per-room 范围内")
        if room_msg_rps <= 0:
            raise RuntimeError("--room-msg-rps 必须 > 0")
        if send_pause_interval_s < 0:
            raise RuntimeError("--send-pause-interval-s 必须 >= 0")
        if send_batch_duration_s <= 0:
            raise RuntimeError("--send-batch-duration-s 必须 > 0")

        message = msg or cr.message or lc.message
        task_interval_s = resolve_sender_task_interval_s(room_msg_rps=room_msg_rps)
        room_ids = _build_room_ids(_SEED.room_id, room_count)

        _SCENARIO_CACHE = ChatroomScenarioConfig(
            room_count=room_count,
            users_per_room=users_per_room,
            sender_per_room=sender_per_room,
            room_msg_rps=room_msg_rps,
            task_interval_s=task_interval_s,
            send_pause_interval_s=send_pause_interval_s,
            send_batch_duration_s=send_batch_duration_s,
            user_prefix=_SEED.user_prefix,
            pad=_SEED.user_pad,
            password=_SEED.user_password,
            message=message,
            app_key=lc.app_key,
            host=lc.host,
            port=lc.port,
            mode=lc.mode,
            use_ssl=lc.use_ssl,
            path=lc.path,
            client_resource=lc.client_resource,
            debug=lc.debug,
            console_log=lc.console_log,
            token_url=lc.token_url,
            token_headers=lc.token_headers,
            chatroom_ids=room_ids,
            enable_receive_metrics=enable_receive_metrics,
            enable_ack_metrics=enable_ack_metrics,
        )
        return _SCENARIO_CACHE


class ChatroomOnlineUser(User):
    abstract = False

    def wait_time(self) -> float:
        if getattr(self, "is_sender", False):
            return 0.0
        return 1.0

    def _pace_sender_before_send(self) -> None:
        interval_s = max(0.001, self.cfg.task_interval_s)
        now = time.monotonic()
        send_at_mono, next_send_at_mono = plan_next_send_time(
            now_mono=now,
            next_send_at_mono=self._next_send_at_mono,
            interval_s=interval_s,
        )
        if send_at_mono > now:
            gevent_sleep(send_at_mono - now)
        self._next_send_at_mono = next_send_at_mono
        return send_at_mono

    def __init__(self, environment):
        super().__init__(environment)
        self.cfg = _load_runtime_scenario(environment)
        self._ring_total = require_cli_num_users(environment)
        self._expected_total = self.cfg.room_count * self.cfg.users_per_room
        if self._ring_total != self._expected_total:
            raise RuntimeError(
                f"locust -u 必须等于 room_count * users_per_room，当前 -u={self._ring_total}，"
                f"期望={self.cfg.room_count}*{self.cfg.users_per_room}={self._expected_total}"
            )

        raw_idx = next(_USER_COUNTER)
        self.user_idx = ((raw_idx - 1) % self._ring_total) + 1
        self.username = _fmt_user(self.cfg.user_prefix, self.user_idx, self.cfg.pad)
        self.secret = self.cfg.password

        room_seq = ((self.user_idx - 1) // self.cfg.users_per_room) + 1
        if room_seq > self.cfg.room_count:
            raise RuntimeError(f"用户分房越界: user_idx={self.user_idx}, room_seq={room_seq}")
        self.room_id = self.cfg.chatroom_ids[room_seq - 1]
        self.room_pos = ((self.user_idx - 1) % self.cfg.users_per_room) + 1
        self.is_sender = self.room_pos <= self.cfg.sender_per_room

        self.token: Optional[str] = None
        self.client: Optional[MsyncClient] = None
        self.is_online = False
        self._last_online_users_report_second = -1
        self._last_connect_error_at_mono = 0.0
        self._connect_retry_cooldown_s = _CONNECT_RETRY_COOLDOWN_S * (0.8 + 0.4 * random.random())
        self._metric_q: queue.SimpleQueue[tuple[str, float, dict, Optional[Exception]]] = queue.SimpleQueue()
        self._send_seq = 0
        self._target_send_rps_reported = False
        self._next_send_at_mono: Optional[float] = None
        self._active_burst_cycle_index: Optional[int] = None
        self._custom_payload_template = ChatroomCustomPayloadTemplate.build(
            room_id=self.room_id,
            sender=self.username,
            body=self.cfg.message,
        )

    def _ensure_token(self) -> str:
        self.token = http_get_token(
            self.username,
            self.secret,
            url=self.cfg.token_url,
            headers=self.cfg.token_headers,
        )
        return self.token

    def _fire_event(self, name: str, exception: Optional[Exception] = None, response_time: float = 0.0, context=None):
        events.request.fire(
            request_type="im",
            name=name,
            response_time=max(0.0, response_time),
            response_length=0,
            exception=exception,
            context=context or {},
        )

    def _enqueue_metric(self, name: str, response_time: float = 0.0, context=None, exception: Optional[Exception] = None):
        self._metric_q.put((name, response_time, context or {}, exception))

    def _flush_metric_queue(self, max_items: int = 500):
        for _ in range(max_items):
            try:
                name, rt, ctx, exc = self._metric_q.get_nowait()
            except queue.Empty:
                break
            self._fire_event(name=name, response_time=rt, context=ctx, exception=exc)

    def _connect(self):
        if self.client is not None and self.is_online:
            return

        client = MsyncClient(_client_options(self.cfg))
        if self.cfg.enable_ack_metrics:
            client.on_server_ack = lambda meta_id, server_id, rt_ms: self._enqueue_metric(
                "send_to_ack",
                response_time=rt_ms if rt_ms is not None else 0.0,
                context={"meta_id": meta_id, "server_id": server_id, "user": self.username, "room_id": self.room_id},
            )
        if self.cfg.enable_receive_metrics:
            client.on_message_received = lambda from_user, to_user, text, msg_id: self._enqueue_metric(
                "receive_chatroom",
                context={
                    "from": from_user,
                    "to": to_user,
                    "msg_id": msg_id,
                    "text_len": len(text or ""),
                    "room_id": self.room_id,
                },
            )

        try:
            conn = _connect_kwargs(self.cfg)
            client.connect(
                ip=conn["ip"],
                port=conn["port"],
                transport=conn["transport"],
                use_ssl=conn["use_ssl"],
            )
            token = self._ensure_token()
            if not token:
                raise RuntimeError(f"failed to get token for {self.username}")
            ok = client.login(self.username, token, password=self.secret)
            if not ok:
                token = self._ensure_token()
                ok = client.login(self.username, token, password=self.secret)
            if not ok:
                raise RuntimeError(
                    f"login failed for {self.username}; "
                    f"code={client.last_login_error_code}({client.last_login_error_name}); "
                    f"reason={client.last_login_reason}; "
                    f"host={self.cfg.host}:{self.cfg.port}; mode={self.cfg.mode}; app_key={self.cfg.app_key}; "
                    f"token_preview={_mask_token(token)}"
                )
            if not client.join_chatroom(self.room_id):
                raise RuntimeError(
                    f"join chatroom failed: user={self.username}, room_id={self.room_id}, "
                    f"code={client.last_muc_error_code}({client.last_muc_error_name}), reason={client.last_muc_reason}"
                )
            client.start_receiving(lambda _msg: None, emit_metrics=self.cfg.enable_receive_metrics)
            self._enqueue_metric("join_chatroom", context={"user": self.username, "room_id": self.room_id})
        except Exception:
            client.disconnect()
            raise

        self.client = client
        self.is_online = True
        with _ONLINE_USERS_LOCK:
            _ONLINE_USERS.add(self.username)
            _refresh_online_users_snapshot_locked()
        with _JOINED_USERS_LOCK:
            _JOINED_USERS.add(self.username)

    def _disconnect(self):
        with _ONLINE_USERS_LOCK:
            _ONLINE_USERS.discard(self.username)
            _refresh_online_users_snapshot_locked()
        with _JOINED_USERS_LOCK:
            _JOINED_USERS.discard(self.username)
        if self.client is not None:
            self.client.disconnect()
        self.client = None
        self.is_online = False

    def _can_retry_connect(self) -> bool:
        now = time.monotonic()
        return (now - self._last_connect_error_at_mono) >= self._connect_retry_cooldown_s

    def _all_joined(self) -> bool:
        with _JOINED_USERS_LOCK:
            return len(_JOINED_USERS) >= self._ring_total

    def _ensure_send_window_started(self) -> float | None:
        global _SEND_WINDOW_STARTED_AT_MONO
        now_mono = time.monotonic()
        all_joined = self._all_joined()
        with _SEND_WINDOW_STARTED_AT_LOCK:
            _SEND_WINDOW_STARTED_AT_MONO = resolve_send_window_started_at(
                existing_started_at_mono=_SEND_WINDOW_STARTED_AT_MONO,
                all_joined=all_joined,
                now_mono=now_mono,
            )
            return _SEND_WINDOW_STARTED_AT_MONO

    def _log_runtime_config_once(self) -> None:
        if self.user_idx != 1:
            return
        self._fire_event(
            "runtime_config",
            response_time=0.0,
            context={
                "room_count": self.cfg.room_count,
                "users_per_room": self.cfg.users_per_room,
                "sender_per_room": self.cfg.sender_per_room,
                "room_msg_rps": self.cfg.room_msg_rps,
                "send_batch_duration_s": self.cfg.send_batch_duration_s,
                "send_pause_interval_s": self.cfg.send_pause_interval_s,
                "task_interval_s": self.cfg.task_interval_s,
            },
        )
        print(
            "[chatroom_online_user_config]",
            {
                "room_count": self.cfg.room_count,
                "users_per_room": self.cfg.users_per_room,
                "sender_per_room": self.cfg.sender_per_room,
                "room_msg_rps": self.cfg.room_msg_rps,
                "send_batch_duration_s": self.cfg.send_batch_duration_s,
                "send_pause_interval_s": self.cfg.send_pause_interval_s,
                "task_interval_s": self.cfg.task_interval_s,
            },
        )

    def _report_online_users_metric(self) -> None:
        if self.user_idx != 1:
            return

        current_online_users = len(_ONLINE_USERS_SNAPSHOT)
        context = {
            "online_users": current_online_users,
            "target_total_users": self._ring_total,
            "active_rooms": self.cfg.room_count,
            "sender_per_room": self.cfg.sender_per_room,
            "room_msg_rps": self.cfg.room_msg_rps,
        }

        if current_online_users >= self._ring_total:
            if _mark_online_users_ready_reported():
                self._fire_event("online_users_ready", response_time=float(current_online_users), context=context)
            return

        elapsed_bucket = int(time.monotonic())
        if elapsed_bucket == self._last_online_users_report_second:
            return
        self._last_online_users_report_second = elapsed_bucket
        self._fire_event("online_users", response_time=float(current_online_users), context=context)

    def _report_target_send_rps_once(self) -> None:
        if self.user_idx != 1 or self._target_send_rps_reported:
            return
        self._target_send_rps_reported = True
        self._fire_event(
            "target_send_rps",
            response_time=calculate_target_send_rps(room_count=self.cfg.room_count, room_msg_rps=self.cfg.room_msg_rps),
            context={
                "room_count": self.cfg.room_count,
                "room_msg_rps": self.cfg.room_msg_rps,
                "sender_per_room": self.cfg.sender_per_room,
                "send_pause_interval_s": self.cfg.send_pause_interval_s,
                "send_batch_duration_s": self.cfg.send_batch_duration_s,
            },
        )

    def _report_room_send_count(self) -> None:
        self._fire_event(
            f"send_room_{self.room_id}",
            response_time=0.0,
            context={"room_id": self.room_id, "sender": self.username},
        )

    def _build_custom_message(self) -> str:
        self._send_seq += 1
        return self._custom_payload_template.render(
            seq=self._send_seq,
            ts_ms=int(time.time() * 1000),
        )

    def on_start(self):
        try:
            self._log_runtime_config_once()
            self._connect()
        except Exception as exc:
            self._fire_event("connect_error", exception=exc, context={"user": self.username, "room_id": self.room_id})

    def on_stop(self):
        self._disconnect()

    @task
    def chatroom_send_once(self):
        self._flush_metric_queue()
        self._report_online_users_metric()
        self._report_target_send_rps_once()

        if not self.is_online:
            if not self._can_retry_connect():
                return
            try:
                self._connect()
                self._last_connect_error_at_mono = 0.0
            except Exception as exc:
                self._last_connect_error_at_mono = time.monotonic()
                self._fire_event("connect_error", exception=exc, context={"user": self.username, "room_id": self.room_id})
                return

        if self.client is None:
            return

        # 先保证所有用户都已完成登录+入房，再开始统一发消息。
        if not self._all_joined():
            return

        if not self.is_sender:
            self._flush_metric_queue()
            return

        send_window_started_at_mono = self._ensure_send_window_started()
        if send_window_started_at_mono is None:
            self._flush_metric_queue()
            return
        if self.user_idx == 1 and _mark_send_window_start_logged():
            print(
                "[chatroom_online_user_send_window_started]",
                {
                    "started_at_mono": send_window_started_at_mono,
                    "send_batch_duration_s": self.cfg.send_batch_duration_s,
                    "send_pause_interval_s": self.cfg.send_pause_interval_s,
                },
            )

        burst = resolve_burst_window(
            now_mono=time.monotonic(),
            started_at_mono=send_window_started_at_mono,
            batch_duration_s=self.cfg.send_batch_duration_s,
            pause_interval_s=self.cfg.send_pause_interval_s,
        )
        if not burst.active:
            self._active_burst_cycle_index = None
            self._next_send_at_mono = None
            self._flush_metric_queue()
            return

        try:
            if self._active_burst_cycle_index != burst.cycle_index:
                self._active_burst_cycle_index = burst.cycle_index
                self._next_send_at_mono = burst.window_start_mono
            send_at_mono = self._pace_sender_before_send()
            if not is_in_send_window(
                now_mono=send_at_mono,
                started_at_mono=send_window_started_at_mono,
                batch_duration_s=self.cfg.send_batch_duration_s,
                pause_interval_s=self.cfg.send_pause_interval_s,
            ):
                self._flush_metric_queue()
                return
            custom_message = self._build_custom_message()
            self.client.send_chatroom_custom_data_message(
                self.room_id,
                custom_event="ROOM_CHAT",
                custom_data=custom_message,
            )
            self._report_room_send_count()
        except Exception as exc:
            self._fire_event(
                "send_error",
                exception=exc,
                context={"user": self.username, "room_id": self.room_id},
            )
            self._disconnect()
            return
        self._flush_metric_queue()
