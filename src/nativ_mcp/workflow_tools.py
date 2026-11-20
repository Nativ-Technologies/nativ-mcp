"""Complete public SDK workflows using the existing production API.

Registered once for stdio, hosted MCP, and the JSON adapter. Storage keys are
separate from file input paths: they must never be treated as remote URLs.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server import MCPServer
from pydantic import Field

from nativ_mcp.files import read_file, save_base64, save_bytes


def _id(value: str) -> str:
    if not value.strip():
        raise ValueError("Provide a non-empty resource ID.")
    return quote(value, safe="")


def _changes(**values: Any) -> dict:
    body = {key: value for key, value in values.items() if value is not None}
    if not body:
        raise ValueError("Provide at least one field to update.")
    return body


def _ownership(confirmed: bool) -> None:
    if not confirmed:
        raise ValueError(
            "Confirm you own this voice or have the speaker's permission to clone it."
        )


def _ranges(ranges: list[dict[str, int]] | None) -> None:
    if ranges is None:
        return
    if not 1 <= len(ranges) <= 500:
        raise ValueError("Provide between 1 and 500 speech ranges.")
    for item in ranges:
        start, end = item.get("start_ms"), item.get("end_ms")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValueError(
                "Each speech range needs integer start_ms >= 0 and end_ms > start_ms."
            )


def register_workflow_tools(mcp: MCPServer, get_client: Any) -> None:
    @mcp.tool()
    async def clone_voice(
        reference_path: Annotated[str, Field(description='Reference speech file: local path in stdio or public HTTPS URL when hosted.')],
        consent_path: Annotated[str, Field(description='Spoken consent recording: local path in stdio or public HTTPS URL when hosted. Required for Google voice cloning.')],
        confirm_ownership: Annotated[bool, Field(description='True only after the user explicitly confirms ownership or the speaker’s permission to clone this voice.')] = False,
        language_code: Annotated[str, Field(description='Language code, for example "en" or "fr". Leave empty to use the operation default.')] = "",
    ) -> dict[str, Any]:
        """Create a Google voice clone from reference speech and spoken consent.

        Requires the user's explicit ownership/permission confirmation. Obtain
        the required consent wording with get_voice_consent_script. Inputs are
        local paths in stdio or public HTTPS URLs hosted. Returns voice_id for
        preview_voice and synthesize_audio. For a saved ElevenLabs clone from
        original video speech, use create_byo_voice with clip_reference=true.
        """
        _ownership(confirm_ownership)
        reference, consent = (
            await read_file(reference_path),
            await read_file(consent_path),
        )
        return await get_client()._request_multipart(
            "/audio/voices/clone",
            files={
                "reference": (reference[1], reference[0], reference[2]),
                "consent": (consent[1], consent[0], consent[2]),
            },
            data={"language_code": language_code} if language_code else {},
        )

    @mcp.tool()
    async def create_byo_voice(
        reference_path: Annotated[str, Field(description='Reference speech file: local path in stdio or public HTTPS URL when hosted.')],
        confirm_ownership: Annotated[bool, Field(description='True only after the user explicitly confirms ownership or the speaker’s permission to clone this voice.')] = False,
        name: Annotated[str, Field(description='Optional display name for the saved voice.')] = "",
        language_code: Annotated[str, Field(description='Language code, for example "en" or "fr". Leave empty to use the operation default.')] = "",
        clip_reference: Annotated[bool, Field(description='True selects original-speech cloning with ElevenLabs; false selects Google cloning and requires consent_path.')] = False,
        consent_path: Annotated[str, Field(description='Spoken consent recording: local path in stdio or public HTTPS URL when hosted. Required for Google voice cloning.')] = "",
        clip_ranges: Annotated[list[dict[str, int]] | None, Field(description='Optional speech-only ranges with integer start_ms >= 0 and end_ms > start_ms; 1–500 ranges, only with clip_reference=true.')] = None,
    ) -> dict[str, Any]:
        """Create and save a reusable voice clone in the caller's workspace.

        Set clip_reference=true to clone original speech from audio/video with
        ElevenLabs. Optional clip_ranges selects speech-only {start_ms,end_ms}
        ranges, useful for individual speakers. Otherwise Google cloning needs
        consent_path with the speaker's consent recording. Requires explicit
        user confirmation of ownership/permission; never assume it. Inputs are
        local paths (stdio) or public HTTPS URLs (hosted). Returns voice_id for
        preview_voice and synthesize_audio. list_voices includes saved clones.
        """
        import json

        _ownership(confirm_ownership)
        _ranges(clip_ranges)
        if not clip_reference and not consent_path:
            raise ValueError(
                "Google cloning requires consent_path; original-speech cloning uses clip_reference=true."
            )
        if clip_ranges is not None and not clip_reference:
            raise ValueError("clip_ranges requires clip_reference=true.")
        reference = await read_file(reference_path)
        files = {"reference": (reference[1], reference[0], reference[2])}
        if consent_path:
            consent = await read_file(consent_path)
            files["consent"] = (consent[1], consent[0], consent[2])
        data = {
            "confirm_ownership": "true",
            "clip_reference": str(clip_reference).lower(),
        }
        if name:
            data["name"] = name
        if language_code:
            data["language_code"] = language_code
        if clip_ranges is not None:
            data["clip_ranges"] = json.dumps(clip_ranges)
        return await get_client()._request_multipart(
            "/audio/voices/byo", files=files, data=data
        )

    @mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
    async def delete_saved_voice(voice_id: Annotated[str, Field(description='Voice identifier returned by list_voices or voice creation; reuse the exact identifier.')]) -> dict[str, Any]:
        """Delete a saved cloned voice belonging to the caller, when explicitly requested."""
        return await get_client()._request(
            "DELETE", "/audio/voices/saved", params={"voice_id": voice_id}
        )

    @mcp.tool()
    async def get_audio_capabilities() -> dict[str, Any]:
        """Get the caller's audio/video duration limits and long-form eligibility.

        Check before transcription; do not assume a long input was processed
        fully. Respect the returned duration_ms and transcript boundaries.
        """
        return await get_client()._request("GET", "/audio/capabilities")

    @mcp.tool()
    async def transcribe_audio_detailed(
        file_path: Annotated[str, Field(description='Input file: local filesystem path in stdio, or an accessible public HTTPS URL on the hosted server.')],
        source_language_code: Annotated[str, Field(description='Source language code, for example "en"; empty omits the optional language hint/filter.')] = "",
        keep_background_music: Annotated[bool, Field(description='Whether to retain the original background music for the dubbing workflow.')] = False,
        speaker_count: Annotated[int, Field(description='Expected number of speakers: 0 for automatic detection, or 1–8.')] = 1,
        enterprise_long_form: Annotated[bool, Field(description='Request enterprise long-form processing only when allowed by get_audio_capabilities.')] = False,
    ) -> dict[str, Any]:
        """Transcribe audio/video with complete timed segments and speaker metadata.

        Unlike the compact transcribe_audio display, returns all segments with
        IDs, speaker IDs, speech islands, actual processed duration, video_id,
        and stem_id. Use for multi-speaker dubbing or long transcripts. File
        input is a local path (stdio) or public HTTPS URL (hosted). Draft step;
        check get_audio_capabilities before requesting long-form processing.
        speaker_count accepts 0 for automatic detection or 1–8 speakers.
        """
        if not 0 <= speaker_count <= 8:
            raise ValueError("speaker_count must be between 0 (automatic) and 8.")
        file = await read_file(file_path)
        data = {
            "keep_background_music": str(keep_background_music).lower(),
            "speaker_count": str(speaker_count),
            "enterprise_long_form": str(enterprise_long_form).lower(),
        }
        if source_language_code:
            data["source_language_code"] = source_language_code
        result = await get_client()._request_multipart(
            "/audio/transcribe", files={"file": (file[1], file[0], file[2])}, data=data
        )
        return {
            key: value for key, value in result.items() if not key.endswith("_base64")
        }

    @mcp.tool()
    async def translate_dialogue(
        segments: Annotated[list[dict[str, Any]], Field(description='1–500 dialogue turns, each with id, text, target_language, target_language_code and optional start_ms, end_ms, speaker_id from detailed transcription.')],
        source_language: Annotated[str, Field(description='Source language name, for example "English".')] = "English",
        source_language_code: Annotated[str, Field(description='Source language code, for example "en"; empty omits the optional language hint/filter.')] = "en",
        context: Annotated[str, Field(description='Optional audience, purpose and surrounding context to guide localization.')] = "",
        formality: Annotated[str, Field(description='Formality override: very_informal, informal, neutral, formal or very_formal. Empty uses workspace defaults.')] = "",
        speakers: Annotated[list[dict[str, Any]] | None, Field(description='Optional speaker metadata from detailed transcription, supplied alongside the dialogue turns.')] = None,
    ) -> dict[str, Any]:
        """Localize speaker turns together with shared dialogue context.

        Each segment needs id, text, target_language, target_language_code and
        optional start_ms, end_ms, speaker_id from transcribe_audio_detailed.
        Returns timed translated turns with review details; different turns
        may target different languages. Does not synthesize speech.
        """
        if not 1 <= len(segments) <= 500:
            raise ValueError("Provide between 1 and 500 dialogue segments.")
        if any(
            not all(
                segment.get(field)
                for field in ("id", "text", "target_language", "target_language_code")
            )
            for segment in segments
        ):
            raise ValueError(
                "Each turn needs id, text, target_language and target_language_code."
            )
        translation = {
            "text": "\n".join(segment["text"] for segment in segments),
            "language": segments[0]["target_language"],
            "language_code": segments[0]["target_language_code"],
            "source_language": source_language,
            "source_language_code": source_language_code,
            "tool": "api",
        }
        if context:
            translation["context"] = context
        if formality:
            translation["formality"] = formality
        return await get_client()._request(
            "POST",
            "/audio/translate-dialogue",
            json_body={
                "segments": segments,
                "translation": translation,
                "speakers": speakers or [],
            },
        )

    @mcp.tool()
    async def synthesize_audio_advanced(
        language: Annotated[str, Field(description='Target language for this operation, for example "French".')],
        language_code: Annotated[str, Field(description='Language code, for example "en" or "fr". Leave empty to use the operation default.')],
        voice_id: Annotated[str, Field(description='Voice identifier returned by list_voices or voice creation; reuse the exact identifier.')],
        segments: Annotated[list[dict[str, Any]], Field(description='Non-empty array of translated segments with text, start_ms, end_ms and optional original, speaker_id, voice_id, language_code and review fields.')],
        output_path: Annotated[str, Field(description='Output filename/path in stdio, or filename for the temporary hosted download. Use the matching file extension.')] = "dubbed.wav",
        video_output_path: Annotated[str, Field(description='Optional output MP4 filename/path; empty derives it from the audio output filename.')] = "",
        speaker_voices: Annotated[dict[str, str] | None, Field(description='Optional mapping from transcript speaker_id to a preset or saved voice_id.')] = None,
        keep_same_length: Annotated[bool, Field(description='Whether synthesis should try to retain the original timing.')] = False,
        keep_background_music: Annotated[bool, Field(description='Whether to retain the original background music for the dubbing workflow.')] = False,
        stem_id: Annotated[str, Field(description='Background-music stem identifier returned by transcription; empty omits it.')] = "",
        video_id: Annotated[str, Field(description='Video identifier returned by registration/transcription; empty omits video assembly.')] = "",
        source_duration_ms: Annotated[int, Field(description='Actual processed source duration in milliseconds, from transcription. Zero leaves it unspecified.')] = 0,
        source_transcript: Annotated[str, Field(description='Original transcript text for synthesis context; empty omits it.')] = "",
        speech_islands: Annotated[list[dict[str, int]] | None, Field(description='Optional speech timing ranges using integer start_ms and end_ms from detailed transcription.')] = None,
        document_translation: Annotated[bool, Field(description='Whether synthesis is for document-translation narration.')] = False,
        enterprise_long_form: Annotated[bool, Field(description='Request enterprise long-form processing only when allowed by get_audio_capabilities.')] = False,
    ) -> dict[str, Any]:
        """Synthesize multi-speaker audio/video with complete timing and review data.

        Billed operation. segments is a native array with text, start_ms,
        end_ms and optional original, speaker_id, voice_id, language_code and
        review fields returned by translation. speaker_voices maps each
        speaker_id to a preset or cloned voice_id. Pass stem_id to preserve
        background music and video_id to produce MP4. Outputs are local files
        (stdio) or expiring download URLs (hosted); no inline media blobs.
        """
        if not segments or source_duration_ms < 0:
            raise ValueError(
                "Provide non-empty segments and a non-negative source_duration_ms."
            )
        body = dict(
            language=language,
            language_code=language_code,
            voice_id=voice_id,
            segments=segments,
            speaker_voices=speaker_voices,
            keep_same_length=keep_same_length,
            keep_background_music=keep_background_music,
            source_duration_ms=source_duration_ms,
            document_translation=document_translation,
            enterprise_long_form=enterprise_long_form,
            speech_islands=speech_islands or [],
            tool="api",
        )
        body.update(
            {
                key: value
                for key, value in {
                    "stem_id": stem_id,
                    "video_id": video_id,
                    "source_transcript": source_transcript,
                }.items()
                if value
            }
        )
        result = await get_client().synthesize_audio(body)
        if not result.get("audio_base64"):
            raise RuntimeError("Synthesis returned no audio.")
        output = {
            key: value for key, value in result.items() if not key.endswith("_base64")
        }
        output["audio_url_or_path"] = await save_base64(
            result["audio_base64"], output_path
        )
        if result.get("video_base64"):
            from pathlib import Path

            output["video_url_or_path"] = await save_base64(
                result["video_base64"],
                video_output_path or str(Path(output_path).with_suffix(".mp4")),
            )
        return output

    @mcp.tool()
    async def upload_subtitle(
        file_path: Annotated[str, Field(description='Input file: local filesystem path in stdio, or an accessible public HTTPS URL on the hosted server.')],
        auto_localize: Annotated[bool, Field(description='True also requests billed subtitle localization; requires target_languages.')] = False,
        target_languages: Annotated[list[str] | None, Field(description='Target language codes for subtitle localization, for example ["fr", "ja"].')] = None,
        context: Annotated[str, Field(description='Optional audience, purpose and surrounding context to guide localization.')] = "",
        glossary: Annotated[str, Field(description='Optional glossary text to guide terminology for subtitle localization.')] = "",
        source_language: Annotated[str, Field(description='Source language code for subtitle processing, for example "en".')] = "en",
    ) -> dict[str, Any]:
        """Upload and save a subtitle file; optionally localize it (billed).

        Input is a local path (stdio) or public HTTPS URL (hosted). Returns
        storage paths for list_subtitles, localize_subtitle_file and download.
        Use localize_subtitles for the existing in-memory workflow instead.
        """
        if auto_localize and not target_languages:
            raise ValueError("auto_localize requires target_languages.")
        file = await read_file(file_path)
        params = {
            "auto_localize": auto_localize,
            "target_languages": target_languages or [],
            "context": context,
            "glossary": glossary,
            "source_language": source_language,
        }
        return await get_client()._request_multipart(
            "/subtitle/upload",
            files={"file": (file[1], file[0], file[2])},
            params=params,
        )

    @mcp.tool()
    async def list_subtitles() -> dict[str, Any]:
        """List the caller's saved subtitle sources, localized files, and storage paths."""
        return await get_client()._request("GET", "/subtitle/list")

    @mcp.tool()
    async def localize_subtitle_file(
        storage_path: Annotated[str, Field(description='Exact saved subtitle storage key returned by upload_subtitle or list_subtitles; not a local path or HTTPS URL.')],
        target_languages: Annotated[list[str], Field(description='Target language codes for subtitle localization, for example ["fr", "ja"].')],
        context: Annotated[str, Field(description='Optional audience, purpose and surrounding context to guide localization.')] = "",
        glossary: Annotated[str, Field(description='Optional glossary text to guide terminology for subtitle localization.')] = "",
    ) -> dict[str, Any]:
        """Localize an already saved ITT subtitle file (billed), using its storage path.

        storage_path comes from upload_subtitle/list_subtitles, not a local
        path or HTTPS URL. Backend expects query parameters for this route.
        For SRT, use upload_subtitle(auto_localize=true) or localize_subtitles.
        """
        if not storage_path or not target_languages:
            raise ValueError("Provide storage_path and at least one target language.")
        return await get_client()._request(
            "POST",
            "/subtitle/localize",
            params={
                "file_path": storage_path,
                "target_languages": target_languages,
                "context": context,
                "glossary": glossary,
            },
        )

    @mcp.tool()
    async def get_subtitle_download_url(storage_path: Annotated[str, Field(description='Exact saved subtitle storage key returned by upload_subtitle or list_subtitles; not a local path or HTTPS URL.')]) -> dict[str, Any]:
        """Get an expiring download URL for a saved subtitle's storage path."""
        return await get_client()._request(
            "GET", "/subtitle/download-url", params={"file_path": storage_path}
        )

    @mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
    async def delete_subtitle(storage_path: Annotated[str, Field(description='Exact saved subtitle storage key returned by upload_subtitle or list_subtitles; not a local path or HTTPS URL.')]) -> dict[str, Any]:
        """Delete a saved subtitle belonging to the caller, when explicitly requested."""
        return await get_client()._request(
            "DELETE", "/subtitle/delete", params={"file_path": storage_path}
        )

    @mcp.tool()
    async def get_subtitle_review(storage_path: Annotated[str, Field(description='Exact saved subtitle storage key returned by upload_subtitle or list_subtitles; not a local path or HTTPS URL.')]) -> dict[str, Any]:
        """Get saved subtitle QC rows, translations, rationales, and approval status."""
        return await get_client()._request(
            "GET", "/subtitle/qc/preview", params={"file_path": storage_path}
        )

    @mcp.tool()
    async def update_subtitle_review(
        storage_path: Annotated[str, Field(description='Exact saved subtitle storage key returned by upload_subtitle or list_subtitles; not a local path or HTTPS URL.')], updates: Annotated[list[dict[str, Any]], Field(description='Review edits with row_index from get_subtitle_review and translation, approved and/or rationale fields.')]
    ) -> dict[str, Any]:
        """Save subtitle review edits: rows with row_index, translation, approved, rationale.

        Use row indices returned by get_subtitle_review. Export with
        export_subtitle(regenerate=true) after editing to apply the changes.
        """
        if not updates:
            raise ValueError("Provide at least one review update.")
        return await get_client()._request(
            "POST",
            "/subtitle/qc/update-translations",
            json_body={"file_path": storage_path, "updates": updates},
        )

    @mcp.tool()
    async def export_subtitle(
        storage_path: Annotated[str, Field(description='Exact saved subtitle storage key returned by upload_subtitle or list_subtitles; not a local path or HTTPS URL.')],
        output_path: Annotated[str, Field(description='Output filename/path in stdio, or filename for the temporary hosted download. Use the matching file extension.')],
        qc: Annotated[bool, Field(description='True exports the review XLSX; false exports the subtitle in its original format.')] = False,
        regenerate: Annotated[bool, Field(description='True applies saved subtitle review edits before exporting.')] = False,
        source_language: Annotated[str, Field(description='Source language code for subtitle processing, for example "en".')] = "en",
    ) -> dict[str, Any]:
        """Export a saved subtitle or its QC workbook as a file/download URL.

        Set qc=true for the review XLSX. Otherwise retain the subtitle's
        original format; regenerate=true applies saved QC edits first. Use
        an output filename with the matching extension (.xlsx for QC).
        """
        data, mime = await get_client().download_subtitle_export(
            storage_path,
            qc=qc,
            regenerate=regenerate,
            source_language=source_language,
        )
        return {
            "url_or_path": await save_bytes(data, output_path, mime),
            "mime_type": mime,
        }

    @mcp.tool()
    async def list_translation_memory_entries(
        source_language_code: Annotated[str, Field(description='Source language code, for example "en"; empty omits the optional language hint/filter.')] = "",
        target_language_code: Annotated[str, Field(description='Target language code, for example "fr" or "ja".')] = "",
        information_source: Annotated[str, Field(description='Optional translation-memory information_source filter; empty includes all sources.')] = "",
        search: Annotated[str, Field(description='Optional text filter for translation-memory entries; empty disables this filter.')] = "",
        enabled_only: Annotated[bool, Field(description='True lists only enabled translation-memory entries.')] = False,
        limit: Annotated[int, Field(description='Maximum entries per page, 1–1000.')] = 100,
        offset: Annotated[int, Field(description='Number of entries to skip, zero or greater.')] = 0,
    ) -> dict[str, Any]:
        """List and paginate translation memory entries, including IDs for editing."""
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("Use limit 1–1000 and offset >= 0.")
        params = {"limit": limit, "offset": offset, "enabled_only": enabled_only}
        params.update(
            {
                key: value
                for key, value in {
                    "source_lang": source_language_code,
                    "target_lang": target_language_code,
                    "information_source": information_source,
                    "search": search,
                }.items()
                if value
            }
        )
        return await get_client()._request("GET", "/master-tm/entries", params=params)

    @mcp.tool()
    async def update_translation_memory_entry(
        entry_id: Annotated[str, Field(description='Exact translation-memory entry ID returned by list_translation_memory_entries.')],
        target_text: Annotated[str | None, Field(description='Translated wording for the memory entry; omit/null on updates to leave it unchanged.')] = None,
        enabled: Annotated[bool | None, Field(description='Whether this entry is enabled for future translations; null leaves it unchanged.')] = None,
    ) -> dict[str, Any]:
        """Edit an approved TM translation or enable/disable it for future translations."""
        return await get_client()._request(
            "PATCH",
            "/master-tm/entries/{entry_id}".format(entry_id=_id(entry_id)),
            json_body=_changes(target_text=target_text, enabled=enabled),
        )

    @mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
    async def delete_translation_memory_entry(entry_id: Annotated[str, Field(description='Exact translation-memory entry ID returned by list_translation_memory_entries.')]) -> dict[str, Any]:
        """Delete a translation memory entry, when explicitly requested."""
        return await get_client()._request(
            "DELETE", "/master-tm/entries/{entry_id}".format(entry_id=_id(entry_id))
        )

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_language_settings() -> dict[str, Any]:
        """Get complete workspace language settings, including IDs for updates.

        Use each returned language id as mapping_id for update_language_formality
        or update_language_custom_style. The compact get_languages tool remains
        available for a human-readable summary.
        """
        return await get_client().get_languages()

    @mcp.tool()
    async def get_language_formality_options() -> dict[str, Any]:
        """List supported workspace language formality levels."""
        return await get_client()._request("GET", "/user/languages/formality-options")

    @mcp.tool()
    async def update_language_formality(
        mapping_id: Annotated[int, Field(description='Exact workspace language mapping ID returned by list_language_settings.')],
        formality: Annotated[Literal[
            "very_informal", "informal", "neutral", "formal", "very_formal"
        ], Field(description='Formality override: very_informal, informal, neutral, formal or very_formal. Empty uses workspace defaults.')],
    ) -> dict[str, Any]:
        """Change the saved formality for a mapping from list_language_settings.

        This persists workspace settings; use translate's formality argument
        for a one-off request instead.
        """
        return await get_client()._request(
            "PATCH",
            "/user/languages/{mapping_id}/formality".format(mapping_id=mapping_id),
            json_body={"formality": formality},
        )

    @mcp.tool()
    async def update_language_custom_style(
        mapping_id: Annotated[int, Field(description='Exact workspace language mapping ID returned by list_language_settings.')], custom_style: Annotated[str | None, Field(description='Custom style instructions for this language mapping.')]
    ) -> dict[str, Any]:
        """Set saved per-language style instructions, or clear them with null.

        This persists workspace settings for the ID from list_language_settings.
        """
        return await get_client()._request(
            "PATCH",
            "/user/languages/{mapping_id}/custom-style".format(mapping_id=mapping_id),
            json_body={"custom_style": custom_style},
        )

    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_style_guides() -> dict[str, Any]:
        """Get full style-guide content, IDs, enabled state and ordering for editing.

        The compact get_style_guides summary is unchanged. Use this complete
        listing to obtain guide_id for update/delete, or IDs for reorder.
        """
        return await get_client().list_style_guides()

    @mcp.tool()
    async def get_combined_prompt() -> dict[str, Any]:
        """Get the workspace brand prompt combined with its enabled style guides."""
        return await get_client().get_combined_prompt()

    @mcp.tool()
    async def create_style_guide(
        title: Annotated[str, Field(description='Style-guide title; omit/null on updates to leave it unchanged.')], content: Annotated[str, Field(description='Style-guide instructions; omit/null on updates to leave them unchanged.')], is_enabled: Annotated[bool, Field(description='Whether the style guide is enabled; omit/null on updates to leave it unchanged.')] = True
    ) -> dict[str, Any]:
        """Create and save a workspace style guide used by future translations."""
        return await get_client()._request(
            "POST",
            "/style-guide",
            json_body={"title": title, "content": content, "is_enabled": is_enabled},
        )

    @mcp.tool()
    async def update_style_guide(
        guide_id: Annotated[str, Field(description='Exact style-guide ID returned by list_style_guides.')],
        title: Annotated[str | None, Field(description='Style-guide title; omit/null on updates to leave it unchanged.')] = None,
        content: Annotated[str | None, Field(description='Style-guide instructions; omit/null on updates to leave them unchanged.')] = None,
        is_enabled: Annotated[bool | None, Field(description='Whether the style guide is enabled; omit/null on updates to leave it unchanged.')] = None,
    ) -> dict[str, Any]:
        """Edit, enable or disable an existing workspace style guide."""
        return await get_client()._request(
            "PUT",
            "/style-guide/{guide_id}".format(guide_id=_id(guide_id)),
            json_body=_changes(title=title, content=content, is_enabled=is_enabled),
        )

    @mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True})
    async def delete_style_guide(guide_id: Annotated[str, Field(description='Exact style-guide ID returned by list_style_guides.')]) -> dict[str, Any]:
        """Delete a workspace style guide, when explicitly requested."""
        return await get_client()._request(
            "DELETE", "/style-guide/{guide_id}".format(guide_id=_id(guide_id))
        )

    @mcp.tool()
    async def upload_style_guide(file_path: Annotated[str, Field(description='Input file: local filesystem path in stdio, or an accessible public HTTPS URL on the hosted server.')], title: Annotated[str, Field(description='Style-guide title; omit/null on updates to leave it unchanged.')] = "") -> dict[str, Any]:
        """Create a workspace style guide from a .txt or .docx file.

        File input is a local path (stdio) or public HTTPS URL (hosted).
        """
        file = await read_file(file_path)
        return await get_client()._request_multipart(
            "/style-guide/upload",
            files={"file": (file[1], file[0], file[2])},
            params={"title": title} if title else {},
        )

    @mcp.tool()
    async def reorder_style_guides(guide_ids: Annotated[list[str], Field(description='Non-empty ordered list of unique style-guide IDs from list_style_guides.')]) -> dict[str, Any]:
        """Save the order of workspace style guides using IDs from list_style_guides."""
        if not guide_ids or len(set(guide_ids)) != len(guide_ids):
            raise ValueError("Provide a non-empty list of unique guide IDs.")
        return await get_client()._request(
            "POST", "/style-guide/reorder", json_body={"guide_ids": guide_ids}
        )

    @mcp.tool()
    async def submit_translation_feedback(
        source: Annotated[str | None, Field(description='Original text associated with this translation feedback.')] = None,
        result: Annotated[str | None, Field(description='Translated text associated with this feedback.')] = None,
        language: Annotated[str | None, Field(description='Target language for this operation, for example "French".')] = None,
        feedback: Annotated[str | None, Field(description='User feedback about this translation.')] = None,
        approved: Annotated[bool | None, Field(description='User approval state; saving approved memory requires explicit approval of the exact wording.')] = None,
    ) -> dict[str, Any]:
        """Save user feedback or an approval rating for a translation.

        This records feedback; add_translation_memory_entry separately saves
        an approved translation for reuse in future localization.
        """
        return await get_client()._request(
            "POST",
            "/text/feedback",
            json_body=_changes(
                source=source,
                result=result,
                language=language,
                feedback=feedback,
                approved=approved,
            ),
        )
