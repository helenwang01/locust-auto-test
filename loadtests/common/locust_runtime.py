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


def local_worker_count(environment: Any) -> int:
    """Return the number of local/distributed worker processes participating in this run."""
    parsed = getattr(environment, "parsed_options", None)
    processes = getattr(parsed, "processes", None) if parsed is not None else None
    if isinstance(processes, (int, float)) and int(processes) >= 1:
        return int(processes)

    runner = getattr(environment, "runner", None)
    worker_count = getattr(runner, "worker_count", None) if runner is not None else None
    if isinstance(worker_count, (int, float)) and int(worker_count) >= 1:
        return int(worker_count)
    return 1


def local_worker_index(environment: Any) -> int:
    """Return this worker's zero-based index, or 0 for single-process local runs."""
    runner = getattr(environment, "runner", None)
    worker_index = getattr(runner, "worker_index", 0) if runner is not None else 0
    if isinstance(worker_index, (int, float)) and int(worker_index) >= 0:
        return int(worker_index)
    if local_worker_count(environment) > 1:
        raise RuntimeError("Locust worker index is not assigned yet; cannot split users across worker processes")
    return 0


def global_user_index_for_worker(raw_idx: int, *, ring_total: int, worker_index: int, worker_count: int) -> int:
    """Map a per-worker Locust user counter to a unique 1-based global user index."""
    if raw_idx < 1:
        raise ValueError("raw_idx must be >= 1")
    if ring_total < 1:
        raise ValueError("ring_total must be >= 1")
    if worker_count < 1:
        raise ValueError("worker_count must be >= 1")
    if worker_index < 0 or worker_index >= worker_count:
        raise ValueError("worker_index must be in 0..worker_count-1")
    return (((raw_idx - 1) * worker_count + worker_index) % ring_total) + 1

