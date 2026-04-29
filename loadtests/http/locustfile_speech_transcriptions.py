from __future__ import annotations

import sys
from pathlib import Path

from locust import constant, events, task
from locust.contrib.fasthttp import FastHttpUser

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from loadtests.common.config_center import LoadtestConfigCenter


_CENTER = LoadtestConfigCenter.get()
_HTTP_CFG = _CENTER.speech_http()

_DEFAULT_HOST = str(_HTTP_CFG.base_url).rstrip("/")
_DEFAULT_PATH = f"/api/sdk/v1/{_HTTP_CFG.org}/{_HTTP_CFG.app}/speech/transcriptions"
_DEFAULT_HEADERS = dict(getattr(_HTTP_CFG, "headers", {}) or {})

_HOT_USERNAME = str(_HTTP_CFG.username)
_HOT_FILE_ID = str(_HTTP_CFG.file_id)


@events.init_command_line_parser.add_listener
def _add_cli_args(parser):
    parser.add_argument(
        "--hot-username",
        type=str,
        default=_HOT_USERNAME,
        help="固定热点压测使用的 username。",
    )
    parser.add_argument(
        "--hot-file-id",
        type=str,
        default=_HOT_FILE_ID,
        help="固定热点压测使用的 fileId。",
    )


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    del kwargs
    global _HOT_USERNAME, _HOT_FILE_ID

    opts = getattr(environment, "parsed_options", None)
    if opts is None:
        return

    cli_username = str(getattr(opts, "hot_username", "") or "").strip()
    cli_file_id = str(getattr(opts, "hot_file_id", "") or "").strip()

    if cli_username:
        _HOT_USERNAME = cli_username
    if cli_file_id:
        _HOT_FILE_ID = cli_file_id


class SpeechTranscriptionsHotspotUser(FastHttpUser):
    abstract = False

    # Locust 要求在用户启动前有 host；命令行 --host 会覆盖这里。
    host = _DEFAULT_HOST

    # 让每个 user 不做额外等待，持续压单热点。
    wait_time = constant(0)

    network_timeout = 10.0
    connection_timeout = 5.0
    max_retries = 0
    insecure = True

    def on_start(self):
        self.path = _DEFAULT_PATH
        self.username = _HOT_USERNAME
        self.file_id = _HOT_FILE_ID
        self.headers = _DEFAULT_HEADERS.copy()

    @task
    def speech_transcriptions(self):
        payload = {
            "data": {
                "username": self.username,
                "fileId": self.file_id,
            }
        }

        self.client.post(
            self.path,
            json=payload,
            headers=self.headers,
            name="speech_transcriptions",
        )

