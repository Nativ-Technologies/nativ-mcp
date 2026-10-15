# MCP localization capability audit

Version 0.5.0 exposes 51 tools through the shared stdio/hosted server and the
JSON tools adapter. This audit compares the existing public Python SDK workflows
with the deployed API schema, plus the audio and subtitle review steps needed
to complete those workflows. It does not expose internal administration,
account provisioning, billing configuration, or provider credentials.

No backend or frontend code changes are part of this release. All new calls
use existing routes, caller authentication, ownership checks, limits and billing.
The existing 21 tools retain their input/output schemas and implementations.

| Workflow | MCP coverage |
| --- | --- |
| Text localization | `translate`, `translate_batch` |
| Image OCR, localization and cultural inspection | `extract_image_text`, `localize_image`, `check_image_cultural_fit` |
| Workspace languages | `get_languages`, `list_language_settings`, `get_language_formality_options`, `update_language_formality`, `update_language_custom_style` |
| Translation memory search, list, creation, editing, deletion and stats | `search_translation_memory`, `list_translation_memory_entries`, `add_translation_memory_entry`, `update_translation_memory_entry`, `delete_translation_memory_entry`, `get_translation_memory_stats` |
| Style guides and brand voice | `get_style_guides`, `list_style_guides`, `get_brand_voice`, `get_combined_prompt`, `create_style_guide`, `update_style_guide`, `delete_style_guide`, `upload_style_guide`, `reorder_style_guides` |
| User translation feedback | `submit_translation_feedback` |
| Audio limits, transcription and script import | `get_audio_capabilities`, `transcribe_audio`, `transcribe_audio_detailed`, `parse_audio_script` |
| Preset and saved voice discovery and preview | `list_voices`, `preview_voice` |
| Create a Google clone with a spoken consent recording | `get_voice_consent_script`, `clone_voice`; `create_byo_voice` also saves the clone |
| Create and save an ElevenLabs clone from source audio/video | `create_byo_voice` with `clip_reference=true`, optional speaker speech ranges |
| Delete a saved clone | `delete_saved_voice` |
| Translate speaker turns together | `translate_dialogue` |
| Dub audio/video, speaker voices and background music | `synthesize_audio`, `synthesize_audio_advanced` |
| Video registration and remux | `register_video`, `remux_video` |
| In-memory subtitle parsing/localization | `parse_subtitle`, `localize_subtitles` |
| Saved subtitle upload, listing, localization and deletion | `upload_subtitle`, `list_subtitles`, `localize_subtitle_file`, `delete_subtitle` |
| Saved subtitle download, review edits and export | `get_subtitle_download_url`, `get_subtitle_review`, `update_subtitle_review`, `export_subtitle` |

## Original-voice video workflow

1. Call `get_audio_capabilities` and respect the account's processing limit.
2. Call `transcribe_audio_detailed` with `keep_background_music=true`. Retain
   the returned segments, speaker IDs, `video_id`, `stem_id`, speech islands,
   transcript and actual processed duration. Set `speaker_count=0` for automatic
   detection, or specify 1–8 speakers.
3. Use an existing saved voice from `list_voices`, or get the user's explicit
   ownership/permission confirmation before creating one. Use
   `create_byo_voice(clip_reference=true)` with the original media and optional
   speech-only `clip_ranges` for each speaker. Google cloning instead requires
   the specified consent recording. Provider verification requirements apply.
4. Translate related turns together with `translate_dialogue` or
   `translate_batch`, supplying the desired locale, context and formality.
5. Review the translated script and cue boundaries. A clipped transcript must
   not be presented as a complete localization of a longer source.
6. Call `synthesize_audio_advanced` with translated segments, chosen voice IDs,
   `speaker_voices` when needed, source timings, `video_id`, `stem_id` and
   `keep_background_music=true`. This is a billed operation. The compact
   `synthesize_audio` tool remains available with its original arguments.
7. Open the returned WAV/MP4 files (stdio) or expiring download URLs (hosted).
   The client's ability to preview a format is independent of MCP transport.

## Saved subtitles

`upload_subtitle` saves a source and can auto-localize SRT/ITT. The existing
`/subtitle/localize` route handles saved ITT sources; its MCP wrapper sends
`file_path` and repeated `target_languages` as query parameters, matching the
deployed API rather than the SDK's outdated JSON-body implementation. For SRT,
use upload with auto-localization or the existing in-memory tool.

`storage_path` is a backend storage key from upload/list, not a local file or
media URL. Review rows come from `get_subtitle_review`. After
`update_subtitle_review`, `export_subtitle(regenerate=true)` applies edits to
the subtitle. `export_subtitle(qc=true)` exports the QC workbook. Backend export
redirects are downloaded with the existing public-HTTPS validator without
forwarding the caller's Nativ API key to storage hosts.

## Transport and compatibility

- All tools register once; stdio and hosted MCP have identical names/schemas.
- New structured inputs use native JSON arrays/objects. Existing string inputs
  on older tools remain unchanged.
- Hosted file inputs use public HTTPS URLs, including valid presigned URLs.
  Local paths remain available for stdio. Clone inputs use `reference_path`
  and `consent_path` and follow the same download protections as other media.
- Generated outputs use the existing private artifact store, signed URLs and
  expiration policy. New tools do not return inline media blobs.
- Deletes are marked destructive; no delete or settings mutation is performed
  automatically by this release. Creating clones requires confirmation before
  reading reference files or contacting the cloning API.
- Models, reasoning settings, pricing, billing and backend/frontend contracts
  are not changed.

## Verification

The regression suite freezes the original 21 input/output schemas, checks all
30 new tools' actual HTTP requests against the deployed API contract, verifies
local/hosted tool-list parity, and exercises JSON media URLs, voice confirmation,
speaker dubbing, per-caller key isolation, artifact generation and export
redirect handling. Paid providers are mocked in these checks.
