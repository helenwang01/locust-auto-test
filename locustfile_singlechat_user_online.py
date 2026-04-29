from __future__ import annotations

import random
import queue
import string
import sys
import threading
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Optional

from locust import User, constant_pacing, events, task

root = Path(__file__).resolve().parent
for p in (root, root / "src"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from apis.token_api import get_token as http_get_token
from loadtests.common.config_center import LoadtestConfigCenter
from utils.msync_client import MsyncClient


@dataclass(frozen=True)
class OnlineTimelineConfig:
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


def _load_scenario() -> OnlineTimelineConfig:
    lc = LoadtestConfigCenter.get().longconn()
    return OnlineTimelineConfig(
        total_users=lc.total_users,
        offline_at_s=lc.offline_at_s,
        offline_count=lc.offline_count,
        online1_at_s=lc.online1_at_s,
        online1_count=lc.online1_count,
        online2_at_s=lc.online2_at_s,
        online2_count=lc.online2_count,
        duration_s=lc.duration_s,
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
_TEST_START_MONO: Optional[float] = None
_ONLINE_USERS: set[str] = set()
_ONLINE_USERS_LOCK = threading.Lock()
_LOGGED_IN_USERS: set[str] = set()
_LOGIN_LOCK = threading.Lock()
_ALL_LOGGED_IN_READY = False
_LAST_LOGIN_PROGRESS = -1
_EXPECTED_LOGIN_USERS = 0


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


def active_online_count(elapsed_s: float, cfg: OnlineTimelineConfig) -> int:
    if elapsed_s < cfg.offline_at_s:
        return cfg.total_users
    if elapsed_s < cfg.online1_at_s:
        return cfg.total_users - cfg.offline_count
    if elapsed_s < cfg.online2_at_s:
        return cfg.total_users - cfg.offline_count + cfg.online1_count
    return cfg.total_users


def is_user_online_at(user_idx: int, elapsed_s: float, cfg: OnlineTimelineConfig) -> bool:
    return 1 <= user_idx <= active_online_count(elapsed_s, cfg)


def should_emit_online_users_metric(user_idx: int) -> bool:
    return user_idx == 1


def online_users_metric_value(elapsed_s: float, cfg: OnlineTimelineConfig) -> float:
    del elapsed_s, cfg
    with _ONLINE_USERS_LOCK:
        return float(len(_ONLINE_USERS))


def _resolve_expected_login_users(environment) -> int:
    # 优先取本次压测实际目标用户数（UI/CLI 传入），再回退配置值
    target = None
    parsed = getattr(environment, "parsed_options", None)
    if parsed is not None:
        for k in ("users", "user_count"):
            v = getattr(parsed, k, None)
            if isinstance(v, (int, float)) and int(v) > 0:
                target = int(v)
                break
    if target is None:
        runner = getattr(environment, "runner", None)
        for k in ("target_user_count", "user_count"):
            v = getattr(runner, k, None) if runner is not None else None
            if isinstance(v, (int, float)) and int(v) > 0:
                target = int(v)
                break
    if target is None:
        target = SCENARIO.total_users
    return max(1, int(target))


def _client_options(cfg: OnlineTimelineConfig) -> dict[str, object]:
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


def _connect_kwargs(cfg: OnlineTimelineConfig) -> dict[str, object]:
    transport = "websocket" if cfg.mode in ("ws", "wss", "websocket") else "tcp"
    return {
        "ip": cfg.host,
        "port": cfg.port,
        "transport": transport,
        "use_ssl": bool(cfg.use_ssl),
    }


def elapsed_since_test_start_s() -> float:
    if _TEST_START_MONO is None:
        return 0.0
    return max(0.0, time.monotonic() - _TEST_START_MONO)


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    del kwargs
    global _TEST_START_MONO, _ALL_LOGGED_IN_READY, _LAST_LOGIN_PROGRESS, _EXPECTED_LOGIN_USERS
    _TEST_START_MONO = time.monotonic()
    _ALL_LOGGED_IN_READY = False
    _LAST_LOGIN_PROGRESS = -1
    _EXPECTED_LOGIN_USERS = _resolve_expected_login_users(environment)
    print(
        f"[login-ready] expected_users={_EXPECTED_LOGIN_USERS}, "
        f"scenario_total={SCENARIO.total_users}"
    )
    with _ONLINE_USERS_LOCK:
        _ONLINE_USERS.clear()
    with _LOGIN_LOCK:
        _LOGGED_IN_USERS.clear()


@events.test_stop.add_listener
def _on_test_stop(environment, **kwargs):
    del environment, kwargs
    global _TEST_START_MONO
    _TEST_START_MONO = None


class OnlineSingleChatUser(User):
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
        self._metric_q: queue.SimpleQueue[tuple[str, float, dict, Optional[Exception]]] = queue.SimpleQueue()

    def _ensure_token(self, force_refresh: bool = False) -> str:
        print(
            f"[token-debug] url={SCENARIO.token_url} "
            f"username={self.username} password={self.secret} force_refresh={force_refresh}"
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

    def _pick_online_peer(self) -> str:
        with _ONLINE_USERS_LOCK:
            peers = [u for u in _ONLINE_USERS if u != self.username]
        if peers:
            return random.choice(peers)
        # 没有其他在线用户时退化到自发自收，保证链路指标可观测
        return self.username

    def _connect(self):
        if self.client is not None and self.is_online:
            return

        client = MsyncClient(_client_options(SCENARIO))
        client.on_server_ack = lambda meta_id, server_id, rt_ms: self._enqueue_metric(
            "send_to_ack",
            response_time=rt_ms if rt_ms is not None else 0.0,
            context={"meta_id": meta_id, "server_id": server_id, "user": self.username},
        )
        # end_to_end 仅统计数量，不统计耗时
        client.on_delivery = lambda meta_id, from_user, to_user, rt_ms: self._enqueue_metric(
            "end_to_end",
            response_time=0.0,
            context={"meta_id": meta_id, "from": from_user, "to": to_user, "rt_ms": rt_ms},
        )
        client.on_message_received = lambda from_user, to_user, text, msg_id: self._enqueue_metric(
            "receive_chat",
            context={"from": from_user, "to": to_user, "msg_id": msg_id, "text_len": len(text or "")},
        )

        try:
            client.connect(**_connect_kwargs(SCENARIO))
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
                    f"host={SCENARIO.host}:{SCENARIO.port}; mode={SCENARIO.mode}; app_key={SCENARIO.app_key}; "
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
        self._mark_login_ready()

    def _mark_login_ready(self):
        global _ALL_LOGGED_IN_READY, _LAST_LOGIN_PROGRESS
        with _LOGIN_LOCK:
            if self.username in _LOGGED_IN_USERS:
                return
            _LOGGED_IN_USERS.add(self.username)
            cur = len(_LOGGED_IN_USERS)
            if cur != _LAST_LOGIN_PROGRESS:
                _LAST_LOGIN_PROGRESS = cur
                print(f"[login-ready] {cur}/{_EXPECTED_LOGIN_USERS}")
            if cur >= _EXPECTED_LOGIN_USERS and not _ALL_LOGGED_IN_READY:
                _ALL_LOGGED_IN_READY = True
                print("[login-ready] all users logged in, start sending messages")

    def _disconnect(self):
        with _ONLINE_USERS_LOCK:
            _ONLINE_USERS.discard(self.username)
        if self.client is not None:
            self.client.disconnect()
        self.client = None
        self.is_online = False

    def on_start(self):
        if is_user_online_at(self.user_idx, elapsed_since_test_start_s(), SCENARIO):
            try:
                self._connect()
            except Exception as exc:
                self._fire_event("connect_error", exception=exc, context={"user": self.username})

    def on_stop(self):
        self._disconnect()

    @task
    def chat_once(self):
        self._flush_metric_queue()
        elapsed_s = elapsed_since_test_start_s()
        if should_emit_online_users_metric(self.user_idx):
            elapsed_bucket = int(elapsed_s)
            if elapsed_bucket != self._last_online_users_report_second:
                self._last_online_users_report_second = elapsed_bucket
                online_users = online_users_metric_value(elapsed_s, SCENARIO)
                self._fire_event(
                    "online_users",
                    response_time=online_users,
                    context={"online_users": int(online_users)},
                )

        should_be_online = is_user_online_at(self.user_idx, elapsed_s, SCENARIO)
        if should_be_online and not self.is_online:
            try:
                self._connect()
            except Exception as exc:
                self._fire_event("connect_error", exception=exc, context={"user": self.username})
                return
        elif not should_be_online and self.is_online:
            self._disconnect()
            return

        if not should_be_online or self.client is None:
            return

        if not _ALL_LOGGED_IN_READY:
            return

        try:
            to_user = self._pick_online_peer()
            self.client.send_message(to_user, SCENARIO.message)
        except Exception as exc:
            self._fire_event("send_error", exception=exc, context={"user": self.username, "peer": self.peer})
            self._disconnect()
            return
        self._flush_metric_queue()
