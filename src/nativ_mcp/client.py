"""Thin async wrapper around the Nativ REST API."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nativ_mcp import __version__

DEFAULT_API_URL = "https://api.usenativ.com"


class NativClient:
    """Thin async wrapper around the Nativ REST API."""

    def __init__(self, api_key: str, base_url: str | None = None):
        self.base_url = (base_url or DEFAULT_API_URL).rstrip("/")
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": f"nativ-mcp/{__version__}",
        }
        # Multipart requests must not set Content-Type; httpx sets the
        # boundary automatically when files are provided.
        self.multipart_headers = {
            "X-API-Key": api_key,
            "User-Agent": f"nativ-mcp/{__version__}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                json=json_body,
                params=params,
            )
            if resp.status_code == 402:
                raise RuntimeError("Insufficient Nativ credits. Top up at https://dashboard.usenativ.com")
            resp.raise_for_status()
            return resp.json()

    async def _request_multipart(
        self,
        path: str,
        *,
        files: Any,
        data: Any | None = None,
    ) -> dict[str, Any]:
        # Image generation can take a while, so use a generous timeout.
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                headers=self.multipart_headers,
                files=files,
                data=data,
            )
            if resp.status_code == 402:
                raise RuntimeError("Insufficient Nativ credits. Top up at https://dashboard.usenativ.com")
            resp.raise_for_status()
            return resp.json()

    # -- Translation --------------------------------------------------------

    async def translate(
        self,
        text: str,
        language: str,
        *,
        language_code: str | None = None,
        source_language: str = "English",
        source_language_code: str = "en",
        context: str | None = None,
        glossary: str | None = None,
        formality: str | None = None,
        max_characters: int | None = None,
        include_tm_info: bool = True,
        backtranslate: bool = False,
        include_rationale: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": text,
            "language": language,
            "source_language": source_language,
            "source_language_code": source_language_code,
            "tool": "api",
            "include_tm_info": include_tm_info,
            "backtranslate": backtranslate,
            "include_rationale": include_rationale,
        }
        if language_code:
            body["language_code"] = language_code
        if context:
            body["context"] = context
        if glossary:
            body["glossary"] = glossary
        if formality:
            body["formality"] = formality
        if max_characters is not None:
            body["max_characters"] = max_characters
        return await self._request("POST", "/text/culturalize", json_body=body)

    # -- Languages ----------------------------------------------------------

    async def get_languages(self) -> dict[str, Any]:
        return await self._request("GET", "/user/languages")

    # -- Translation Memory -------------------------------------------------

    async def search_tm(
        self,
        query: str,
        *,
        source_lang: str = "en",
        target_lang: str | None = None,
        score_cutoff: float = 0.0,
        limit: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "query": query,
            "source_lang": source_lang,
            "score_cutoff": score_cutoff,
            "limit": limit,
        }
        if target_lang:
            params["target_lang"] = target_lang
        return await self._request("GET", "/master-tm/fuzzy-search", params=params)

    async def list_tm_entries(
        self,
        *,
        source_lang: str | None = None,
        target_lang: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if source_lang:
            params["source_lang"] = source_lang
        if target_lang:
            params["target_lang"] = target_lang
        if search:
            params["search"] = search
        return await self._request("GET", "/master-tm/entries", params=params)

    async def add_tm_entry(
        self,
        source_text: str,
        target_text: str,
        source_language_code: str,
        target_language_code: str,
        *,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "source_text": source_text,
            "target_text": target_text,
            "source_language_code": source_language_code,
            "target_language_code": target_language_code,
            "information_source": "manual",
        }
        if source_name:
            body["source_name"] = source_name
        return await self._request("POST", "/master-tm/entries", json_body=body)

    async def get_tm_stats(self) -> dict[str, Any]:
        return await self._request("GET", "/master-tm/stats")

    # -- Style Guides -------------------------------------------------------

    async def list_style_guides(self) -> dict[str, Any]:
        return await self._request("GET", "/style-guide")

    async def get_brand_prompt(self) -> dict[str, Any]:
        return await self._request("GET", "/style-guide/prompt")

    async def get_combined_prompt(self) -> dict[str, Any]:
        return await self._request("GET", "/style-guide/combined")

    # -- Image --------------------------------------------------------------

    async def extract_image_segments(
        self, image_bytes: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        files = {"file": (filename, image_bytes, content_type)}
        return await self._request_multipart("/text/extract-segments", files=files)

    async def localize_image(
        self,
        image_bytes: bytes,
        filename: str,
        content_type: str,
        *,
        replacements_json: str,
        language_code: str,
        num_images: int = 1,
        output_format: str = "png",
    ) -> dict[str, Any]:
        files = {"file": (filename, image_bytes, content_type)}
        data = {
            "replacements": replacements_json,
            "language_code": language_code,
            "output_format": output_format,
            "tool": "api",
            "num_images": str(num_images),
        }
        return await self._request_multipart("/image/localize", files=files, data=data)

    async def inspect_image(
        self,
        image_bytes: bytes,
        filename: str,
        content_type: str,
        *,
        countries: list[str] | None = None,
    ) -> dict[str, Any]:
        files = {"file": (filename, image_bytes, content_type)}
        # httpx encodes a dict-with-list value as repeated form fields. Passing
        # a list of tuples here instead makes httpx build a sync stream, which
        # fails inside the AsyncClient — so always hand it a Mapping.
        data = {"countries": countries} if countries else {}
        return await self._request_multipart("/image/inspect", files=files, data=data)

    async def transcribe_audio(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        *,
        source_language_code: str | None = None,
        keep_background_music: bool = False,
    ) -> dict[str, Any]:
        files = {"file": (filename, file_bytes, content_type)}
        data: dict[str, Any] = {
            "keep_background_music": "true" if keep_background_music else "false",
        }
        if source_language_code:
            data["source_language_code"] = source_language_code
        return await self._request_multipart("/audio/transcribe", files=files, data=data)

    async def parse_audio_script(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        files = {"file": (filename, file_bytes, content_type)}
        return await self._request_multipart("/audio/script", files=files)

    async def register_video(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        files = {"file": (filename, file_bytes, content_type)}
        return await self._request_multipart("/audio/video/register", files=files)

    async def list_voices(self, language_code: str | None = None) -> dict[str, Any]:
        params = {"language_code": language_code} if language_code else None
        return await self._request("GET", "/audio/voices", params=params)

    async def preview_voice(
        self,
        voice_id: str,
        *,
        language_code: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"voice_id": voice_id}
        if language_code:
            body["language_code"] = language_code
        if text:
            body["text"] = text
        return await self._request("POST", "/audio/voices/preview", json_body=body)

    async def get_voice_consent_script(
        self, language_code: str | None = None
    ) -> dict[str, Any]:
        params = {"language_code": language_code} if language_code else None
        return await self._request("GET", "/audio/voices/consent-script", params=params)

    async def synthesize_audio(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/audio/synthesize", json_body=body)

    async def remux_video(self, video_id: str, audio_base64: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/audio/remux-video",
            json_body={"video_id": video_id, "audio_base64": audio_base64},
        )

    async def parse_subtitle(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        files = {"file": (filename, file_bytes, content_type)}
        return await self._request_multipart("/subtitle/parse", files=files)

    async def localize_subtitles(
        self,
        target_language_codes: list[str],
        *,
        subtitle: tuple[bytes, str, str] | None = None,
        video: tuple[bytes, str, str] | None = None,
        glossary: tuple[bytes, str, str] | None = None,
        source_language_code: str = "en",
        context: str = "",
        formality: str | None = None,
    ) -> dict[str, Any]:
        files: dict[str, Any] = {}
        if subtitle:
            files["subtitle"] = (subtitle[1], subtitle[0], subtitle[2])
        if video:
            files["video"] = (video[1], video[0], video[2])
        if glossary:
            files["glossary"] = (glossary[1], glossary[0], glossary[2])
        data: dict[str, Any] = {
            "target_language_codes": json.dumps(target_language_codes),
            "source_language_code": source_language_code,
            "context": context,
        }
        if formality:
            data["formality"] = formality
        return await self._request_multipart(
            "/subtitle/playground", files=files or None, data=data
        )


