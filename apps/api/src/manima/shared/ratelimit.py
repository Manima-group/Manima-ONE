"""Fixed-window limiter for abuse-prone endpoints (login, signup). SECURITY_ARCHITECTURE §7.

Counters live in Valkey/Redis so limits hold across API replicas; if Valkey is unreachable the
limiter falls back to a per-process window (still blocks brute force against one task).
"""

from __future__ import annotations

import hashlib
import threading
import time

from manima.settings import get_settings
from manima.shared.http import AppError

_local: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()
_client = None


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=0.3, socket_connect_timeout=0.3
        )
    return _client


def _key(scope: str, ident: str) -> str:
    return f"rl:{scope}:{hashlib.sha256(ident.encode()).hexdigest()[:32]}"


def hit(scope: str, ident: str, *, limit: int, window_s: int) -> None:
    """Count one attempt; raise 429 RATE_LIMITED once ``limit`` is exceeded within the window."""
    key = _key(scope, ident)
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_s, nx=True)
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
        retry = max(int(ttl), 1)
    except Exception:
        now = time.monotonic()
        with _lock:
            count, start = _local.get(key, (0, now))
            if now - start >= window_s:
                count, start = 0, now
            count += 1
            _local[key] = (count, start)
        retry = max(int(window_s - (now - start)), 1)
    if count > limit:
        raise AppError(
            429, "RATE_LIMITED", f"Too many attempts. Try again in {retry} seconds.", retry_after=retry
        )


def reset(scope: str, ident: str) -> None:
    key = _key(scope, ident)
    try:
        _redis().delete(key)
    except Exception:
        with _lock:
            _local.pop(key, None)
