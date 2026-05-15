from __future__ import annotations
import os
import time
import random
import string


def gen_msg_id(prefix: str = "msg") -> str:
    now = int(time.time() * 1000)
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}-{now}-{rnd}"


def now_ms() -> int:
    return int(time.time() * 1000)
