"""Additive JSON-only HTTP access to existing Nativ MCP tools."""

from __future__ import annotations

import copy
import json
import logging
import math
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from nativ_mcp.runtime import hosted_request


logger = logging.getLogger(__name__)
MAX_JSON_BYTES = 1024 * 1024
URL_FIELDS = {"file_path", "image_path", "audio_path", "video_path", "subtitle_path", "glossary_path"}
# Only the new HTTP adapter accepts native arrays here. MCP's existing string
# arguments and serialized JSON remain unchanged.
ARRAY_FIELDS = {
    "localize_image": {"replacements": {
        "type": "object", "properties": {"original": {"type": "string"}, "translated": {"type": "string"}},
        "required": ["original", "translated"], "additionalProperties": False,
    }},
    "synthesize_audio": {"segments": {
        "type": "object", "properties": {
            "text": {"type": "string", "minLength": 1}, "start_ms": {"type": "integer", "minimum": 0},
            "end_ms": {"type": "integer", "minimum": 0}, "original": {"type": "string"},
        }, "required": ["text"], "additionalProperties": True,
    }},
}


def input_schema(tool: Any) -> dict:
    schema = copy.deepcopy(tool.input_schema)
    schema["additionalProperties"] = False
    for name, prop in schema.get("properties", {}).items():
        if name in URL_FIELDS:
            prop["description"] = "Public HTTPS media URL, including an unexpired presigned S3/GCS HTTPS URL."
            # Optional file arguments use an empty string for absence.
            prop["pattern"] = r"^https://" if name in schema.get("required", []) else r"^(https://|$)"
        if name in ARRAY_FIELDS.get(tool.name, {}):
            prop.clear()
            prop.update({"type": "array", "minItems": 1, "items": ARRAY_FIELDS[tool.name][name]})
    return schema


def openapi_schema(tools: list[Any], server_url: str) -> dict:
    paths = {}
    for tool in tools:
        paths[f"/tools/{tool.name}"] = {"post": {
            "operationId": tool.name,
            "summary": (tool.description or tool.name).split("\n", 1)[0],
            "description": (tool.description or "") + "\nHosted file arguments take public HTTPS URLs. Generated media is returned in artifacts as expiring download URLs.",
            "security": [{"NativAPIKey": []}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": input_schema(tool)}}},
            "responses": {
                "200": {"description": "Tool result with optional media download URLs.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolResponse"}}}},
                **{code: {"description": description, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}} for code, description in {
                    "400": "Invalid JSON", "401": "Invalid API key", "404": "Unknown tool",
                    "413": "JSON request too large", "415": "Use application/json", "422": "Invalid tool arguments",
                    "429": "Retry shortly", "502": "Tool execution failed", "503": "Authentication unavailable",
                }.items()},
            },
        }}
    return {
        "openapi": "3.1.0", "info": {
            "title": "Nativ JSON Tools API", "version": "0.3.0",
            "description": "JSON-only access to Nativ localization tools. Send public HTTPS media URLs and receive expiring download URLs. No multipart uploads or binary response bodies are required.",
        }, "servers": [{"url": server_url}], "paths": paths,
        "components": {
            "securitySchemes": {"NativAPIKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
            "schemas": {
                "Artifact": {"type": "object", "properties": {
                    "url": {"type": "string", "format": "uri"}, "filename": {"type": "string"},
                    "mime_type": {"type": "string"}, "expires_in_seconds": {"type": "integer"},
                }, "required": ["url", "filename", "mime_type", "expires_in_seconds"]},
                "ToolResponse": {"type": "object", "properties": {
                    "tool": {"type": "string"}, "text": {"type": "string"},
                    "data": {"type": ["object", "null"], "additionalProperties": True},
                    "artifacts": {"type": "array", "items": {"$ref": "#/components/schemas/Artifact"}},
                }, "required": ["tool", "text", "data", "artifacts"]},
                "Error": {"type": "object", "properties": {"error": {"type": "string"}}, "required": ["error"]},
            },
        },
    }


def _finite_numbers(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_numbers(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite_numbers(v) for v in value)
    return True


def routes(mcp: Any, server_url: str) -> list[Route]:
    async def schema(request: Request):
        return JSONResponse(openapi_schema(await mcp.list_tools(), server_url))

    async def invoke(request: Request):
        name = request.path_params["name"]
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        if name not in tools:
            return JSONResponse({"error": "Unknown tool."}, status_code=404)
        if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
            return JSONResponse({"error": "Use Content-Type: application/json."}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_JSON_BYTES:
                return JSONResponse({"error": "JSON requests are limited to 1 MiB. Send media as a HTTPS URL."}, status_code=413)
            body.extend(chunk)
        try:
            args = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return JSONResponse({"error": "Provide a valid JSON object."}, status_code=400)
        try:
            finite = _finite_numbers(args)
        except RecursionError:
            return JSONResponse({"error": "JSON nesting is too deep."}, status_code=400)
        if not isinstance(args, dict) or not finite:
            return JSONResponse({"error": "Provide a JSON object with finite numeric values."}, status_code=400)
        validator = Draft202012Validator(input_schema(tools[name]), format_checker=FormatChecker())
        error = next(validator.iter_errors(args), None)
        if error is not None:
            # Do not echo submitted signed URLs or arbitrary request data.
            location = ".".join(str(part) for part in error.absolute_path) or "request"
            return JSONResponse({"error": f"Invalid {location}: {error.validator} constraint."}, status_code=422)
        for field in ARRAY_FIELDS.get(name, {}):
            if field in args:
                args[field] = json.dumps(args[field], ensure_ascii=False)
        try:
            result = await mcp.call_tool(name, args)
            if result.is_error:
                raise RuntimeError("Tool returned an error")
        except Exception as exc:
            logger.error("JSON tool %s failed (%s)", name, type(exc).__name__)
            return JSONResponse({"error": "Tool execution failed. Check media URLs and arguments, then retry."}, status_code=502)
        remote = hosted_request.get()
        return JSONResponse({
            "tool": name,
            "text": "\n".join(c.text for c in result.content if hasattr(c, "text")),
            "data": result.structured_content,
            "artifacts": remote.artifacts if remote is not None else [],
        })

    return [Route("/json-openapi.json", schema), Route("/tools/{name}", invoke, methods=["POST"])]
