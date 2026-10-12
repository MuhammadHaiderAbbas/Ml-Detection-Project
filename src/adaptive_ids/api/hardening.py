"""HTTP hardening: security headers on every response and request-body size limits.

Both are plain ASGI middleware so they also cover static files and error responses.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.exceptions import HTTPException

# The web app loads only its own scripts and styles; React and the charts set inline
# style attributes, hence 'unsafe-inline' for styles only. Nothing may frame the app.
WEB_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
           "frame-ancestors 'none'")
API_CSP = "default-src 'none'; frame-ancestors 'none'"

UPLOAD_PATHS = ("/api/imports", "/api/imports/preview")
JSON_BODY_LIMIT = 1024 * 1024  # 1 MiB is far above any legitimate JSON request


class SecurityHeaders:
    def __init__(self, app: Any, *, hsts: bool = False) -> None:
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api/")

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"server",)]
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=(), usb=()",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-origin",
                    b"content-security-policy": (API_CSP if is_api else WEB_CSP).encode(),
                }
                if is_api:
                    extra[b"cache-control"] = b"no-store"
                if self.hsts:
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in extra.items() if k not in present or k == b"cache-control"]
                if is_api:
                    headers = [(k, v) for k, v in headers if not (k.lower() == b"cache-control" and v != b"no-store")]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimit:
    """Reject request bodies above the limit with 413 before the application reads them.

    Uploads get ``upload_limit`` bytes (the configured maximum file size plus room for the
    form fields); every other request gets 1 MiB. Bodies without a Content-Length header are
    counted as they stream in.
    """

    def __init__(self, app: Any, *, upload_limit: int, default_limit: int = JSON_BODY_LIMIT) -> None:
        self.app, self.upload_limit, self.default_limit = app, upload_limit, default_limit

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self.upload_limit if scope["path"] in UPLOAD_PATHS else self.default_limit
        length = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if length is not None and length.isdigit() and int(length) > limit:
            await _too_large(send, limit)
            return
        seen = 0
        responded = False

        async def limited_receive() -> dict:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: dict) -> None:
            nonlocal responded
            if message["type"] == "http.response.start":
                responded = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not responded:
                await _too_large(send, limit)


class _BodyTooLarge(HTTPException):
    """An HTTPException so FastAPI's body parsing re-raises it as 413 instead of a generic 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="request body too large")


async def _too_large(send: Any, limit: int) -> None:
    body = json.dumps({"detail": f"request body too large (limit {limit // (1024 * 1024)} MiB)"}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
