"""Credential-free, SDK-backed metadata only, isolated from executable tools."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server.lowlevel import Server
from mcp.types import Icon, ListToolsResult
from starlette.requests import Request
from starlette.responses import JSONResponse

PUBLIC_METHODS = frozenset({"initialize", "ping", "tools/list", "notifications/initialized"})
MAX_DISCOVERY_BODY = 64 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def create_discovery_app(catalog, security):
    async def list_tools(context, params):
        # The source is the static registration catalogue, never a customer API.
        return ListToolsResult(tools=await catalog.list_tools())

    # No call_tool, resource, prompt or account handlers exist on this server.
    server = Server(
        "nativ", version="0.5.1", title="Nativ",
        website_url="https://www.usenativ.com/integrations/mcp/",
        icons=[Icon(src="https://www.usenativ.com/apple-touch-icon.png", mime_type="image/png", sizes=["180x180"])],
        instructions="Inspect Nativ's public localisation capabilities. Executing any tool requires a Nativ API key. Connect at https://www.usenativ.com/integrations/mcp/.",
        on_list_tools=list_tools,
    )
    return server.streamable_http_app(
        json_response=True, stateless_http=True, transport_security=security,
        max_request_body_size=MAX_DISCOVERY_BODY,
    )


async def dispatch_discovery(app: Any, scope, receive, send):
    """Return True if handled; never pass consumed unauthenticated input onward."""
    request = Request(scope, receive)
    if scope.get("method") != "POST" or request.url.path != "/mcp":
        return False
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return False
    async def read_body():
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                raise ConnectionError("Client disconnected")
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_DISCOVERY_BODY:
                raise OverflowError("Request too large")
            body.extend(chunk)
            if not message.get("more_body", False):
                return bytes(body)
    try:
        body = await asyncio.wait_for(read_body(), timeout=5)
        payload = json.loads(body, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        await JSONResponse({"error": "Invalid discovery request."}, status_code=400)(scope, receive, send)
        return True
    except asyncio.TimeoutError:
        await JSONResponse({"error": "Discovery request timed out."}, status_code=408)(scope, receive, send)
        return True
    except OverflowError:
        await JSONResponse({"error": "Discovery request exceeds 64 KiB."}, status_code=413)(scope, receive, send)
        return True
    except ConnectionError:
        return True
    # A batch, forged header, nested call, unsupported method or notification
    # cannot reach the real application. The SDK validates allowed envelopes.
    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str) or payload["method"] not in PUBLIC_METHODS:
        return False
    replayed = False

    async def replay():
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}
        return await receive()

    await app(scope, replay, send)
    return True
