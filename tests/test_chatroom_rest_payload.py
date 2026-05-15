from __future__ import annotations

from loadtests.longconn.locustfile_chatroom_online_rest import (
    build_chatroom_custom_rest_headers,
    build_chatroom_custom_rest_payload,
)


def test_build_chatroom_custom_rest_payload_returns_expected_shape():
    payload = build_chatroom_custom_rest_payload(
        room_id="309162229694468",
        sender="yc1",
        app_key="easemob-demo#wang01",
        message="room custom message",
    )

    assert payload == {
        "from": "yc1",
        "to": ["309162229694468"],
        "type": "custom",
        "body": {
            "customEvent": "custom_event",
            "customExts": {
                "ext_key1": "room custom message",
            },
        },
    }


def test_build_chatroom_custom_rest_headers_returns_expected_shape():
    headers = build_chatroom_custom_rest_headers()

    assert headers == {
        "source": "kefu",
    }
