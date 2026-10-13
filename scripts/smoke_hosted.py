"""Live MCP smoke test. Set NATIV_API_KEY; --media adds an unbilled preview."""

import argparse
import asyncio
import os
import re

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from nativ_mcp.files import download_media


async def check(base: str, media: bool):
    key = os.environ["NATIV_API_KEY"]
    base = base.rstrip("/").removesuffix("/mcp")
    async with httpx.AsyncClient(timeout=30) as http:
        health = await http.get(base + "/health")
        health.raise_for_status()
        schema = await http.get(base + "/openapi.json")
        schema.raise_for_status()
        assert schema.json()["components"]["securitySchemes"]["NativAPIKey"]["name"] == "X-API-Key"
        json_schema = await http.get(base + "/json-openapi.json")
        json_schema.raise_for_status()
        assert "/tools/localize_image" in json_schema.json()["paths"]
        json_result = await http.post(base + "/tools/get_languages", headers={"X-API-Key": key}, json={})
        json_result.raise_for_status()
        assert json_result.json()["tool"] == "get_languages"
        assert json_result.json()["artifacts"] == []
        assert (await http.post(base + "/mcp", json={})).status_code == 401
        assert (await http.post(base + "/mcp", headers={"X-API-Key": "nativ_invalid"}, json={})).status_code == 401
    async with httpx2.AsyncClient(headers={"X-API-Key": key}, timeout=180) as http:
        async with Client(streamable_http_client(base + "/mcp", http_client=http)) as client:
            tools = (await client.list_tools()).tools
            resources = (await client.list_resources()).resources
            result = await client.call_tool("get_languages", {})
            assert not result.is_error, "Read-only language tool failed"
            print(f"MCP passed: {len(tools)} tools, {len(resources)} resources, valid authentication, invalid keys rejected")
            if media:
                async with httpx.AsyncClient(timeout=30) as api:
                    voices = await api.get(
                        os.getenv("NATIV_API_URL", "https://api.usenativ.com") + "/audio/voices",
                        params={"language_code": "en-US"}, headers={"X-API-Key": key},
                    )
                    voices.raise_for_status()
                    voice = voices.json()["voices"][0]
                preview = await client.call_tool("preview_voice", {
                    "voice_id": voice["id"], "language_code": "en-US", "text": "Nativ test.",
                })
                assert not preview.is_error, "Hosted preview failed"
                text = "\n".join(c.text for c in preview.content if hasattr(c, "text"))
                match = re.search(r"https://storage\.googleapis\.com/[^\s)]+", text)
                assert match, "No signed download URL returned"
                data, _, _ = await download_media(match.group(0), 5 * 1024 * 1024)
                assert data[:4] == b"RIFF", "Downloaded preview is not WAV audio"
                print(f"Media passed: preview, private upload, IAM signing, HTTPS download ({len(data)} bytes)")
                async with httpx.AsyncClient(timeout=180) as json_http:
                    result = await json_http.post(base + "/tools/preview_voice", headers={"X-API-Key": key}, json={
                        "voice_id": voice["id"], "language_code": "en-US", "text": "Nativ test.",
                    })
                    result.raise_for_status()
                    artifact = result.json()["artifacts"][0]
                    assert artifact["expires_in_seconds"] == 3600
                    data, _, _ = await download_media(artifact["url"], 5 * 1024 * 1024)
                    assert data[:4] == b"RIFF"
                    print("JSON API passed: application/json request and structured media download URLs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--media", action="store_true")
    args = parser.parse_args()
    asyncio.run(check(args.url, args.media))
