# Using Nativ: context, files and review

Checked against the full 0.5.0 tool catalogue and public JSON schema on
5 November 2026. This is an interface guide, not a translation-quality benchmark.

## Choose the contract before the tool

Local stdio and hosted `/mcp` expose the full 51-tool catalogue. The JSON adapter
exposes those operations at `/tools/{tool_name}` with JSON request bodies.
The focused OAuth `/chatgpt/mcp` endpoint has seven different tools. See
[the authentication table](hosting.md#authentication-boundaries).

A text batch returns text results. It is not an Office-file reconstruction
operation. Use the appropriate dashboard file workflow or documented REST route
when the deliverable is a PSD, PPTX, DOCX or workbook. Native creative plugins
work inside their host applications. Neither route implies that every source
feature survives a round trip; review a representative file.

## Which brand context applies?

Full MCP text translation uses the connected workspace’s memory and style
context. Inspect `get_languages`, `get_brand_voice`, `get_style_guides` or
`get_combined_prompt` where appropriate, and search relevant memory before
requesting new wording. A configured text language is not a guarantee that a
voice is available for that language.

`translate` accepts request-specific `context`, inline CSV `glossary`,
`formality`, `max_characters` and `backtranslate` arguments. `translate_batch`
accepts shared `context` and `formality`, but does **not** expose `glossary`,
`max_characters` or `backtranslate`. Do not pass parameters copied from a
different tool or assume a glossary uploaded in one plugin is attached to every
request. Resolve conflicting guidance with a small representative exercise;
there is no universal precedence guarantee in this guide.

Backtranslation, rationale and a memory match support review. They do not
certify linguistic or cultural quality. Requesting a character limit also does
not prove that a label fits its rendered box.

## Files and generated outputs

- **Local stdio:** the server reads paths on the machine where it runs.
- **Hosted MCP/JSON:** use accessible HTTPS media URLs, including valid signed
  URLs. Local paths, private-network URLs and private chat attachments are not
  automatically available to the service.
- **Generated hosted files:** download links expire after one hour. Save the
  approved deliverable to your intended storage. A temporary URL is not a
  permanent asset-publishing destination.
- **Transport limits:** hosted media downloads are capped at 100 MiB and
  120 seconds with up to five checked redirects. JSON bodies are capped at
  1 MiB. These do not replace account processing limits or per-operation checks.

JSON responses contain `tool`, `text`, `data` and `artifacts`. Not every tool
returns the same structured `data`. Inspect the response instead of assuming a
universal translation field. Generated artifacts include `url`, `filename`,
`mime_type` and `expires_in_seconds`.

The JSON adapter accepts a native `replacements` array for `localize_image`.
A direct MCP call to this older tool instead takes a JSON-encoded string.
Do not mix those input shapes. A rendered image does not recover editable
source type layers; inspect both the lettering and surrounding visual details.

## How saved subtitle edits reach the export

1. Save a source with `upload_subtitle`. Upload with auto-localisation supports
   SRT/ITT. The separate saved-file `localize_subtitle_file` route handles ITT;
   use upload auto-localisation or `localize_subtitles` for the SRT path.
2. Read `list_subtitles` and select the intended target-language file. Retain
   its `storage_path`: this is a storage key, not an HTTPS URL or local path.
3. Call `get_subtitle_review` with that key. Use the actual returned
   `row_index` values when sending `update_subtitle_review` updates such as
   `translation`, `approved` or `rationale`. Do not invent row indices.
4. Call `export_subtitle` with `regenerate=true` to apply saved edits. Match
   `output_path` to the source format, such as `.srt` for a saved SRT.
   For the QC workbook instead, use `qc=true` and an `.xlsx` filename.
5. Inspect the downloaded subtitle in the destination player. Saving review
   rows or exporting the workbook alone does not deliver the edited subtitle.

WebVTT conversion is a separate delivery step; this workflow does not promise
native VTT export or automatic timing/accessibility certification.

## Audio, video and voices

Check `get_audio_capabilities` and `list_voices` before generation. Preserve the
segments, speaker identities and media IDs returned by the transcription path,
review the translated script, then synthesize using the appropriate voice and
timing arguments. See the [complete audio workflow](capabilities.md#original-voice-video-workflow).

Dubbing speech or remuxing its soundtrack does not automatically translate
visible text and artwork. Editable motion graphics have a separate After Effects
workflow. Voice cloning requires ownership or speaker permission and the
applicable consent and provider-verification steps.

## Generation, approval and retrying are separate

Generation returns a proposal. Saving memory, applying wording and publishing
an asset are separate operations. Full MCP exposes write/delete tools; a custom
client or agent must enforce the review and permission policy it needs.
The focused ChatGPT tool separately requires explicit approval before saving
exact wording to memory; do not assume this is a universal API approval lock.

For failures, keep the tool name, sanitised error and any completed outputs.
Check the endpoint/authentication pair, media URL expiry, account capabilities
and usage before retrying. A failed multi-part operation can have completed
work before a later error. Do not invent missing results or assume repeating a
generation is free. Share support diagnostics without credentials or private
source content.

## References

- [Live JSON tool schemas](https://mcp.usenativ.com/json-openapi.json)
- [REST request schemas](https://api.usenativ.com/redoc)
- [Complete full-server tool mapping](capabilities.md)
- [Hosted transport and authentication](hosting.md)
- [Nativ integration catalogue](https://www.usenativ.com/integrations/)
