from __future__ import annotations

import queue
import random
import string
import sys
import threading
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Optional, TypedDict

from locust import User, constant_pacing, events, task

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from apis.token_api import get_token as http_get_token
from loadtests.common.config_center import LoadtestConfigCenter
from utils.msync_client import MsyncClient


@dataclass(frozen=True)
class TcpSingleChatConfig:
    total_users: int
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


class TcpConnectKwargs(TypedDict):
    ip: str
    port: int
    transport: str
    use_ssl: bool


def _load_scenario() -> TcpSingleChatConfig:
    lc = LoadtestConfigCenter.get().longconn()
    return TcpSingleChatConfig(
        total_users=lc.total_users,
        message_interval_s=lc.message_interval_s,
        spawn_rate=lc.spawn_rate,
        user_prefix=lc.user_prefix,
        pad=lc.pad,
        password=lc.password,
        message=lc.message,
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
    )


SCENARIO = _load_scenario()
_USER_COUNTER = count(1)
_ONLINE_USERS: set[str] = set()
_ONLINE_USERS_SNAPSHOT: tuple[str, ...] = ()
_ONLINE_USERS_LOCK = threading.Lock()
_CONNECT_RETRY_COOLDOWN_S = 1.0


def _mask_token(token: Optional[str]) -> str:
    if not token:
        return "<empty>"
    if len(token) <= 12:
        return f"{token[:2]}***{token[-2:]}(len={len(token)})"
    return f"{token[:6]}...{token[-6:]}(len={len(token)})"


def _fmt_user(prefix: str, idx: int, pad: int) -> str:
    if pad > 0:
        return f"{prefix}{idx:0{pad}d}"
    return f"{prefix}{idx}"


def should_emit_online_users_metric(user_idx: int) -> bool:
    return user_idx == 1


def current_online_count() -> int:
    return len(_ONLINE_USERS_SNAPSHOT)


def online_users_metric_value() -> float:
    return float(current_online_count())


def _refresh_online_users_snapshot_locked() -> None:
    global _ONLINE_USERS_SNAPSHOT
    _ONLINE_USERS_SNAPSHOT = tuple(_ONLINE_USERS)


def _client_options(cfg: TcpSingleChatConfig) -> dict[str, object]:
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


def _connect_kwargs(cfg: TcpSingleChatConfig) -> TcpConnectKwargs:
    return {
        "ip": cfg.host,
        "port": cfg.port,
        "transport": "tcp",
        "use_ssl": bool(cfg.use_ssl),
    }


class TcpSingleChatUser(User):
    wait_time = constant_pacing(SCENARIO.message_interval_s)

    def __init__(self, environment):
        super().__init__(environment)
        raw_idx = next(_USER_COUNTER)
        self.user_idx = ((raw_idx - 1) % SCENARIO.total_users) + 1
        next_idx = (self.user_idx % SCENARIO.total_users) + 1
        self.username = _fmt_user(SCENARIO.user_prefix, self.user_idx, SCENARIO.pad)
        self.peer = _fmt_user(SCENARIO.user_prefix, next_idx, SCENARIO.pad)
        self.secret = SCENARIO.password
        self.token: Optional[str] = None
        self.client: Optional[MsyncClient] = None
        self.is_online = False
        self._last_online_users_report_second = -1
        self._last_connect_error_at_mono = 0.0
        self._connect_retry_cooldown_s = _CONNECT_RETRY_COOLDOWN_S * (0.8 + 0.4 * random.random())
        self._metric_q: queue.SimpleQueue[tuple[str, float, dict, Optional[Exception]]] = queue.SimpleQueue()

    def _ensure_token(self, force_refresh: bool = False) -> str:
        print(
            f"[token-debug] url={SCENARIO.token_url} "
            f"username={self.username} force_refresh={force_refresh}"
        )
        self.token = http_get_token(
            self.username,
            self.secret,
            url=SCENARIO.token_url,
            headers=SCENARIO.token_headers,
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

        client = MsyncClient(_client_options(SCENARIO))
        client.on_server_ack = lambda meta_id, server_id, rt_ms: self._enqueue_metric(
            "send_to_ack",
            response_time=rt_ms if rt_ms is not None else 0.0,
            context={"meta_id": meta_id, "server_id": server_id, "user": self.username},
        )
        client.on_delivery = lambda meta_id, from_user, to_user, rt_ms: self._enqueue_metric(
            "end_to_end",
            response_time=rt_ms if rt_ms is not None else 0.0,
            context={"meta_id": meta_id, "from": from_user, "to": to_user},
        )
        client.on_message_received = lambda from_user, to_user, text, msg_id: self._enqueue_metric(
            "receive_chat",
            context={"from": from_user, "to": to_user, "msg_id": msg_id, "text_len": len(text or "")},
        )

        try:
            conn = _connect_kwargs(SCENARIO)
            client.connect(
                ip=conn["ip"],
                port=conn["port"],
                transport=conn["transport"],
                use_ssl=conn["use_ssl"],
            )
            token = self._ensure_token()
            if not token:
                raise RuntimeError(f"failed to get token for {self.username}")
            ok = client.login(self.username, token)
            if not ok:
                token = self._ensure_token(force_refresh=True)
                ok = client.login(self.username, token)
            if not ok:
                raise RuntimeError(
                    f"login failed for {self.username}; "
                    f"code={client.last_login_error_code}({client.last_login_error_name}); "
                    f"reason={client.last_login_reason}; "
                    f"host={SCENARIO.host}:{SCENARIO.port}; mode=tcp; app_key={SCENARIO.app_key}; "
                    f"token_preview={_mask_token(token)}"
                )
            client.start_receiving(lambda _msg: None)
        except Exception:
            client.disconnect()
            raise

        self.client = client
        self.is_online = True
        with _ONLINE_USERS_LOCK:
            _ONLINE_USERS.add(self.username)
            _refresh_online_users_snapshot_locked()

    def _disconnect(self):
        with _ONLINE_USERS_LOCK:
            _ONLINE_USERS.discard(self.username)
            _refresh_online_users_snapshot_locked()
        if self.client is not None:
            self.client.disconnect()
        self.client = None
        self.is_online = False

    def _can_retry_connect(self) -> bool:
        now = time.monotonic()
        return (now - self._last_connect_error_at_mono) >= self._connect_retry_cooldown_s

    def on_start(self):
        try:
            self._connect()
        except Exception as exc:
            self._fire_event("connect_error", exception=exc, context={"user": self.username})

    def on_stop(self):
        self._disconnect()

    @task
    def chat_once(self):
        self._flush_metric_queue()
        if should_emit_online_users_metric(self.user_idx):
            elapsed_bucket = int(time.monotonic())
            if elapsed_bucket != self._last_online_users_report_second:
                self._last_online_users_report_second = elapsed_bucket
                online_users = online_users_metric_value()
                self._fire_event(
                    "online_users",
                    response_time=online_users,
                    context={
                        "online_users": int(online_users),
                        "target_total_users": SCENARIO.total_users,
                    },
                )

        if not self.is_online:
            if not self._can_retry_connect():
                return
            try:
                self._connect()
                self._last_connect_error_at_mono = 0.0
            except Exception as exc:
                self._last_connect_error_at_mono = time.monotonic()
                self._fire_event("connect_error", exception=exc, context={"user": self.username})
                return

        if self.client is None:
            return

        try:
            self.client.send_message(self.peer, SCENARIO.message)
        except Exception as exc:
            self._fire_event("send_error", exception=exc, context={"user": self.username, "peer": self.peer})
            self._disconnect()
            return
        self._flush_metric_queue()
