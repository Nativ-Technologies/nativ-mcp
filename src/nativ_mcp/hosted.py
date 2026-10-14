"""Stateless Streamable HTTP hosting with per-request Nativ API keys."""

from __future__ import annotations

import os
import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

import httpx
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route

from nativ_mcp.client import DEFAULT_API_URL
from nativ_mcp.runtime import HostedRequest, hosted_request
from nativ_mcp.json_api import routes as json_routes


class APIKeyMiddleware:
    def __init__(self, app: Any, client: httpx.AsyncClient, artifact_store: Any, security: TransportSecuritySettings):
        self.app = app
        self.client = client
        self.artifact_store = artifact_store
        self.security = TransportSecurityMiddleware(security)
        self.slots = asyncio.Semaphore(4)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        if request.url.path == "/health":
            await self.app(scope, receive, send)
            return
        invalid = await self.security.validate_request(request)
        if invalid is not None:
            await invalid(scope, receive, send)
            return
        if request.url.path in ("/openapi.json", "/json-openapi.json"):
            await self.app(scope, receive, send)
            return
        keys = request.headers.getlist("x-api-key")
        authorization = request.headers.getlist("authorization")
        if len(keys) > 1 or len(authorization) > 1 or (keys and authorization):
            response = JSONResponse({"error": "Supply one API key using X-API-Key or Authorization: Bearer."}, status_code=400)
            await response(scope, receive, send)
            return
        api_key = keys[0].strip() if keys else ""
        if authorization:
            scheme, _, value = authorization[0].partition(" ")
            if scheme.lower() == "bearer":
                api_key = value.strip()
        if not re.fullmatch(r"nativ_[A-Za-z0-9_-]{1,250}", api_key):
            response = JSONResponse({"error": "A Nativ API key is required in X-API-Key or Authorization: Bearer."}, status_code=401)
            await response(scope, receive, send)
            return
        try:
            # Revalidate on every request so revoked/expired keys lose access
            # immediately. Never send the key to any user-supplied URL.
            verification = await self.client.get("/master-tm/stats", headers={"X-API-Key": api_key})
        except httpx.HTTPError:
            verification = None
        if verification is None or verification.status_code not in (200, 401, 403):
            response = JSONResponse({"error": "Nativ authentication is temporarily unavailable."}, status_code=503)
            await response(scope, receive, send)
            return
        if verification.status_code != 200:
            response = JSONResponse({"error": "Invalid or expired Nativ API key."}, status_code=401)
            await response(scope, receive, send)
            return
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=0.1)
        except asyncio.TimeoutError:
            response = JSONResponse({"error": "Server is busy. Retry shortly."}, status_code=429, headers={"Retry-After": "2"})
            await response(scope, receive, send)
            return
        token = hosted_request.set(HostedRequest(api_key=api_key, artifact_store=self.artifact_store))
        try:
            await self.app(scope, receive, send)
        finally:
            hosted_request.reset(token)
            self.slots.release()


def create_app(*, artifact_store: Any = None, api_transport: httpx.AsyncBaseTransport | None = None):
    from nativ_mcp.server import mcp

    public_url = os.getenv("NATIV_MCP_PUBLIC_URL", "http://localhost:8080/mcp")
    hostname = urlparse(public_url).netloc
    hosts = [hostname, "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    hosts += [h.strip() for h in os.getenv("NATIV_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    origins = [o.strip() for o in os.getenv("NATIV_MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)
    # SSE delivers progress on the active POST while a tool is running.
    # Stateless requests still work across replicas; the JSON tool adapter
    # remains application/json for connectors without MCP streaming support.
    app = mcp.streamable_http_app(json_response=False, stateless_http=True, transport_security=security)
    api_client = httpx.AsyncClient(
        base_url=os.getenv("NATIV_API_URL", DEFAULT_API_URL), timeout=15, follow_redirects=False,
        transport=api_transport,
    )
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with api_client, original_lifespan(application):
            yield

    app.router.lifespan_context = lifespan

    async def health(request: Request):
        return JSONResponse({"status": "ok", "transport": "streamable-http"})

    async def openapi(request: Request):
        return FileResponse(Path(__file__).with_name("rest-openapi.json"), media_type="application/json")

    app.routes.insert(0, Route("/health", health))
    app.routes.insert(0, Route("/openapi.json", openapi))
    # New routes reuse the existing tools without changing the MCP wire
    # protocol or the REST API schema already shared with customers.
    app.routes[:0] = json_routes(mcp, public_url.removesuffix("/mcp").rstrip("/"))
    app.add_middleware(APIKeyMiddleware, client=api_client, artifact_store=artifact_store, security=security)
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key", "Authorization", "Mcp-Protocol-Version", "Mcp-Session-Id", "Mcp-Method", "Mcp-Name"],
            expose_headers=["Mcp-Session-Id"],
        )
    return app


def production_app():
    from nativ_mcp.artifacts import GCSArtifactStore

    bucket = os.environ.get("NATIV_MCP_OUTPUT_BUCKET")
    account = os.environ.get("NATIV_MCP_SIGNING_ACCOUNT")
    if not bucket or not account:
        raise RuntimeError("Hosted MCP requires NATIV_MCP_OUTPUT_BUCKET and NATIV_MCP_SIGNING_ACCOUNT.")
    return create_app(artifact_store=GCSArtifactStore(bucket, account))


def main():
    import uvicorn

    uvicorn.run("nativ_mcp.hosted:production_app", factory=True, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
