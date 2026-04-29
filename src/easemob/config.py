from __future__ import annotations
import os
from dataclasses import dataclass, fields
from typing import Dict, Any, Mapping
from pathlib import Path
import yaml

DEFAULT_CONFIG_PATH = "cfg/singlechat.yaml"


def default_config_path() -> str:
    """Which YAML to load; override with env ``EASEMOB_CFG`` (only bootstrap hook)."""
    return os.environ.get("EASEMOB_CFG", DEFAULT_CONFIG_PATH)


@dataclass
class TransportCfg:
    mode: str
    host: str
    port: int
    path: str | None = None
    tls_verify: bool = True


@dataclass
class ProtoCfg:
    codec: str
    modules_path: str
    messages: Dict[str, str]


@dataclass
class WorkloadCfg:
    pairs: int
    spawn_rate: int
    pattern: str
    msg_per_sec: float
    msg_sizes: list[int]
    online_ratio: float
    receiver_offline_ratio: float


@dataclass
class HeartbeatCfg:
    interval_ms: int
    timeout_ms: int


@dataclass
class TokenRestCfg:
    url: str
    method: str = "POST"
    headers: Dict[str, str] | None = None
    body_template: str | None = None
    response_json_pointer: str = "/token"





@dataclass
class TokenServiceCfg:
    url: str
    org_name: str
    app_name: str
@dataclass
class SecurityCfg:
    auth: str = "token"  # password|token|none
    token_source: str = "rest"  # file|rest
    token_rest: TokenRestCfg | None = None
    app_key: str | None = None  # e.g. org#appname


@dataclass
class ReceiptsCfg:
    server_ack: bool = True
    delivery_receipt: bool = True
    read_receipt: bool = False


@dataclass
class RunCfg:
    """Runtime / Locust / pytest 均只从 YAML ``run:`` 读取（不再用环境变量覆盖 run）。"""

    sender_prefix: str = "tst"
    receiver_prefix: str = "tst"
    pad: int = 0
    start_sender: int = 1
    start_receiver: int = 1
    client_resource: str = "locust"
    debug: bool = False
    console_log: bool = True
    password: str = "1"
    pb_secret: str = "secret"
    message: str = "hello"
    sender: str | None = None
    peer: str | None = None
    receiver: str | None = None
    token_url: str | None = None
    api_dir: str | None = None
    app_key: str | None = None
    pb_sender: str = "sender_1"
    pb_peer: str = "receiver_1"
    pb_receiver: str = "receiver_1"
    token_integration: bool = False
    token_api_test_use_default_url: bool = False


def _run_from_mapping(raw: Mapping[str, Any] | None) -> RunCfg:
    if not raw:
        return RunCfg()
    defaults = RunCfg()
    d: Dict[str, Any] = {}
    for f in fields(RunCfg):
        if f.name in raw:
            d[f.name] = raw[f.name]
        else:
            d[f.name] = getattr(defaults, f.name)
    return RunCfg(**d)


def run_cfg_env_var_name(field_name: str) -> str:
    """历史兼容：``RunCfg`` 字段名 -> 旧版环境变量名（当前 run 仅来自 YAML）。"""
    return "EASEMOB_" + field_name.upper()


@dataclass
class Config:
    transport: TransportCfg
    proto: ProtoCfg
    workload: WorkloadCfg
    heartbeat: HeartbeatCfg
    security: SecurityCfg
    metrics: Dict[str, Any]
    receipts: ReceiptsCfg
    run: RunCfg

    @staticmethod
    def load(path: str | None = None) -> "Config":
        """Load YAML config with robust path resolution.
        Resolution order:
          1) env EASEMOB_CFG (absolute or relative)
          2) explicit `path` as given
          3) repo-root relative (based on this file location)
        """
        env_cfg = os.environ.get("EASEMOB_CFG")
        candidates = []
        def _append(p):
            from pathlib import Path as _P
            if p is None:
                return
            p = _P(p) if not isinstance(p, _P) else p
            candidates.append(p)
        # 1) env override
        if env_cfg:
            p = Path(env_cfg)
            _append(p if p.is_absolute() else Path.cwd() / p)
            _append(Path(__file__).resolve().parents[2] / env_cfg)
        # 2) explicit path
        if path:
            pp = Path(path)
            _append(pp if pp.is_absolute() else Path.cwd() / pp)
            _append(Path(__file__).resolve().parents[2] / pp)
        else:
            default_rel = Path("cfg/singlechat.yaml")
            _append(Path.cwd() / default_rel)
            _append(Path(__file__).resolve().parents[2] / default_rel)
        chosen = None
        for c in candidates:
            try:
                if Path(c).exists():
                    chosen = Path(c)
                    break
            except Exception:
                pass
        if not chosen:
            tried = "\n".join(str(c) for c in candidates)
            raise FileNotFoundError(f"Config file not found. Tried:\n{tried}\nSet EASEMOB_CFG to an absolute path or run from project root.")
        with open(chosen, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        # allow env substitution like ${FOO}
        def env_expand(v: Any) -> Any:
            if isinstance(v, str):
                return os.path.expandvars(v)
            if isinstance(v, dict):
                return {k: env_expand(x) for k, x in v.items()}
            if isinstance(v, list):
                return [env_expand(x) for x in v]
            return v
        raw = env_expand(raw)
        tr = TransportCfg(**raw["transport"]) 
        pr = ProtoCfg(**raw["proto"]) 
        wl = WorkloadCfg(**raw["workload"]) 
        hb = HeartbeatCfg(**raw["heartbeat"]) 
        sec_raw = raw.get("security", {})
        token_rest = None
        if sec_raw.get("token_rest"):
            token_rest = TokenRestCfg(**sec_raw["token_rest"])
        sec = SecurityCfg(
            auth=sec_raw.get("auth", "token"),
            token_source=sec_raw.get("token_source", "rest"),
            token_rest=token_rest,
            app_key=sec_raw.get("app_key"),
        )

        # parse optional token_service pieces from security.token_service
        ts = None
        if sec_raw.get("token_service"):
            ts = TokenServiceCfg(**sec_raw["token_service"])
        setattr(sec, "token_service", ts)
        rc = ReceiptsCfg(**raw.get("receipts", {}))
        run = _run_from_mapping(raw.get("run"))
        return Config(
            transport=tr,
            proto=pr,
            workload=wl,
            heartbeat=hb,
            security=sec,
            metrics=raw.get("metrics", {}),
            receipts=rc,
            run=run,
        )
