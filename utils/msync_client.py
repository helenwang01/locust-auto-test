import logging
import socket
import ssl
import struct
import threading
import time
from typing import Optional, Callable, Dict
from types import SimpleNamespace
from pathlib import Path

# NOTE: pb imports: try relative (package mode) then top-level (script mode)
try:  # package-style
    from ...pb import jid_pb2, messagebody_pb2, msync_pb2  # type: ignore
except Exception:
    try:  # repo-root script-style (ensure src/ on path)
        import sys
        root = Path(__file__).resolve().parents[1]
        for p in (root / "src", root):
            sp = str(p)
            if sp not in sys.path:
                sys.path.insert(0, sp)
        from pb import jid_pb2, messagebody_pb2, msync_pb2  # type: ignore
    except Exception as _e:
        raise

try:
    from websocket import create_connection
    HAS_WEBSOCKET = True
except Exception:
    HAS_WEBSOCKET = False


class MsyncClient:
    """
    Minimal msync client for single-chat load testing.
    - Transport: TCP (fixed32 length-prefix) or WebSocket (binary)
    - Auth: PROVISION with token
    - Chat: one-to-one only (MessageBody.Type.CHAT)
    - Metrics: server ACK and delivery latency callbacks
    """

    def __init__(self, options):
        # Accept either an object with attributes or a plain dict
        if isinstance(options, dict):
            options = SimpleNamespace(**options)
        self.options = options
        self.appkey = options.app_key
        self.device_uuid = options.device_uuid
        self.client_resource = getattr(options, "client_resource", "python")

        self.socket: Optional[socket.socket] = None
        self.ws = None
        self.transport_type: Optional[str] = None  # "tcp" | "websocket"

        self.is_connected = False
        self.is_logged_in = False

        # receiving
        self._rx_thread: Optional[threading.Thread] = None
        self._rx_running = False
        self._on_packet: Optional[Callable[[msync_pb2.MSync], None]] = None

        # callbacks for metrics
        # on_server_ack(meta_id: int, server_id: int, rt_ms: float)
        self.on_server_ack: Optional[Callable[[int, int, float], None]] = None
        # on_delivery(meta_id: int, from_user: str, to_user: str, rt_ms: float)
        self.on_delivery: Optional[Callable[[int, str, str, float], None]] = None
        # on_message_received(from_user: str, to_user: str, text: str, meta_id: int)
        self.on_message_received: Optional[Callable[[str, str, str, int], None]] = None

        # pending send tracking: meta_id -> t_send_ms
        self._pending: Dict[int, float] = {}

        # last login diagnostics
        self.last_login_error_code: Optional[int] = None
        self.last_login_error_name: Optional[str] = None
        self.last_login_reason: Optional[str] = None

        # logger
        self.logger = logging.getLogger(f"MsyncClient_{id(self)}")
        self.logger.setLevel(logging.DEBUG if getattr(options, "debug_mode", False) else logging.INFO)
        if getattr(options, "enable_console_log", True) and not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            self.logger.addHandler(logging.StreamHandler())

    # --------------- transport ---------------
    def connect(self, ip: Optional[str] = None, port: Optional[int] = None,
                transport: Optional[str] = None, use_ssl: Optional[bool] = None,
                timeout: float = 30.0):
        self.transport_type = (transport or "tcp").lower()
        use_ssl = bool(use_ssl if use_ssl is not None else getattr(self.options, "using_https", False))

        if self.transport_type == "tcp":
            host = ip or getattr(self.options, "im_server", None)
            prt = int(port or getattr(self.options, "im_port", 0))
            if not host or not prt:
                raise ValueError("tcp requires ip and port (or options.im_server/im_port)")
            s = socket.create_connection((host, prt), timeout=timeout)
            if use_ssl:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                s = ctx.wrap_socket(s, server_hostname=host)
            s.settimeout(timeout)
            self.socket = s
            self.is_connected = True
            self.logger.debug(f"TCP connected {host}:{prt} ssl={use_ssl}")
        elif self.transport_type == "websocket":
            if not HAS_WEBSOCKET:
                raise ImportError("websocket-client is required for websocket transport")
            host = ip or getattr(self.options, "websocket_server", None)
            prt = int(port or getattr(self.options, "websocket_port", 0))
            path = getattr(self.options, "websocket_path", None) or "/websocket"
            if not host or not prt:
                raise ValueError("websocket requires ip and port (or options.websocket_server/websocket_port)")
            scheme = "wss" if use_ssl else "ws"
            if not path.startswith("/"):
                path = "/" + path
            url = f"{scheme}://{host}:{prt}{path}"
            sslopt = {"cert_reqs": ssl.CERT_NONE} if use_ssl else None
            self.ws = create_connection(url, timeout=timeout, sslopt=sslopt)
            self.is_connected = True
            self.logger.debug(f"WS connected {url}")
        else:
            raise ValueError(f"unsupported transport: {self.transport_type}")

    def disconnect(self):
        self.stop_receiving()
        if self.socket:
            try:
                self.socket.close()
            finally:
                self.socket = None
        if self.ws:
            try:
                self.ws.close()
            finally:
                self.ws = None
        self.is_connected = False
        self.is_logged_in = False

    # --------------- io helpers ---------------
    def _send_packet(self, msync_msg: msync_pb2.MSync):
        data = msync_msg.SerializeToString()
        if self.transport_type == "tcp":
            header = struct.pack(">I", len(data))
            assert self.socket is not None
            self.socket.sendall(header + data)
        else:
            assert self.ws is not None
            self.ws.send_binary(data)

    def _recv_packet(self, timeout: Optional[float] = None) -> Optional[msync_pb2.MSync]:
        end = time.time() + (timeout or 0) if timeout else None
        try:
            if self.transport_type == "tcp":
                assert self.socket is not None
                self.socket.settimeout((end - time.time()) if end else None)
                hdr = self._read_exact(4)
                if not hdr:
                    return None
                length = struct.unpack(">I", hdr)[0]
                payload = self._read_exact(length)
                if len(payload) != length:
                    return None
                msg = msync_pb2.MSync()
                msg.ParseFromString(payload)
                return msg
            else:
                assert self.ws is not None
                if timeout:
                    self.ws.settimeout(max(0.001, end - time.time()))
                data = self.ws.recv()
                if not data:
                    return None
                msg = msync_pb2.MSync()
                msg.ParseFromString(data)
                return msg
        except Exception:
            return None

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        assert self.socket is not None
        while len(buf) < n:
            chunk = self.socket.recv(n - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def _send_sync_ul(self, queue_jid: jid_pb2.JID, key: int = 0):
        sync_ul = msync_pb2.CommSyncUL()
        if key != 0:
            sync_ul.key = key
        sync_ul.queue.CopyFrom(queue_jid)

        ms = msync_pb2.MSync()
        ms.version = msync_pb2.MSync.MSYNC_V1
        ms.command = msync_pb2.MSync.SYNC
        ms.guid.CopyFrom(self._current_jid())
        ms.payload = sync_ul.SerializeToString()
        self._send_packet(ms)

    # --------------- auth ---------------
    def _build_login_msg(self, username: str, token: str) -> msync_pb2.MSync:
        provision = msync_pb2.Provision()
        provision.os_type = getattr(self.options, "os_type", 1)
        provision.version = getattr(self.options, "sdk_version", "python")
        provision.device_uuid = self.device_uuid
        provision.auth_token = ("{""token"": ""%s""}" % token).encode("utf-8")
        provision.is_manual_login = True

        jid = jid_pb2.JID()
        jid.app_key = self.appkey
        jid.name = username
        jid.domain = "easemob.com"
        jid.client_resource = self.client_resource

        ms = msync_pb2.MSync()
        ms.version = msync_pb2.MSync.MSYNC_V1
        ms.command = msync_pb2.MSync.PROVISION
        ms.guid.CopyFrom(jid)
        ms.payload = provision.SerializeToString()
        return ms

    def login(self, username: str, token: str, timeout: float = 10.0) -> bool:
        self.current_username = username
        self.last_login_error_code = None
        self.last_login_error_name = None
        self.last_login_reason = None
        self._send_packet(self._build_login_msg(username, token))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._recv_packet(timeout=max(0.001, deadline - time.time()))
            if not msg:
                continue
            if msg.command == msync_pb2.MSync.PROVISION:
                prov = msync_pb2.Provision()
                prov.ParseFromString(msg.payload)
                code = int(getattr(prov.status, "error_code", 1))
                reason = str(getattr(prov.status, "reason", "") or "")
                try:
                    code_name = msync_pb2.Status.ErrorCode.Name(code)
                except Exception:
                    code_name = f"UNKNOWN_{code}"

                self.last_login_error_code = code
                self.last_login_error_name = code_name
                self.last_login_reason = reason

                ok = code == 0
                self.is_logged_in = ok
                if ok:
                    self.logger.debug("LOGIN OK user=%s", username)
                else:
                    self.logger.warning(
                        "LOGIN FAIL user=%s code=%s(%s) reason=%s",
                        username,
                        code,
                        code_name,
                        reason,
                    )
                return ok
        self.is_logged_in = False
        self.last_login_error_code = -1
        self.last_login_error_name = "TIMEOUT"
        self.last_login_reason = f"no PROVISION response within {timeout}s"
        self.logger.warning("LOGIN TIMEOUT user=%s timeout=%ss", username, timeout)
        return False

    # --------------- chat ---------------
    def send_message(self, to_username: str, content_text: str) -> int:
        if not self.is_logged_in:
            raise RuntimeError("not logged in")
        msg_id = int(time.time() * 1000)

        body = messagebody_pb2.MessageBody()
        body.type = messagebody_pb2.MessageBody.Type.CHAT

        j_from = jid_pb2.JID()
        j_from.app_key = self.appkey
        j_from.name = self.current_username
        j_from.domain = "easemob.com"
        j_from.client_resource = self.client_resource
        getattr(body, "from").CopyFrom(j_from)

        j_to = jid_pb2.JID()
        j_to.app_key = self.appkey
        j_to.name = to_username
        j_to.domain = "easemob.com"
        body.to.CopyFrom(j_to)

        ct = body.contents.add()
        ct.type = messagebody_pb2.MessageBody.Content.Type.TEXT
        ct.text = content_text

        meta = msync_pb2.Meta()
        meta.ns = msync_pb2.Meta.NameSpace.CHAT
        meta.to.CopyFrom(j_to)
        meta.payload = body.SerializeToString()
        meta.id = msg_id

        ul = msync_pb2.CommSyncUL()
        ul.meta.CopyFrom(meta)

        ms = msync_pb2.MSync()
        ms.version = msync_pb2.MSync.MSYNC_V1
        ms.command = msync_pb2.MSync.SYNC
        ms.guid.CopyFrom(j_from)
        ms.payload = ul.SerializeToString()

        # record send timestamp for ack/delivery latency
        self._pending[msg_id] = time.time() * 1000.0
        self._send_packet(ms)
        return msg_id

    # --------------- receive loop ---------------
    def start_receiving(self, on_packet: Callable[[msync_pb2.MSync], None]):
        """Start background loop and invoke callback for each parsed MSync packet."""
        if self._rx_thread and self._rx_thread.is_alive():
            return
        self._on_packet = on_packet
        self._rx_running = True

        def _loop():
            while self._rx_running and self.is_connected:
                msg = self._recv_packet(timeout=1.0)
                if msg is None:
                    continue
                try:
                    if self._on_packet:
                        self._on_packet(msg)
                    # built-in parsing for metrics
                    self._parse_and_emit(msg)
                except Exception:
                    pass
                if msg.command == msync_pb2.MSync.NOTICE:
                    try:
                        notice = msync_pb2.CommNotice()
                        notice.ParseFromString(msg.payload)
                        ul = msync_pb2.CommSyncUL()
                        ul.queue.CopyFrom(notice.queue)
                        ms = msync_pb2.MSync()
                        ms.version = msync_pb2.MSync.MSYNC_V1
                        ms.command = msync_pb2.MSync.SYNC
                        ms.guid.CopyFrom(self._current_jid())
                        ms.payload = ul.SerializeToString()
                        self._send_packet(ms)
                    except Exception:
                        pass
        self._rx_thread = threading.Thread(target=_loop, name="msync-recv", daemon=True)
        self._rx_thread.start()

    def stop_receiving(self):
        self._rx_running = False
        t = self._rx_thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._rx_thread = None

    # --------------- helpers ---------------
    def _current_jid(self) -> jid_pb2.JID:
        j = jid_pb2.JID()
        j.app_key = self.appkey
        j.name = getattr(self, "current_username", "")
        j.domain = "easemob.com"
        j.client_resource = self.client_resource
        return j

    def _emit_server_ack(self, meta_id: int, server_id: int):
        # 不在 ACK 阶段 pop，避免 end_to_end 取不到发送时间
        t0 = self._pending.get(meta_id, None)
        rt = (time.time() * 1000.0 - t0) if t0 else -1.0
        if self.on_server_ack:
            try:
                self.on_server_ack(meta_id, server_id, rt)
            except Exception:
                pass

    def _emit_delivery(self, meta_id: int, from_user: str, to_user: str, msg_ts_ms: Optional[int] = None):
        # delivery 仅用于事件计数，这里不再计算耗时；仍清理 pending 避免增长
        del msg_ts_ms
        self._pending.pop(meta_id, None)
        rt = 0.0
        if self.on_delivery:
            try:
                self.on_delivery(meta_id, from_user, to_user, rt)
            except Exception:
                pass

    def _parse_and_emit(self, ms: msync_pb2.MSync):
        if ms.command != msync_pb2.MSync.SYNC:
            return
        # Parse DL payload
        try:
            dl = msync_pb2.CommSyncDL()
            dl.ParseFromString(ms.payload)
        except Exception:
            return

        try:
            if dl.HasField("next_key") and dl.next_key != 0 and dl.HasField("queue"):
                self._send_sync_ul(dl.queue, int(dl.next_key))
        except Exception:
            pass

        # Server ACK path (dl.meta_id + dl.server_id)
        try:
            if hasattr(dl, "server_id") and hasattr(dl, "meta_id") and dl.HasField("server_id") and dl.HasField("meta_id"):
                self._emit_server_ack(int(dl.meta_id), int(dl.server_id))
        except Exception:
            pass

        # Delivered messages metas
        metas = []
        try:
            if hasattr(dl, "metas"):
                metas = list(dl.metas)
            elif hasattr(dl, "meta") and dl.HasField("meta"):
                metas = [dl.meta]
        except Exception:
            metas = []

        for m in metas:
            try:
                if m.ns != msync_pb2.Meta.NameSpace.CHAT:
                    continue
                body = messagebody_pb2.MessageBody()
                body.ParseFromString(m.payload)
                # Extract basic fields
                from_user = getattr(body, "from").name if hasattr(body, "from") else ""
                to_user = body.to.name if hasattr(body, "to") else ""
                text = ""
                try:
                    if body.contents:
                        c0 = body.contents[0]
                        if hasattr(c0, "text") and c0.HasField("text"):
                            text = c0.text
                except Exception:
                    pass
                # message received callback
                if self.on_message_received:
                    try:
                        self.on_message_received(from_user, to_user, text, int(m.id))
                    except Exception:
                        pass
                # delivery latency metric
                ts = int(m.timestamp) if hasattr(m, "timestamp") else 0
                self._emit_delivery(int(m.id), from_user, to_user, ts)
            except Exception:
                continue
