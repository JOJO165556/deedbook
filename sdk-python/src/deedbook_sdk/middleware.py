"""Middlewares d'intégration applicative ASGI et WSGI avec contrat zéro plantage."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deedbook_sdk.client import AuditClient

logger = logging.getLogger("deedbook_sdk.middleware")


class DeedbookASGIMiddleware:
    """Middleware ASGI (FastAPI, Starlette) pour la capture automatique d'audit.

    Contrat garanti : zéro plantage hôte. Même si l'audit échoue, la requête hôte
    n'est jamais interrompue ni ralentie.
    """

    def __init__(
        self,
        app: Any,
        client: AuditClient,
        *,
        exclude_paths: list[str] | None = None,
    ) -> None:
        self.app = app
        self.client = client
        self.exclude_paths = frozenset(exclude_paths or ["/health", "/metrics", "/favicon.ico"])

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        headers = dict(scope.get("headers", []))

        # Extraction ou génération transparente du correlation_id
        corr_id: str | None = None
        for key in (b"x-correlation-id", b"x-request-id"):
            if key in headers:
                corr_id = headers[key].decode("latin1", errors="ignore").strip()
                break

        if not corr_id:
            corr_id = f"corr-{uuid.uuid4().hex[:12]}"

        client_host = None
        client_info = scope.get("client")
        if client_info and isinstance(client_info, tuple) and len(client_info) > 0:
            client_host = str(client_info[0])

        status_code = 200

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            try:
                event = {
                    "action": f"http_{method.lower()}",
                    "correlation_id": corr_id,
                    "resource": {"type": "route", "name": path},
                    "result": {
                        "status": "success" if status_code < 400 else "failure",
                        "code": str(status_code),
                    },
                    "origin": {
                        "ip": client_host or "unknown",
                        "app": self.client.app_name,
                    },
                }
                self.client.emit(event)
            except Exception as exc:
                logger.error("DeedbookASGIMiddleware: exception interceptée : %s", exc)


class DeedbookWSGIMiddleware:
    """Middleware WSGI (Django, Flask) pour la capture automatique d'audit.

    Contrat garanti : zéro plantage hôte.
    """

    def __init__(
        self,
        app: Any,
        client: AuditClient,
        *,
        exclude_paths: list[str] | None = None,
    ) -> None:
        self.app = app
        self.client = client
        self.exclude_paths = frozenset(exclude_paths or ["/health", "/metrics", "/favicon.ico"])

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> Any:
        path = environ.get("PATH_INFO", "")
        if path in self.exclude_paths:
            return self.app(environ, start_response)

        method = environ.get("REQUEST_METHOD", "GET").upper()
        corr_id = environ.get("HTTP_X_CORRELATION_ID") or environ.get("HTTP_X_REQUEST_ID")
        if not corr_id:
            corr_id = f"corr-{uuid.uuid4().hex[:12]}"

        client_ip = environ.get("REMOTE_ADDR") or "unknown"
        status_code = 200

        def start_response_wrapper(
            status_line: str,
            response_headers: list[tuple[str, str]],
            exc_info: Any = None,
        ) -> Any:
            nonlocal status_code
            try:
                code_str = status_line.split()[0]
                status_code = int(code_str)
            except (IndexError, ValueError):
                status_code = 200
            return start_response(status_line, response_headers, exc_info)

        try:
            return self.app(environ, start_response_wrapper)
        finally:
            try:
                event = {
                    "action": f"http_{method.lower()}",
                    "correlation_id": corr_id,
                    "resource": {"type": "route", "name": path},
                    "result": {
                        "status": "success" if status_code < 400 else "failure",
                        "code": str(status_code),
                    },
                    "origin": {
                        "ip": client_ip,
                        "app": self.client.app_name,
                    },
                }
                self.client.emit(event)
            except Exception as exc:
                logger.error("DeedbookWSGIMiddleware: exception interceptée : %s", exc)
