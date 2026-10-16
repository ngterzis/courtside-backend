import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send

ORIGIN_HEADER = b"x-origin-verify"

# deploy.yml probes the API Gateway and chat Function URLs directly, without
# going through CloudFront, so the health check can't require the header.
EXEMPT_PATHS = frozenset({"/api/health"})


class OriginVerifyMiddleware:
    """Reject requests that didn't come through CloudFront.

    CloudFront adds X-Origin-Verify to every origin request. Without this check
    the execute-api URL and the public chat Function URL could be called
    directly, skipping CloudFront's access logs. A no-op when no secret is
    configured (local development, tests).

    Pure ASGI rather than BaseHTTPMiddleware so the chat SSE stream passes
    through untouched.
    """

    def __init__(self, app: ASGIApp, secret: str | None) -> None:
        self.app = app
        self.secret = secret.encode() if secret else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.secret is None or scope["type"] != "http" or scope["path"] in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        received = dict(scope["headers"]).get(ORIGIN_HEADER, b"")
        if hmac.compare_digest(received, self.secret):
            await self.app(scope, receive, send)
            return

        body = json.dumps(
            {"error": "forbidden", "message": "Requests must go through CloudFront"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
