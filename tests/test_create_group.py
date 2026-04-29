from __future__ import annotations
"""
Pytest: create one group with 200 members via REST (real HTTP).
- Members: yc1..yc200
- Owner: yc1
"""

import time
from typing import Any, Dict, List, Optional

import pytest
import requests

from apis.group_api import create_group
from utils.config import load_yaml_config


def _pick(d: Dict[str, Any], keys, default):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _extract_group_id(resp_json: Any) -> Optional[str]:
    if not isinstance(resp_json, dict):
        return None

    if isinstance(resp_json.get("data"), dict):
        data = resp_json["data"]
        gid = data.get("groupid") or data.get("id")
        if gid is not None:
            return str(gid)

    if isinstance(resp_json.get("data"), list) and resp_json["data"]:
        first = resp_json["data"][0]
        if isinstance(first, dict):
            gid = first.get("groupid") or first.get("id")
            if gid is not None:
                return str(gid)

    gid = resp_json.get("groupid") or resp_json.get("id")
    return str(gid) if gid is not None else None


@pytest.mark.create_group
class TestCreateGroup:
    def test_create_one_group_with_200_members(self):
        cfg = load_yaml_config()
        rest_sec: Dict[str, Any] = cfg.get("rest", {}) if isinstance(cfg, dict) else {}
        loc: Dict[str, Any] = cfg.get("locust", {}) if isinstance(cfg, dict) else {}

        missing = [k for k in ("rest_url", "org_name", "app_name", "authorization") if not rest_sec.get(k)]
        if missing:
            pytest.fail("config/.env 缺失字段: " + ", ".join(f"rest.{k}" for k in missing))

        owner = "yc1"
        members: List[str] = [f"yc{i}" for i in range(1, 201)]
        assert len(members) == 200
        assert owner in members

        timeout = float(_pick(loc, ["user_timeout", "timeout"], 15))
        title = f"测试test{int(time.time())}"

        payload: Dict[str, Any] = {
            "members": members,
            "mute": False,
            "scale": "large",
            "allowinvites": True,
            "max_users": 10000,
            "public": True,
            "invite_need_confirm": True,
            "mute_duration": 0,
            "debut_msg_num": 0,
            "custom": "string",
            "members_only": False,
            "owner": owner,
            "description": "RST created group",
            "title": title,
            "roles": {
                "admin": ["yc2"],
            },
        }

        try:
            resp = create_group(payload, str(rest_sec["authorization"]), timeout=timeout)
        except requests.HTTPError as e:
            resp = e.response
        except requests.RequestException as e:
            pytest.fail(f"Request error while creating group: {e}")

        assert resp is not None, "response is None"
        ok = 200 <= resp.status_code < 300

        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None

        if not ok:
            snippet = (resp.text or "")[:300]
            pytest.fail(f"HTTP {resp.status_code} create group failed: {snippet}")

        group_id = _extract_group_id(body)
        assert group_id, f"group id missing in response: {body}"
        print(f"[create-group] created group_id={group_id}, owner={owner}, members={len(members)}")
