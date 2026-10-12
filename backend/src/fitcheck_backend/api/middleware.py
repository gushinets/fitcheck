import logging
from uuid import uuid4
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Scope, Receive, Send
from fitcheck_backend.api.errors import error_response

logger = logging.getLogger("fitcheck.http")
METHODS = {"GET", "POST", "PUT", "DELETE", "OPTIONS"}
HEADERS = {"content-type", "authorization", "x-csrf-token", "idempotency-key"}


class RequestBoundaryMiddleware:
    """Bounded JSON requests and exact-origin CORS around the complete HTTP boundary."""
    def __init__(self, app: ASGIApp, max_body_bytes: int, allowed_origins: list[str]):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allowed = origin in self.allowed_origins
        started = False
        status = 500

        async def boundary_send(message):
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                output = MutableHeaders(scope=message)
                output["X-Request-ID"] = request_id
                if scope['path'].startswith('/v1/'):
                    output['Cache-Control'] = 'no-store'
                output.add_vary_header("Origin")
                if allowed:
                    output["Access-Control-Allow-Origin"] = origin
                    output["Access-Control-Expose-Headers"] = "X-Request-ID"
                    if origin.startswith(("http://", "https://")):
                        output["Access-Control-Allow-Credentials"] = "true"
            await send(message)

        async def fail(status, code, message):
            await error_response(status, code, message, request_id)(scope, receive, boundary_send)

        try:
            if scope["method"] == "OPTIONS" and headers.get("access-control-request-method"):
                requested_headers = {h.strip().lower() for h in headers.get("access-control-request-headers", "").split(",") if h.strip()}
                if not allowed or headers["access-control-request-method"] not in METHODS or not requested_headers <= HEADERS:
                    await fail(403, "forbidden", "Origin, method or headers are not allowed")
                else:
                    await Response(status_code=204, headers={
                        "Access-Control-Allow-Methods": ", ".join(sorted(METHODS)),
                        "Access-Control-Allow-Headers": ", ".join(sorted(HEADERS)),
                        "Vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers",
                    })(scope, receive, boundary_send)
                return
            # Consume at most the configured bound before any route sees bytes.
            chunks = []
            size = 0
            while True:
                part = await receive()
                if part["type"] == "http.disconnect":
                    return
                chunk = part.get("body", b"")
                size += len(chunk)
                if size > self.max_body_bytes:
                    await fail(413, "body_too_large", "Request body is too large")
                    return
                chunks.append(chunk)
                if not part.get("more_body", False):
                    break
            if size and scope["method"] in {"POST", "PUT", "DELETE"} and headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                await fail(415, "unsupported_content_type", "Expected application/json")
                return
            consumed = False
            async def bounded_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()
            await self.app(scope, bounded_receive, boundary_send)
        except Exception:
            if started:
                # Response already started: abort rather than send a second envelope.
                raise
            await fail(500, "internal_error", "Internal server error")
        finally:
            logger.info("requestId=%s method=%s path=%s status=%s", request_id,
                        scope["method"], scope["path"], status)
