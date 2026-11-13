"""Loopback guard: keep the local server from being driven by other web pages or hosts.

Conclave has no login. The guard is what stops a web page open in the same browser
(cross-site requests) or a DNS-rebinding page from spending provider calls or reading
stored runs, and what makes a ``--host 0.0.0.0`` mistake visible instead of silent.

It is a plain ASGI middleware, so request cancellation reaches the handlers unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD"})
ALLOWED_HOSTS_ENV = "CONCLAVE_ALLOWED_HOSTS"


def allowed_hosts_from_env() -> list[str]:
    raw = os.getenv(ALLOWED_HOSTS_ENV, "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _hostname(netloc: str) -> str:
    """Host part of a ``Host`` header or URL netloc, without the port. IPv6 keeps brackets."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        end = netloc.find("]")
        return netloc[: end + 1] if end != -1 else netloc
    return netloc.rsplit(":", 1)[0] if ":" in netloc else netloc


def _same_origin(origin: str, host: str) -> bool:
    """True when the ``Origin`` header names exactly the ``Host`` it was sent to."""
    try:
        return urlsplit(origin).netloc.lower() == host.strip().lower()
    except ValueError:  # e.g. "http://[::1" is malformed, so it cannot match
        return False


class LoopbackGuardMiddleware:
    """Reject requests whose ``Host`` is not loopback or explicitly allowed.

    Every HTTP method must carry an allowed ``Host`` (this also blocks DNS rebinding
    reads of stored runs). Methods other than GET and HEAD must also have an ``Origin``
    header that is absent, or identical to the ``Host`` header.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str] | None = None) -> None:
        self.app = app
        extra = allowed_hosts_from_env() if allowed_hosts is None else list(allowed_hosts)
        self.allowed = LOOPBACK_HOSTS | {_hostname(item) for item in extra}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        reason = None
        if not host or _hostname(host) not in self.allowed:
            reason = "Host not allowed. Conclave only serves loopback addresses."
        elif scope["method"] not in SAFE_METHODS:
            origin = headers.get("origin")
            if origin is not None and not _same_origin(origin, host):
                reason = "Cross-origin request refused."

        if reason is not None:
            await JSONResponse({"detail": reason}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)
