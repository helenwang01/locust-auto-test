from __future__ import annotations

from tests.test_create_chatrooms import _build_room_apply_plan


def test_build_room_apply_plan_maps_seed_users_to_each_room_in_order():
    plan = _build_room_apply_plan(
        seed_room_id="room_1",
        room_count=2,
        user_prefix="yc",
        user_pad=0,
        users_per_room=3,
    )

    assert plan == (
        ("room_1", ("yc1", "yc2", "yc3")),
        ("room_2", ("yc4", "yc5", "yc6")),
    )
