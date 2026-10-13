import asyncio
import base64
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from nativ_mcp.files import download_media, read_file, save_base64
from nativ_mcp.hosted import create_app
from nativ_mcp.runtime import HostedRequest, hosted_request
from nativ_mcp.server import _get_client, mcp


class MemoryArtifacts:
    def __init__(self):
        self.files = []

    async def save(self, data, filename, content_type):
        self.files.append((data, filename, content_type))
        return f"https://storage.example.com/{filename}"


class HostedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.verified_keys = []

        async def authenticate(request):
            key = request.headers.get("X-API-Key")
            self.verified_keys.append(key)
            if key == "nativ_unavailable":
                return httpx.Response(500)
            return httpx.Response(200 if key in ("nativ_alice", "nativ_bob") else 401, json={})

        self.store = MemoryArtifacts()
        self.app = create_app(artifact_store=self.store, api_transport=httpx.MockTransport(authenticate))
        self.ready = asyncio.Event()
        self.stop = asyncio.Event()

        async def run_lifespan():
            async with self.app.router.lifespan_context(self.app):
                self.ready.set()
                await self.stop.wait()

        self.lifespan_task = asyncio.create_task(run_lifespan())
        await self.ready.wait()
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://localhost:8080")

    async def asyncTearDown(self):
        await self.http.aclose()
        self.stop.set()
        await self.lifespan_task

    async def rpc(self, method, params=None, key="nativ_alice", bearer=False):
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
            "Authorization" if bearer else "X-API-Key": f"Bearer {key}" if bearer else key,
        }
        return await self.http.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
        })

    async def test_health_and_auth_fail_closed(self):
        self.assertEqual((await self.http.get("/health")).status_code, 200)
        schema = (await self.http.get("/openapi.json")).json()
        self.assertEqual(schema["servers"][0]["url"], "https://api.usenativ.com")
        self.assertEqual(schema["components"]["securitySchemes"]["NativAPIKey"]["name"], "X-API-Key")
        for key, status in (("", 401), ("nativ_bad", 401), ("nativ_unavailable", 503)):
            with self.subTest(key=key):
                response = await self.rpc("tools/list", key=key)
                self.assertEqual(response.status_code, status)
        with patch.dict(os.environ, {"NATIV_API_KEY": "nativ_alice"}):
            self.assertEqual((await self.http.post("/mcp", json={})).status_code, 401)
        self.assertIsNone(hosted_request.get())

    async def test_discovery_and_bearer_api_key(self):
        response = await self.rpc("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("mcp-session-id", response.headers)
        for method, field in (("tools/list", "tools"), ("resources/list", "resources"), ("prompts/list", "prompts")):
            response = await self.rpc(method, bearer=True)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["result"][field])

    async def test_current_sdk_connects_over_http(self):
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), headers={"X-API-Key": "nativ_alice"},
        ) as http_client:
            async with Client(streamable_http_client("http://localhost:8080/mcp", http_client=http_client)) as client:
                self.assertTrue((await client.list_tools()).tools)
                with patch("nativ_mcp.client.NativClient.get_languages", AsyncMock(return_value={"languages": []})) as upstream:
                    await client.call_tool("get_languages", {})
                    upstream.assert_awaited_once()

    async def test_concurrent_calls_and_resources_keep_their_own_keys(self):
        async def languages(client):
            await asyncio.sleep(0.01)
            return {"languages": [{"language": client.headers["X-API-Key"], "language_code": "en"}]}

        with patch("nativ_mcp.client.NativClient.get_languages", languages):
            responses = []
            for _ in range(4):
                # Stay below the four-request capacity limit; concurrency
                # isolation is independent of overload rejection.
                responses.extend(await asyncio.gather(
                    self.rpc("tools/call", {"name": "get_languages", "arguments": {}}, key="nativ_alice"),
                    self.rpc("tools/call", {"name": "get_languages", "arguments": {}}, key="nativ_bob"),
                    self.rpc("resources/read", {"uri": "nativ://languages"}, key="nativ_bob"),
                ))
        for index, response in enumerate(responses):
            self.assertEqual(response.status_code, 200, response.text)
            text = response.json()["result"]["contents" if index % 3 == 2 else "content"][0]["text"]
            self.assertIn("nativ_alice" if index % 3 == 0 else "nativ_bob", text)
            self.assertNotIn("nativ_bob" if index % 3 == 0 else "nativ_alice", text)
        self.assertIsNone(hosted_request.get())

    async def test_revocation_checked_on_each_request(self):
        self.assertEqual((await self.rpc("tools/list")).status_code, 200)
        self.assertEqual((await self.rpc("tools/list")).status_code, 200)
        self.assertEqual(self.verified_keys, ["nativ_alice", "nativ_alice"])

    async def test_rejects_duplicate_keys_bad_host_and_bad_origin(self):
        response = await self.http.post("/mcp", headers=[("X-API-Key", "nativ_alice"), ("X-API-Key", "nativ_bob")], json={})
        self.assertEqual(response.status_code, 400)
        for header, status in (({"Host": "attacker.example"}, 421), ({"Origin": "https://attacker.example"}, 403)):
            response = await self.http.post("/mcp", headers={"X-API-Key": "nativ_alice", **header}, json={})
            self.assertEqual(response.status_code, status)

    async def test_media_output_and_local_files_blocked_over_http(self):
        with patch("nativ_mcp.client.NativClient.preview_voice", AsyncMock(return_value={"audio_base64": base64.b64encode(b"wav").decode()})):
            response = await self.rpc("tools/call", {"name": "preview_voice", "arguments": {"voice_id": "voice", "output_path": "/etc/not-written.wav"}})
        self.assertIn("https://storage.example.com/not-written.wav", response.text)
        self.assertEqual(self.store.files, [(b"wav", "not-written.wav", "audio/x-wav")])
        response = await self.rpc("tools/call", {"name": "register_video", "arguments": {"file_path": "/etc/passwd"}})
        self.assertTrue(response.json()["result"]["isError"])
        self.assertIn("HTTPS", response.text)

    async def test_subtitle_outputs_download_urls_without_writing_local_paths(self):
        payload = {"languages": [{"language": "French", "language_code": "fr", "srt_utf8": "1\n00:00:00,000 --> 00:00:01,000\nBonjour\n", "cues": []}]}
        with patch("nativ_mcp.media_tools.hosted_request", hosted_request), patch(
            "nativ_mcp.files.download_media", AsyncMock(return_value=(b"subtitle", "source.srt", "application/x-subrip")),
        ), patch("nativ_mcp.client.NativClient.localize_subtitles", AsyncMock(return_value=payload)):
            response = await self.rpc("tools/call", {"name": "localize_subtitles", "arguments": {
                "target_language_codes": "fr", "subtitle_path": "https://cdn.example.com/source.srt",
                "output_dir": "/etc/must-not-write",
            }})
        self.assertIn("https://storage.example.com/fr.srt", response.text)
        self.assertEqual(self.store.files[0][1:], ("fr.srt", "application/x-subrip"))

    async def test_cors_preflight_for_configured_client(self):
        with patch.dict(os.environ, {"NATIV_MCP_ALLOWED_ORIGINS": "https://client.example"}):
            app = create_app(artifact_store=self.store)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8080") as client:
            response = await client.options("/mcp", headers={
                "Origin": "https://client.example", "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key,mcp-protocol-version",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://client.example")

    async def test_json_schema_is_additive_and_preserves_mcp_argument_types(self):
        schema = (await self.http.get("/json-openapi.json")).json()
        self.assertEqual(len(schema["paths"]), 21)
        for path in schema["paths"].values():
            self.assertEqual(set(path["post"]["requestBody"]["content"]), {"application/json"})
        props = schema["paths"]["/tools/localize_image"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
        self.assertEqual(props["replacements"]["type"], "array")
        tools = (await self.rpc("tools/list")).json()["result"]["tools"]
        image = next(t for t in tools if t["name"] == "localize_image")
        self.assertEqual(image["inputSchema"]["properties"]["replacements"]["type"], "string")
        old_schema = (await self.http.get("/openapi.json")).json()
        self.assertEqual(old_schema["servers"][0]["url"], "https://api.usenativ.com")
        self.assertIn("multipart/form-data", old_schema["paths"]["/audio/transcribe"]["post"]["requestBody"]["content"])

    async def test_json_image_url_input_and_structured_download_output(self):
        replacement = [{"original": "Hello", "translated": "Bonjour"}]
        with patch("nativ_mcp.files.download_media", AsyncMock(return_value=(b"image", "source.png", "image/png"))) as download, patch(
            "nativ_mcp.client.NativClient.localize_image", AsyncMock(return_value={"images": [{"image_base64": base64.b64encode(b"localized").decode()}]}),
        ) as upstream:
            response = await self.http.post("/tools/localize_image", headers={"X-API-Key": "nativ_alice"}, json={
                "image_path": "https://cdn.example.com/source.png", "replacements": replacement, "target_language_code": "fr",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/json")
        result = response.json()
        self.assertEqual(result["artifacts"], [{"url": "https://storage.example.com/source.fr.png", "filename": "source.fr.png", "mime_type": "image/png", "expires_in_seconds": 3600}])
        self.assertEqual(upstream.call_args.args, (b"image", "source.png", "image/png"))
        self.assertEqual(json.loads(upstream.call_args.kwargs["replacements_json"]), replacement)
        download.assert_awaited_once()
        self.assertNotIn("image_base64", response.text)

    async def test_json_concurrent_callers_keep_keys_and_artifacts_separate(self):
        seen = []

        async def preview(client, voice_id, **kwargs):
            seen.append(client.headers["X-API-Key"])
            await asyncio.sleep(0.01)
            return {"audio_base64": base64.b64encode(b"wav").decode()}

        with patch("nativ_mcp.client.NativClient.preview_voice", preview):
            responses = await asyncio.gather(*[
                self.http.post("/tools/preview_voice", headers={"X-API-Key": key}, json={"voice_id": "voice", "output_path": name + ".wav"})
                for key, name in [("nativ_alice", "alice"), ("nativ_bob", "bob")]
            ])
        self.assertCountEqual(seen, ["nativ_alice", "nativ_bob"])
        for response, name in zip(responses, ["alice", "bob"]):
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()["artifacts"]), 1)
            self.assertEqual(response.json()["artifacts"][0]["filename"], name + ".wav")
        self.assertIsNone(hosted_request.get())

    async def test_json_validation_authentication_and_body_limits(self):
        auth = {"X-API-Key": "nativ_alice"}
        self.assertEqual((await self.http.post("/tools/get_languages", json={})).status_code, 401)
        cases = [
            ("/tools/unknown", {}, 404), ("/tools/get_languages", {"extra": "x"}, 422),
            ("/tools/transcribe_audio", {"file_path": "/etc/passwd"}, 422),
            ("/tools/transcribe_audio", {}, 422), ("/tools/get_languages", [], 400),
        ]
        for path, body, status in cases:
            response = await self.http.post(path, headers=auth, json=body)
            self.assertEqual(response.status_code, status, response.text)
        response = await self.http.post("/tools/get_languages", headers={**auth, "Content-Type": "application/json"}, content=b"not json")
        self.assertEqual(response.status_code, 400)
        response = await self.http.post("/tools/get_languages", headers={**auth, "Content-Type": "text/plain"}, content=b"{}")
        self.assertEqual(response.status_code, 415)
        response = await self.http.post("/tools/get_languages", headers={**auth, "Content-Type": "application/json"}, content=b" " * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    async def test_json_tool_failure_does_not_echo_signed_urls(self):
        with patch("nativ_mcp.client.NativClient.get_languages", AsyncMock(side_effect=RuntimeError("https://cdn.example.com/?secret=must-not-echo"))):
            response = await self.http.post("/tools/get_languages", headers={"X-API-Key": "nativ_alice"}, json={})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("must-not-echo", response.text)


class FileTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_reads_and_writes_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sample.wav")
            result = await save_base64(base64.b64encode(b"audio").decode(), path)
            self.assertEqual(result, path)
            self.assertEqual((await read_file(path))[0], b"audio")
        with patch.dict(os.environ, {"NATIV_API_KEY": "nativ_stdio"}):
            self.assertEqual(_get_client().headers["X-API-Key"], "nativ_stdio")

    async def test_download_pins_dns_and_never_sends_nativ_key(self):
        seen = []

        async def serve(request):
            seen.append(request)
            return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"image")

        original_client = httpx.AsyncClient
        with patch("nativ_mcp.files._public_address", AsyncMock(return_value="8.8.8.8")), patch(
            "nativ_mcp.files.httpx.AsyncClient", side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(serve), **kwargs),
        ):
            token = hosted_request.set(HostedRequest("nativ_secret", MemoryArtifacts()))
            try:
                data, name, mime = await read_file("https://cdn.example.com/image.png?signature=secret")
            finally:
                hosted_request.reset(token)
        self.assertEqual((data, name, mime), (b"image", "image.png", "image/png"))
        self.assertEqual(seen[0].url.host, "8.8.8.8")
        self.assertEqual(seen[0].headers["Host"], "cdn.example.com")
        self.assertEqual(seen[0].extensions["sni_hostname"], "cdn.example.com")
        self.assertNotIn("x-api-key", seen[0].headers)

    async def test_private_dns_and_invalid_urls_rejected(self):
        from nativ_mcp.files import _public_address

        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"):
            with patch("asyncio.BaseEventLoop.getaddrinfo", AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 443))])):
                with self.assertRaisesRegex(RuntimeError, "public IP"):
                    await _public_address("cdn.example.com", 443)
        for url in ("/etc/passwd", "file:///etc/passwd", "http://cdn.example.com/file", "https://user:pass@cdn.example.com/file", "https://cdn.example.com:8443/file"):
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                await download_media(url, 100)

    async def test_redirects_revalidated_and_size_limit_streamed(self):
        original_client = httpx.AsyncClient

        def serve(request):
            if request.url.path == "/redirect":
                return httpx.Response(302, headers={"Location": "http://169.254.169.254/metadata"})
            return httpx.Response(200, content=b"too long")

        with patch("nativ_mcp.files._public_address", AsyncMock(return_value="8.8.8.8")), patch(
            "nativ_mcp.files.httpx.AsyncClient", side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(serve), **kwargs),
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                await download_media("https://cdn.example.com/redirect", 100)
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                await download_media("https://cdn.example.com/file", 2)


class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_iam_signing_uses_cloud_platform_scope_and_unique_objects(self):
        from nativ_mcp.artifacts import GCSArtifactStore

        credentials = MagicMock(valid=True, token="test-token")
        client = MagicMock()
        client._credentials = credentials
        client.bucket.return_value.blob.return_value.generate_signed_url.return_value = "https://storage.example.com/signed"
        with patch("google.auth.default", return_value=(credentials, "test-project")) as auth, patch(
            "google.cloud.storage.Client", return_value=client,
        ):
            store = GCSArtifactStore("test-bucket", "mcp@test-project.iam.gserviceaccount.com")
            self.assertEqual(await store.save(b"output", "output.wav", "audio/wav"), "https://storage.example.com/signed")
            await store.save(b"output", "output.wav", "audio/wav")
        auth.assert_called_once_with(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        names = [call.args[0] for call in client.bucket.return_value.blob.call_args_list]
        self.assertNotEqual(names[0], names[1])
        signed = client.bucket.return_value.blob.return_value.generate_signed_url.call_args.kwargs
        self.assertEqual(signed["service_account_email"], "mcp@test-project.iam.gserviceaccount.com")
        self.assertEqual(signed["access_token"], "test-token")


if __name__ == "__main__":
    unittest.main()
