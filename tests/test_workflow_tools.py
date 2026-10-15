import asyncio
import base64
import email
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from jsonschema import Draft202012Validator
from mcp import Client

from nativ_mcp.client import NativClient
from nativ_mcp.hosted import create_app
from nativ_mcp.runtime import hosted_request
from nativ_mcp.server import mcp


SCHEMA = json.loads(
    (Path(__file__).parents[1] / "src/nativ_mcp/rest-openapi.json").read_text()
)
ORIGINAL = json.loads(
    (Path(__file__).parent / "fixtures/original_tool_schemas.json").read_text()
)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.file = Path(self.directory.name) / "speech.wav"
        self.file.write_bytes(b"reference speech")
        self.requests = []
        self.real_client = httpx.AsyncClient
        self.env = patch.dict(os.environ, {"NATIV_API_KEY": "nativ_workflow_test"})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def validate(self, value, schema):
        Draft202012Validator({**schema, "components": SCHEMA["components"]}).validate(
            value
        )

    def backend(self, request):
        """Validate real encoded requests against the deployed API contract."""
        self.requests.append(request)
        self.assertEqual(request.headers["X-API-Key"], "nativ_workflow_test")
        candidates = [
            (path, operations)
            for path, operations in SCHEMA["paths"].items()
            if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", path), request.url.path)
        ]
        self.assertTrue(candidates, request.url.path)
        _, operations = candidates[0]
        operation = operations[request.method.lower()]
        declared = {
            p["name"] for p in operation.get("parameters", []) if p["in"] == "query"
        }
        self.assertFalse(set(request.url.params) - declared, request.url.params)
        for parameter in operation.get("parameters", []):
            if parameter["in"] != "query":
                continue
            name, schema = parameter["name"], parameter["schema"]
            if name not in request.url.params:
                self.assertFalse(parameter.get("required"), name)
                continue
            value = request.url.params[name]
            kind = schema.get("type")
            if kind == "array":
                value = request.url.params.get_list(name)
            elif kind == "boolean":
                value = {"true": True, "false": False}[value]
            elif kind == "integer":
                value = int(value)
            self.validate(value, schema)
        content = operation.get("requestBody", {}).get("content", {})
        if "application/json" in content:
            self.assertIn("application/json", request.headers["content-type"])
            self.validate(
                json.loads(request.content), content["application/json"]["schema"]
            )
        if "multipart/form-data" in content:
            self.assertIn("boundary=", request.headers["content-type"])
            message = email.message_from_bytes(
                (
                    "Content-Type: " + request.headers["content-type"] + "\r\n\r\n"
                ).encode()
                + request.content
            )
            fields = {
                part.get_param("name", header="content-disposition"): part
                for part in message.get_payload()
            }
            body_schema = content["multipart/form-data"]["schema"]
            body_schema = SCHEMA["components"]["schemas"][
                body_schema["$ref"].split("/")[-1]
            ]
            self.assertTrue(set(body_schema.get("required", [])) <= set(fields))
            self.assertFalse(set(fields) - set(body_schema["properties"]))
        if request.url.path == "/audio/synthesize":
            return httpx.Response(
                200,
                json={
                    "audio_base64": base64.b64encode(b"dubbed").decode(),
                    "video_base64": base64.b64encode(b"video").decode(),
                    "metadata": {"provider": "test"},
                },
            )
        if request.url.path == "/audio/transcribe":
            return httpx.Response(
                200,
                json={
                    "segments": [
                        {"id": str(i), "speaker_id": "s1"} for i in range(101)
                    ],
                    "speakers": [{"speaker_id": "s1", "speech_ms": 30000}],
                    "source_voice_audio_base64": "private-blob",
                    "video_id": "video",
                },
            )
        if request.url.path in (
            "/subtitle/qc/download",
            "/subtitle/download-formatted",
        ):
            return httpx.Response(
                200, content=b"export", headers={"Content-Type": "application/x-subrip"}
            )
        return httpx.Response(
            200, json={"success": True, "voice_id": "elevenlabs:test"}
        )

    async def call(self, name, args):
        transport = httpx.MockTransport(self.backend)
        with patch(
            "nativ_mcp.client.httpx.AsyncClient",
            lambda **kwargs: self.real_client(transport=transport, **kwargs),
        ):
            async with Client(mcp) as client:
                return await client.call_tool(name, args)

    async def test_original_tool_input_and_output_contracts_are_unchanged(self):
        async with Client(mcp) as client:
            current = {
                tool.name: tool.model_dump(mode="json")
                for tool in (await client.list_tools()).tools
            }
        for name, schemas in ORIGINAL.items():
            with self.subTest(tool=name):
                self.assertEqual(
                    {key: current[name].get(key) for key in schemas}, schemas
                )
        self.assertEqual(len(current), 51)

    async def test_all_new_tools_send_requests_matching_production_contract(self):
        f = str(self.file)
        cases = [
            ("list_language_settings", {}, "GET", "/user/languages"),
            ("list_style_guides", {}, "GET", "/style-guide"),
            (
                "clone_voice",
                {"reference_path": f, "consent_path": f, "confirm_ownership": True},
                "POST",
                "/audio/voices/clone",
            ),
            (
                "create_byo_voice",
                {
                    "reference_path": f,
                    "confirm_ownership": True,
                    "clip_reference": True,
                    "clip_ranges": [{"start_ms": 100, "end_ms": 3000}],
                },
                "POST",
                "/audio/voices/byo",
            ),
            (
                "delete_saved_voice",
                {"voice_id": "elevenlabs:test"},
                "DELETE",
                "/audio/voices/saved",
            ),
            ("get_audio_capabilities", {}, "GET", "/audio/capabilities"),
            (
                "transcribe_audio_detailed",
                {"file_path": f, "speaker_count": 2},
                "POST",
                "/audio/transcribe",
            ),
            (
                "translate_dialogue",
                {
                    "segments": [
                        {
                            "id": "1",
                            "text": "Hello",
                            "target_language": "Hindi",
                            "target_language_code": "hi",
                        }
                    ]
                },
                "POST",
                "/audio/translate-dialogue",
            ),
            (
                "synthesize_audio_advanced",
                {
                    "language": "Hindi",
                    "language_code": "hi",
                    "voice_id": "elevenlabs:test",
                    "segments": [{"text": "नमस्ते", "speaker_id": "s1"}],
                    "speaker_voices": {"s1": "elevenlabs:test"},
                    "output_path": str(Path(self.directory.name) / "dub.wav"),
                },
                "POST",
                "/audio/synthesize",
            ),
            (
                "upload_subtitle",
                {
                    "file_path": f,
                    "auto_localize": True,
                    "target_languages": ["hi", "bn"],
                },
                "POST",
                "/subtitle/upload",
            ),
            ("list_subtitles", {}, "GET", "/subtitle/list"),
            (
                "localize_subtitle_file",
                {"storage_path": "423/en/source.srt", "target_languages": ["hi", "bn"]},
                "POST",
                "/subtitle/localize",
            ),
            (
                "get_subtitle_download_url",
                {"storage_path": "423/hi/target.srt"},
                "GET",
                "/subtitle/download-url",
            ),
            (
                "delete_subtitle",
                {"storage_path": "423/hi/target.srt"},
                "DELETE",
                "/subtitle/delete",
            ),
            (
                "get_subtitle_review",
                {"storage_path": "423/hi/target.srt"},
                "GET",
                "/subtitle/qc/preview",
            ),
            (
                "update_subtitle_review",
                {
                    "storage_path": "423/hi/target.srt",
                    "updates": [
                        {"row_index": 2, "translation": "नमस्ते", "approved": True}
                    ],
                },
                "POST",
                "/subtitle/qc/update-translations",
            ),
            (
                "export_subtitle",
                {
                    "storage_path": "423/hi/target.srt",
                    "output_path": str(Path(self.directory.name) / "target.srt"),
                },
                "GET",
                "/subtitle/download-formatted",
            ),
            (
                "list_translation_memory_entries",
                {"enabled_only": True},
                "GET",
                "/master-tm/entries",
            ),
            (
                "update_translation_memory_entry",
                {"entry_id": "entry", "enabled": False},
                "PATCH",
                "/master-tm/entries/entry",
            ),
            (
                "delete_translation_memory_entry",
                {"entry_id": "entry"},
                "DELETE",
                "/master-tm/entries/entry",
            ),
            (
                "get_language_formality_options",
                {},
                "GET",
                "/user/languages/formality-options",
            ),
            (
                "update_language_formality",
                {"mapping_id": 5, "formality": "very_informal"},
                "PATCH",
                "/user/languages/5/formality",
            ),
            (
                "update_language_custom_style",
                {"mapping_id": 5, "custom_style": None},
                "PATCH",
                "/user/languages/5/custom-style",
            ),
            ("get_combined_prompt", {}, "GET", "/style-guide/combined"),
            (
                "create_style_guide",
                {"title": "Street Hindi", "content": "Use colloquial dialogue"},
                "POST",
                "/style-guide",
            ),
            (
                "update_style_guide",
                {"guide_id": "guide", "is_enabled": False},
                "PUT",
                "/style-guide/guide",
            ),
            (
                "delete_style_guide",
                {"guide_id": "guide"},
                "DELETE",
                "/style-guide/guide",
            ),
            (
                "upload_style_guide",
                {"file_path": f, "title": "Voice"},
                "POST",
                "/style-guide/upload",
            ),
            (
                "reorder_style_guides",
                {"guide_ids": ["a", "b"]},
                "POST",
                "/style-guide/reorder",
            ),
            (
                "submit_translation_feedback",
                {"approved": False, "feedback": "Too formal"},
                "POST",
                "/text/feedback",
            ),
        ]
        async with Client(mcp) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
        self.assertEqual({name for name, *_ in cases}, tools - set(ORIGINAL))
        for name, args, method, path in cases:
            with self.subTest(tool=name):
                before = len(self.requests)
                result = await self.call(name, args)
                self.assertFalse(result.is_error, result)
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(
                    (self.requests[-1].method, self.requests[-1].url.path),
                    (method, path),
                )
                if name == "transcribe_audio_detailed":
                    self.assertEqual(len(result.structured_content["segments"]), 101)
                    self.assertNotIn(
                        "source_voice_audio_base64", result.structured_content
                    )
                if name == "synthesize_audio_advanced":
                    self.assertNotIn("audio_base64", result.structured_content)
                    self.assertEqual(
                        Path(
                            result.structured_content["audio_url_or_path"]
                        ).read_bytes(),
                        b"dubbed",
                    )

    async def test_cloning_requires_confirmation_before_reading_files_or_contacting_api(
        self,
    ):
        for name in ("clone_voice", "create_byo_voice"):
            args = {"reference_path": "must-not-read"}
            if name == "clone_voice":
                args["consent_path"] = "must-not-read"
            with patch("nativ_mcp.workflow_tools.read_file", AsyncMock()) as read:
                result = await self.call(name, args)
            self.assertTrue(result.is_error)
            read.assert_not_awaited()
        self.assertEqual(self.requests, [])

    async def test_google_saved_clone_requires_consent_and_forwards_both_uploads(self):
        args = {"reference_path": str(self.file), "confirm_ownership": True}
        result = await self.call("create_byo_voice", args)
        self.assertTrue(result.is_error)
        self.assertFalse(self.requests)
        result = await self.call(
            "create_byo_voice", {**args, "consent_path": str(self.file)}
        )
        self.assertFalse(result.is_error)
        self.assertIn(b'name="consent"', self.requests[-1].content)
        self.assertIn(b'name="clip_reference"\r\n\r\nfalse', self.requests[-1].content)

    async def test_invalid_ranges_and_empty_updates_fail_without_api_calls(self):
        for name, args in [
            (
                "create_byo_voice",
                {
                    "reference_path": str(self.file),
                    "confirm_ownership": True,
                    "clip_reference": True,
                    "clip_ranges": [{"start_ms": 100, "end_ms": 50}],
                },
            ),
            ("update_style_guide", {"guide_id": "guide"}),
            ("update_translation_memory_entry", {"entry_id": "entry"}),
            ("update_subtitle_review", {"storage_path": "423/hi/a.srt", "updates": []}),
            ("upload_subtitle", {"file_path": str(self.file), "auto_localize": True}),
        ]:
            with self.subTest(tool=name):
                self.assertTrue((await self.call(name, args)).is_error)
        self.assertFalse(self.requests)

    async def test_upstream_failure_is_tool_error_and_is_not_retried(self):
        request = httpx.Request("POST", "https://api.usenativ.com/audio/voices/byo")
        response = httpx.Response(403, request=request)
        with patch.object(
            NativClient,
            "_request_multipart",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "verification required", request=request, response=response
                )
            ),
        ) as upstream:
            result = await self.call(
                "create_byo_voice",
                {
                    "reference_path": str(self.file),
                    "clip_reference": True,
                    "confirm_ownership": True,
                },
            )
        self.assertTrue(result.is_error)
        upstream.assert_awaited_once()

    async def test_subtitle_export_redirect_never_forwards_api_key(self):
        def redirect(request):
            self.assertEqual(request.headers["X-API-Key"], "nativ_workflow_test")
            return httpx.Response(
                302,
                headers={
                    "Location": "https://storage.example.com/export.srt?signature=secret"
                },
            )

        with patch(
            "nativ_mcp.client.httpx.AsyncClient",
            lambda **kwargs: self.real_client(
                transport=httpx.MockTransport(redirect), **kwargs
            ),
        ), patch(
            "nativ_mcp.files.download_media",
            AsyncMock(return_value=(b"subtitle", "export.srt", "application/x-subrip")),
        ) as download:
            data, mime = await NativClient(
                "nativ_workflow_test"
            ).download_subtitle_export("423/hi/a.srt")
        self.assertEqual(data, b"subtitle")
        self.assertEqual(mime, "application/x-subrip")
        download.assert_awaited_once_with(
            "https://storage.example.com/export.srt?signature=secret", 100 * 1024 * 1024
        )


class HostedWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from test_hosted import MemoryArtifacts

        self.store = MemoryArtifacts()
        self.app = create_app(
            artifact_store=self.store,
            api_transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={})
            ),
        )
        self.ready, self.stop = asyncio.Event(), asyncio.Event()

        async def lifespan():
            async with self.app.router.lifespan_context(self.app):
                self.ready.set()
                await self.stop.wait()

        self.task = asyncio.create_task(lifespan())
        await self.ready.wait()
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://localhost:8080",
        )

    async def asyncTearDown(self):
        await self.http.aclose()
        self.stop.set()
        await self.task

    async def test_json_clone_accepts_urls_native_ranges_and_returns_saved_voice(self):
        seen = []

        async def upstream(client, path, **kwargs):
            seen.append((client.headers["X-API-Key"], path, kwargs))
            return {"voice_id": "elevenlabs:new", "provider": "elevenlabs"}

        with patch(
            "nativ_mcp.files.download_media",
            AsyncMock(return_value=(b"speech", "source.mp4", "video/mp4")),
        ), patch.object(NativClient, "_request_multipart", upstream):
            response = await self.http.post(
                "/tools/create_byo_voice",
                headers={"X-API-Key": "nativ_alice"},
                json={
                    "reference_path": "https://cdn.example.com/source.mp4",
                    "confirm_ownership": True,
                    "clip_reference": True,
                    "clip_ranges": [{"start_ms": 0, "end_ms": 30000}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["voice_id"], "elevenlabs:new")
        self.assertEqual(seen[0][:2], ("nativ_alice", "/audio/voices/byo"))
        self.assertEqual(
            json.loads(seen[0][2]["data"]["clip_ranges"]),
            [{"start_ms": 0, "end_ms": 30000}],
        )

    async def test_new_url_fields_block_local_paths_but_storage_keys_are_accepted(self):
        for field in ("reference_path", "consent_path"):
            response = await self.http.post(
                "/tools/clone_voice",
                headers={"X-API-Key": "nativ_alice"},
                json={
                    "reference_path": "https://cdn.example.com/speech.wav",
                    "consent_path": "https://cdn.example.com/consent.wav",
                    field: "/etc/passwd",
                    "confirm_ownership": True,
                },
            )
            self.assertEqual(response.status_code, 422)
        with patch.object(
            NativClient,
            "_request",
            AsyncMock(
                return_value={"download_url": "https://storage.example.com/a.srt"}
            ),
        ) as upstream:
            response = await self.http.post(
                "/tools/get_subtitle_download_url",
                headers={"X-API-Key": "nativ_alice"},
                json={"storage_path": "423/hi/a.srt"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            upstream.call_args.kwargs["params"], {"file_path": "423/hi/a.srt"}
        )

    async def test_hosted_and_local_register_identical_schemas_including_new_tools(
        self,
    ):
        from test_hosted import HostedTests

        response = await HostedTests.rpc(self, "tools/list")
        remote = {
            tool["name"]: tool["inputSchema"]
            for tool in response.json()["result"]["tools"]
        }
        async with Client(mcp) as client:
            local = {
                tool.name: tool.input_schema
                for tool in (await client.list_tools()).tools
            }
        self.assertEqual(remote, local)

    async def test_speaker_dubbing_outputs_artifacts_and_keeps_each_callers_key(self):
        seen = []

        async def synthesize(client, body):
            seen.append((client.headers["X-API-Key"], body))
            await asyncio.sleep(0.01)
            return {
                "audio_base64": base64.b64encode(
                    client.headers["X-API-Key"].encode()
                ).decode()
            }

        with patch.object(NativClient, "synthesize_audio", synthesize):
            responses = await asyncio.gather(
                *[
                    self.http.post(
                        "/tools/synthesize_audio_advanced",
                        headers={"X-API-Key": key},
                        json={
                            "language": "Hindi",
                            "language_code": "hi",
                            "voice_id": "elevenlabs:test",
                            "segments": [{"text": "नमस्ते", "speaker_id": "s1"}],
                            "speaker_voices": {"s1": "elevenlabs:test"},
                            "output_path": "/must-not-write/" + key + ".wav",
                            "stem_id": "music",
                            "keep_background_music": True,
                        },
                    )
                    for key in ("nativ_alice", "nativ_bob")
                ]
            )
        self.assertCountEqual([key for key, _ in seen], ["nativ_alice", "nativ_bob"])
        for response, key in zip(responses, ("nativ_alice", "nativ_bob")):
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["artifacts"][0]["filename"], key + ".wav")
            self.assertNotIn("audio_base64", response.text)
        self.assertTrue(
            all(
                body["speaker_voices"] == {"s1": "elevenlabs:test"}
                and body["stem_id"] == "music"
                for _, body in seen
            )
        )
        self.assertIsNone(hosted_request.get())
