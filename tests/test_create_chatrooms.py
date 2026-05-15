from __future__ import annotations

"""
Pytest: batch-create chatrooms via REST (real HTTP).
- Uses existing config/fixtures (data_seed_config, rest_client).
- Idempotent-friendly: existing chatroom treated as success.

Run:
  pytest -q -s -m create_chatrooms tests/test_create_chatrooms.py
"""

import re
from typing import Any, Iterable

import pytest
import requests

from apis.token_api import get_token as http_get_token


def _fmt_user(prefix: str, idx: int, pad: int) -> str:
    if pad > 0:
        return f"{prefix}{idx:0{pad}d}"
    return f"{prefix}{idx}"


def _build_room_ids(seed_room_id: str, room_count: int) -> tuple[str, ...]:
    if room_count <= 0:
        raise RuntimeError(f"room_count must be > 0, got {room_count}")
    val = str(seed_room_id).strip()
    if not val:
        raise RuntimeError("data_seed.room_id is empty")

    m = re.match(r"^(.*?)(\d+)$", val)
    if m:
        prefix = m.group(1)
        start = int(m.group(2))
        return tuple(f"{prefix}{start + i}" for i in range(room_count))

    base = val if val.endswith("_") else f"{val}_"
    return tuple(f"{base}{i}" for i in range(1, room_count + 1))


def _chunk(items: Iterable[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise RuntimeError(f"chunk size must be > 0, got {size}")
    buf: list[str] = []
    chunks: list[list[str]] = []
    for item in items:
        buf.append(item)
        if len(buf) == size:
            chunks.append(buf)
            buf = []
    if buf:
        chunks.append(buf)
    return chunks


def _build_room_apply_plan(
    *,
    seed_room_id: str,
    room_count: int,
    user_prefix: str,
    user_pad: int,
    users_per_room: int,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    room_ids = _build_room_ids(seed_room_id, room_count)
    plan: list[tuple[str, tuple[str, ...]]] = []
    for idx, room_id in enumerate(room_ids, 1):
        start = ((idx - 1) * users_per_room) + 1
        end = idx * users_per_room
        usernames = tuple(_fmt_user(user_prefix, i, user_pad) for i in range(start, end + 1))
        plan.append((room_id, usernames))
    return tuple(plan)


def _extract_chatroom_id(resp_json: Any) -> str | None:
    if not isinstance(resp_json, dict):
        return None

    data = resp_json.get("data")
    if isinstance(data, dict):
        rid = data.get("id") or data.get("roomid")
        if rid is not None:
            return str(rid)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            rid = first.get("id") or first.get("roomid")
            if rid is not None:
                return str(rid)

    rid = resp_json.get("id") or resp_json.get("roomid")
    return str(rid) if rid is not None else None


def _is_idempotent_exists(status_code: int, body: Any, text: str) -> bool:
    if status_code not in (400, 409):
        return False
    low = (text or "").lower()
    if any(k in low for k in ("exist", "already", "duplicate", "has already")):
        return True
    if isinstance(body, dict):
        msg = str(body.get("message") or body.get("error") or body.get("desc") or "").lower()
        if any(k in msg for k in ("exist", "already", "duplicate")):
            return True
    return False


def _delete_chatroom_members(rest_client, room_id: str, members: list[str], *, timeout: float, batch_size: int = 50) -> int:
    if batch_size > 50:
        raise RuntimeError(f"batch_size must be <= 50, got {batch_size}")
    if not room_id:
        raise RuntimeError("room_id is empty")
    if not members:
        return 0

    deleted = 0
    batches = _chunk(members, batch_size)
    for idx, batch in enumerate(batches, 1):
        users = ",".join(batch)
        path = f"/chatrooms/{room_id}/users/{users}"
        try:
            resp = rest_client.request("DELETE", path, data="", timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(f"request error while deleting chatroom members room_id={room_id}, batch={idx}: {e}")

        # if not (200 <= resp.status_code < 300):
        #     pytest.fail(
        #         f"HTTP {resp.status_code} delete chatroom members failed "
        #         f"(room_id={room_id}, batch={idx}/{len(batches)}, size={len(batch)}): {resp.text[:300]}"
        #     )
        #
        # deleted += len(batch)
        # print(f"[delete-chatroom-members] room_id={room_id}, batch={idx}/{len(batches)}, size={len(batch)}")

    return deleted


@pytest.mark.create_chatrooms
def test_create_chatrooms_for_loadtest(config_center, data_seed_config, rest_client):
    room_count = config_center.chatroom_longconn_scene().room_count
    room_ids = _build_room_ids(data_seed_config.room_id, room_count)

    owner_override = config_center.cfg.get("locust", {}).get("chatroom_owner")
    owner = str(owner_override).strip() if owner_override else _fmt_user(
        data_seed_config.user_prefix, 1, data_seed_config.user_pad
    )
    timeout = data_seed_config.user_timeout_s
    max_users = 10000

    print(f"[create-chatrooms] target_count={len(room_ids)}, owner={owner}, room_id_start={room_ids[0]}")

    created = 0
    existed = 0
    for idx, room_id in enumerate(room_ids, 1):
        payload = {
            "roomid": room_id,
            "name": f"聊天室{room_id}",
            "maxusers": max_users,
            "owner": "tst",
            "members": [],
            "roles": {"admin": ["tst"]},
        }

        try:
            resp = rest_client.post("/chatrooms", json=payload, timeout=timeout)
        except requests.RequestException as e:
            pytest.fail(f"request error while creating chatroom={room_id}: {e}")

        ok = 200 <= resp.status_code < 300
        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None
        text = resp.text or ""

        if not ok and _is_idempotent_exists(resp.status_code, body, text):
            existed += 1
            ok = True

        if not ok:
            snippet = text[:300]
            pytest.fail(
                f"HTTP {resp.status_code} create chatroom failed "
                f"(idx={idx}/{len(room_ids)}, room_id={room_id}): {snippet}"
            )

        if 200 <= resp.status_code < 300:
            created += 1

        returned_room_id = _extract_chatroom_id(body)
        if returned_room_id and returned_room_id != room_id:
            pytest.fail(
                f"room id mismatch: request={room_id}, response={returned_room_id}, "
                f"idx={idx}/{len(room_ids)}"
            )

        if idx % 50 == 0 or idx == len(room_ids):
            print(
                f"[create-chatrooms] progress {idx}/{len(room_ids)}, "
                f"created={created}, existed={existed}"
            )

    assert created + existed == len(room_ids)
    print(
        f"[create-chatrooms] done total={len(room_ids)}, created={created}, "
        f"existed={existed}, owner={owner}"
    )


@pytest.mark.delete_chatroom_members
def test_delete_chatroom_members_in_batches(config_center, data_seed_config, rest_client):
    batch_size = int(config_center.cfg.get("locust", {}).get("delete_chatroom_members_batch", 50))
    timeout = data_seed_config.user_timeout_s
    scene = config_center.chatroom_longconn_scene()
    room_ids = _build_room_ids(data_seed_config.room_id, scene.room_count)

    if batch_size > 50:
        raise RuntimeError(f"delete_chatroom_members_batch must be <= 50, got {batch_size}")

    print(
        f"[delete-chatroom-members] rooms={len(room_ids)}, first_room={room_ids[0]}, "
        f"users_per_room={scene.users_per_room}, batch_size={batch_size}"
    )

    total_deleted = 0
    for idx, room_id in enumerate(room_ids, 1):
        start = (idx - 1) * scene.users_per_room + 1
        end = idx * scene.users_per_room
        members = [
            _fmt_user(data_seed_config.user_prefix, i, data_seed_config.user_pad)
            for i in range(start, end + 1)
        ]
        deleted = _delete_chatroom_members(rest_client, room_id, members, timeout=timeout, batch_size=batch_size)
        total_deleted += deleted
        print(
            f"[delete-chatroom-members] room_progress={idx}/{len(room_ids)}, "
            f"room_id={room_id}, members={members[0]}..{members[-1]}, deleted={deleted}"
        )

    assert total_deleted == len(room_ids) * scene.users_per_room


@pytest.mark.apply_chatroom
def test_apply_chatrooms_for_scene_users(config_center, data_seed_config, rest_client):
    timeout = data_seed_config.user_timeout_s
    scene = config_center.chatroom_longconn_scene()
    longconn_cfg = config_center.longconn()
    apply_plan = _build_room_apply_plan(
        seed_room_id=data_seed_config.room_id,
        room_count=scene.room_count,
        user_prefix=data_seed_config.user_prefix,
        user_pad=data_seed_config.user_pad,
        users_per_room=scene.users_per_room,
    )
    password = data_seed_config.user_password

    print(
        f"[apply-chatroom] rooms={scene.room_count}, users_per_room={scene.users_per_room}, "
        f"first_room={apply_plan[0][0]}, first_users={apply_plan[0][1][0]}..{apply_plan[0][1][-1]}"
    )

    applied = 0
    for room_idx, (room_id, usernames) in enumerate(apply_plan, 1):
        for user_idx, username in enumerate(usernames, 1):
            try:
                user_token = http_get_token(
                    username,
                    password,
                    url=longconn_cfg.token_url,
                    headers=longconn_cfg.token_headers,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                pytest.fail(f"request error while getting user token user={username}: {e}")
            except Exception as e:
                pytest.fail(f"get user token failed user={username}: {e}")

            try:
                resp = rest_client.post(
                    f"/chatrooms/{room_id}/apply",
                    authorization="Bearer " + user_token,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                pytest.fail(f"request error while applying chatroom room_id={room_id}, user={username}: {e}")

            if not (200 <= resp.status_code < 300):
                pytest.fail(
                    f"HTTP {resp.status_code} apply chatroom failed "
                    f"(room_id={room_id}, user={username}, room_progress={room_idx}/{len(apply_plan)}, "
                    f"user_progress={user_idx}/{len(usernames)}): {resp.text[:300]}"
                )
            applied += 1

        print(
            f"[apply-chatroom] room_progress={room_idx}/{len(apply_plan)}, room_id={room_id}, "
            f"users={usernames[0]}..{usernames[-1]}, applied={len(usernames)}"
        )

    assert applied == scene.room_count * scene.users_per_room
