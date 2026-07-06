from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

_ORIGINAL_GETADDRINFO: Callable[..., list[tuple[Any, ...]]] | None = None


def prefer_ipv4_addresses() -> None:
    global _ORIGINAL_GETADDRINFO
    if _ORIGINAL_GETADDRINFO is not None:
        return

    _ORIGINAL_GETADDRINFO = socket.getaddrinfo

    def getaddrinfo_ipv4_first(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        results = _ORIGINAL_GETADDRINFO(*args, **kwargs)
        return sorted(results, key=lambda item: 0 if item[0] == socket.AF_INET else 1)

    socket.getaddrinfo = getaddrinfo_ipv4_first
