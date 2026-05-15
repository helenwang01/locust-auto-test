"""Locust 命令行运行时参数（与 config.yaml 解耦）。"""

from __future__ import annotations

from typing import Any


def cli_num_users(environment: Any) -> int | None:
    """读取本次运行的 ``-u`` / ``--users``（Locust 2.x 为 parsed_options.num_users）。"""
    parsed = getattr(environment, "parsed_options", None)
    if parsed is None:
        v = None
    else:
        v = getattr(parsed, "num_users", None)
    if isinstance(v, (int, float)) and int(v) >= 1:
        return int(v)

    # Web UI 场景：未在命令行传 -u 时，优先从 runner 读取当前目标并发。
    runner = getattr(environment, "runner", None)
    target = getattr(runner, "target_user_count", None) if runner is not None else None
    if isinstance(target, (int, float)) and int(target) >= 1:
        return int(target)

    # 次级兜底：当前在线用户数（通常在运行中可用）
    current = getattr(runner, "user_count", None) if runner is not None else None
    if isinstance(current, (int, float)) and int(current) >= 1:
        return int(current)
    return None


def require_cli_num_users(environment: Any, *, hint: str = "") -> int:
    n = cli_num_users(environment)
    if n is None:
        msg = "请在命令行指定并发用户数，例如：locust --headless -u 20 ..."
        if hint:
            msg += f" {hint}"
        raise RuntimeError(msg)
    return n
