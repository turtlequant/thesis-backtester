"""Cache and coalesce expensive numerical screening previews."""
from __future__ import annotations

import asyncio
import copy
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from typing import Any, Callable, Dict


_CACHE_TTL_SECONDS = 300.0
_CACHE_MAX_ENTRIES = 32
_LOCK = threading.RLock()
_CACHE: "OrderedDict[str, tuple[float, Dict[str, Any]]]" = OrderedDict()
_INFLIGHT: Dict[str, Future] = {}


def clear_screening_preview_cache() -> None:
    """Drop retained results after tests or an explicit invalidation."""
    with _LOCK:
        _CACHE.clear()


def _cached_value(key: str) -> Dict[str, Any] | None:
    now = time.monotonic()
    with _LOCK:
        item = _CACHE.get(key)
        if item is None:
            return None
        created_at, value = item
        if now - created_at > _CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return copy.deepcopy(value)


def _store_value(key: str, value: Dict[str, Any]) -> None:
    with _LOCK:
        _CACHE[key] = (time.monotonic(), copy.deepcopy(value))
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)


async def get_screening_preview(
    key: str,
    compute: Callable[[], Dict[str, Any]],
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Return one result per key, sharing an in-progress calculation."""
    if not force:
        cached = _cached_value(key)
        if cached is not None:
            return cached

    with _LOCK:
        future = _INFLIGHT.get(key)
        owner = future is None
        if owner:
            future = Future()
            _INFLIGHT[key] = future

    if not owner:
        shared = await asyncio.shield(asyncio.wrap_future(future))
        return copy.deepcopy(shared)

    try:
        value = await asyncio.to_thread(compute)
        _store_value(key, value)
        future.set_result(copy.deepcopy(value))
        return value
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _LOCK:
            if _INFLIGHT.get(key) is future:
                _INFLIGHT.pop(key, None)
