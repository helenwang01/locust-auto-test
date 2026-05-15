from __future__ import annotations

from loadtests.longconn.locustfile_chatroom_online import ChatroomCustomPayloadTemplate


def test_chatroom_custom_payload_template_renders_expected_json():
    tpl = ChatroomCustomPayloadTemplate.build(
        room_id="room_1",
        sender="yc1",
        body='{"kind":"ROOM_CHAT","data":"' + ("x" * 16) + '"}',
    )

    rendered = tpl.render(seq=7, ts_ms=1710000000123)

    assert rendered == (
        '{"type":"chatroom_custom","room_id":"room_1","sender":"yc1",'
        '"seq":7,"ts_ms":1710000000123,"body":"{\\"kind\\":\\"ROOM_CHAT\\",'
        '\\"data\\":\\"xxxxxxxxxxxxxxxx\\"}"}'
    )
