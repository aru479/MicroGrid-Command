"""Tiny thread-safe in-memory activity log (resets on restart).
For persistence use Catalyst Data Store - see README 'Optional extras'."""
from __future__ import annotations

import collections
import threading
import time

_LOG = collections.deque(maxlen=60)
_LOCK = threading.Lock()


def add(level: str, msg: str) -> None:
    with _LOCK:
        _LOG.appendleft({"t": time.strftime("%H:%M:%S"), "level": level, "msg": str(msg)[:300]})


def entries() -> list:
    with _LOCK:
        return list(_LOG)


def clear() -> None:
    with _LOCK:
        _LOG.clear()
