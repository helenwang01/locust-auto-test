from __future__ import annotations
import logging
import time
from typing import Optional

import gevent

log = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, interval_ms: int, timeout_ms: int, send_func):
        self.interval = interval_ms / 1000.0
        self.timeout = timeout_ms / 1000.0
        self.send_func = send_func
        self._g = None
        self._last_pong: float = time.time()

    def start(self, payload_builder):
        def loop():
            while True:
                try:
                    payload = payload_builder()
                    self.send_func(payload)
                except Exception as e:
                    log.warning("heartbeat send failed: %s", e)
                gevent.sleep(self.interval)
        self._g = gevent.spawn(loop)

    def stop(self):
        if self._g:
            self._g.kill()
            self._g = None
