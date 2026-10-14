"""
Nativ MCP Server

Exposes Nativ's AI localization platform as an MCP server, enabling
translation, translation memory, and style guide access from any
MCP-compatible AI tool (Claude Code, Cursor, Windsurf, etc.).
"""

import os
import sys
import json
import logging
import asyncio
import time
import uuid
import httpx
from urllib.parse import urlparse
from typing import Any

from mcp.server import MCPServer

from nativ_mcp.client import NativClient
from nativ_mcp.files import read_file as _read_local_file, read_image as _read_local_image
from nativ_mcp.files import save_base64 as _save_base64_image, save_subtitle
from nativ_mcp.runtime import hosted_request

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("nativ-mcp")
_BATCH_DEADLINE_SECONDS = 240
# Signed media URLs must not appear in httpx request logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client() -> NativClient:
    """Use the hosted caller's key, or the stdio environment key."""
    remote = hosted_request.get()
    api_key = remote.api_key if remote is not None else os.environ.get("NATIV_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NATIV_API_KEY environment variable is required. "
            "Create one at https://dashboard.usenativ.com → Settings → API Keys"
        )
    base_url = os.environ.get("NATIV_API_URL")
    return NativClient(api_key, base_url)


def _fmt_json(data: Any) -> str:
    """Pretty-print JSON for LLM consumption."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "nativ",
    instructions=(
        "Nativ is an AI-powered localization platform. Use the available tools to "
        "translate text, search translation memory, manage TM entries, access "
        "style guides, localize images, transcribe and dub audio/video, and "
        "localize subtitles. Always use the user's configured languages and "
        "respect their brand voice and style settings. Translate related text, "
        "subtitle cues, and voiceover segments together with translate_batch "
        "instead of separate translate calls. Surface translation errors before "
        "synthesizing audio or assembling video."
    ),
)


# ===================== TOOLS =====================


@mcp.tool()
async def translate(
    text: str,
    target_language: str,
    target_language_code: str = "",
    source_language: str = "English",
    source_language_code: str = "en",
    context: str = "",
    glossary: str = "",
    formality: str = "",
    max_characters: int = 0,
    backtranslate: bool = False,
) -> str:
    """Translate text using Nativ's AI localization engine.

    Uses the team's translation memory, style guides, and brand voice
    automatically. Returns the translation along with TM match info and
    rationale.

    Args:
        text: The text to translate.
        target_language: Full target language name (e.g. "French", "German", "Japanese").
        target_language_code: Optional ISO language code (e.g. "fr", "de", "ja").
        source_language: Source language name. Defaults to English.
        source_language_code: Source language code. Defaults to "en".
        context: Optional context to guide the translation (e.g. "marketing headline for Gen Z audience").
        glossary: Optional inline glossary as CSV (e.g. "term,translation\\nbrand,marque").
        formality: Tone override — one of: very_informal, informal, neutral, formal, very_formal.
        max_characters: Optional strict character limit for the translation output.
        backtranslate: If true, also returns a back-translation to verify intent.
    """
    client = _get_client()
    result = await client.translate(
        text=text,
        language=target_language,
        language_code=target_language_code or None,
        source_language=source_language,
        source_language_code=source_language_code,
        context=context or None,
        glossary=glossary or None,
        formality=formality or None,
        max_characters=max_characters if max_characters > 0 else None,
        backtranslate=backtranslate,
    )

    parts = [f"**Translation ({target_language}):** {result.get('translated_text', '')}"]

    tm = result.get("tm_match")
    if tm and tm.get("score", 0) > 0:
        parts.append(f"\n**TM Match:** {tm['score']:.0f}% ({tm.get('match_type', 'unknown')}) — source: {tm.get('tm_source', 'N/A')}")
        if tm.get("source_text"):
            parts.append(f"  TM reference: \"{tm['source_text']}\" → \"{tm.get('target_text', '')}\"")

    if result.get("backtranslation"):
        parts.append(f"\n**Back-translation:** {result['backtranslation']}")

    if result.get("rationale"):
        parts.append(f"\n**Rationale:** {result['rationale']}")

    return "\n".join(parts)


@mcp.tool()
async def translate_batch(
    texts: list[str],
    target_language: str,
    target_language_code: str = "",
    source_language: str = "English",
    source_language_code: str = "en",
    context: str = "",
    formality: str = "",
) -> str:
    """Translate multiple texts to a single target language.

    Use for lists of strings, UI labels, i18n files, subtitle cues, and
    voiceover segments. Prefer one batch over separate translate calls.
    Texts are translated together using the team's TM and style guides.
    A failed or incomplete batch is a tool error; do not synthesize its output.

    Args:
        texts: List of texts to translate.
        target_language: Full target language name (e.g. "French").
        target_language_code: Optional ISO language code.
        source_language: Source language name. Defaults to English.
        source_language_code: Source language code. Defaults to "en".
        context: Optional context to guide all translations.
        formality: Tone override for all translations.
    """
    client = _get_client()
    batch_id = uuid.uuid4().hex
    started = time.monotonic()
    logger.info("event=mcp_batch_start batch_id=%s tool=translate_batch items=%s", batch_id, len(texts))
    try:
        translated_results = await asyncio.wait_for(client.translate_batch(
            texts, target_language, language_code=target_language_code or None,
            source_language=source_language, source_language_code=source_language_code,
            context=context or None, formality=formality or None,
        ), timeout=_BATCH_DEADLINE_SECONDS)
    except TimeoutError as exc:
        logger.warning("event=mcp_batch_timeout batch_id=%s elapsed_s=%.3f", batch_id, time.monotonic() - started)
        raise RuntimeError("Batch translation exceeded its 240-second deadline. No complete batch was returned; split the input before trying again.") from exc
    except Exception as exc:
        logger.warning("event=mcp_batch_failed batch_id=%s error_type=%s elapsed_s=%.3f", batch_id, type(exc).__name__, time.monotonic() - started)
        if isinstance(exc, httpx.TimeoutException):
            raise RuntimeError("Nativ timed out during batch translation. No complete batch was returned.") from exc
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            reason = " The backend translation deadline was exceeded." if status == 504 else ""
            raise RuntimeError(f"Nativ batch translation failed (HTTP {status}).{reason} No complete batch was returned.") from exc
        raise
    logger.info("event=mcp_batch_complete batch_id=%s items=%s elapsed_s=%.3f", batch_id, len(texts), time.monotonic() - started)
    results = []
    for i, (text, result) in enumerate(zip(texts, translated_results)):
        tm = result.get("tm_match")
        tm_note = f" (TM {tm['score']:.0f}%)" if tm and tm.get("score", 0) > 0 else ""
        results.append(f"{i+1}. \"{text}\" → \"{result['translated_text']}\"{tm_note}")

    header = f"**Batch translation to {target_language}** ({len(texts)} items):\n"
    return header + "\n".join(results)


@mcp.tool()
async def search_translation_memory(
    query: str,
    source_language_code: str = "en",
    target_language_code: str = "",
    min_score: float = 0.0,
    limit: int = 10,
) -> str:
    """Search the translation memory for existing translations.

    Use this to check if translations already exist before creating new ones,
    or to find reference translations for consistency.

    Args:
        query: Text to search for in the translation memory.
        source_language_code: Source language code (default: "en").
        target_language_code: Optional target language code to filter results.
        min_score: Minimum fuzzy match score (0-100). Default 0 returns all.
        limit: Maximum number of results (default 10).
    """
    client = _get_client()
    result = await client.search_tm(
        query=query,
        source_lang=source_language_code,
        target_lang=target_language_code or None,
        score_cutoff=min_score,
        limit=limit,
    )

    matches = result.get("matches", [])
    if not matches:
        return f"No translation memory matches found for \"{query}\"."

    lines = [f"**TM Search Results** for \"{query}\" ({len(matches)} matches):\n"]
    for m in matches:
        lines.append(
            f"- **{m['score']:.0f}%** [{m.get('match_type', '')}] "
            f"\"{m['source_text']}\" → \"{m['target_text']}\" "
            f"(source: {m.get('information_source', 'N/A')})"
        )
    return "\n".join(lines)


@mcp.tool()
async def add_translation_memory_entry(
    source_text: str,
    target_text: str,
    source_language_code: str,
    target_language_code: str,
    name: str = "",
) -> str:
    """Add a new entry to the translation memory.

    Use this to store approved translations so they are reused in future
    localizations.

    Args:
        source_text: The original text.
        target_text: The approved translation.
        source_language_code: Source language code (e.g. "en").
        target_language_code: Target language code (e.g. "fr-FR").
        name: Optional label for this entry (e.g. "homepage hero copy").
    """
    client = _get_client()
    result = await client.add_tm_entry(
        source_text=source_text,
        target_text=target_text,
        source_language_code=source_language_code,
        target_language_code=target_language_code,
        source_name=name or None,
    )
    return (
        f"Added TM entry: \"{source_text}\" ({source_language_code}) "
        f"→ \"{target_text}\" ({target_language_code})"
    )


@mcp.tool()
async def get_languages() -> str:
    """Get all languages configured for the Nativ workspace.

    Returns language names, codes, formality settings, and custom style
    directives for each language.
    """
    client = _get_client()
    result = await client.get_languages()
    languages = result.get("languages", [])

    if not languages:
        return "No languages configured. Set up languages at https://dashboard.usenativ.com"

    lines = [f"**Configured Languages** ({len(languages)}):\n"]
    for lang in languages:
        formality = lang.get("formality") or "neutral"
        parts = [f"- **{lang['language']}** (`{lang['language_code']}`) — formality: {formality}"]
        if lang.get("custom_style"):
            parts.append(f"  Custom style: {lang['custom_style']}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


@mcp.tool()
async def get_translation_memory_stats() -> str:
    """Get statistics about the translation memory.

    Shows total entries, enabled/disabled counts, and breakdown by source type.
    """
    client = _get_client()
    stats = await client.get_tm_stats()

    lines = [
        "**Translation Memory Statistics:**\n",
        f"- Total entries: {stats.get('total', 0)}",
        f"- Enabled: {stats.get('enabled', 0)}",
        f"- Disabled: {stats.get('disabled', 0)}",
    ]

    by_source = stats.get("by_source", {})
    if by_source:
        lines.append("\n**By Source:**")
        source_labels = {
            "brand_voice": "Brand Voice",
            "phrase_tm": "Phrase TM",
            "phrase_tb": "Phrase Term Base",
            "user_glossary": "User Glossary",
            "approved": "Approved Translations",
            "manual": "Manual Entries",
        }
        for src, counts in by_source.items():
            label = source_labels.get(src, src)
            lines.append(f"- {label}: {counts.get('total', 0)} entries ({counts.get('enabled', 0)} enabled)")

    return "\n".join(lines)


@mcp.tool()
async def get_style_guides() -> str:
    """Get all style guides configured for the workspace.

    Returns the titles, content, and enabled status of each style guide.
    """
    client = _get_client()
    result = await client.list_style_guides()
    guides = result.get("guides", [])

    if not guides:
        return "No custom style guides configured. Create them at https://dashboard.usenativ.com → Settings → Style Guides"

    lines = [f"**Style Guides** ({len(guides)}):\n"]
    for g in guides:
        status = "enabled" if g.get("is_enabled") else "disabled"
        lines.append(f"### {g.get('title', 'Untitled')} ({status})")
        content = g.get("content", "")
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def get_brand_voice() -> str:
    """Get the brand voice prompt — the core localization personality.

    This is the master prompt that shapes all translations. It captures
    the brand's tone, personality, terminology, and localization guidelines.
    """
    client = _get_client()
    result = await client.get_brand_prompt()

    if not result.get("exists"):
        return "No brand voice prompt configured. Set one up at https://dashboard.usenativ.com → Settings → Style Guides"

    prompt = result.get("prompt", "")
    if len(prompt) > 2000:
        return f"**Brand Voice Prompt:**\n\n{prompt[:2000]}...\n\n(Truncated — full prompt has {len(prompt)} characters)"
    return f"**Brand Voice Prompt:**\n\n{prompt}"


@mcp.tool()
async def extract_image_text(image_path: str) -> str:
    """Extract text segments from an image, in reading order (OCR).

    Use this as the first step when localizing an image: pull out the
    on-image source strings, translate each with `translate` (so TM, style
    guides, and brand voice apply), then re-render with `localize_image`.

    Args:
        image_path: Public HTTPS URL (hosted) or local path (stdio) to a PNG, JPEG, or WebP image file.
    """
    client = _get_client()
    image_bytes, filename, content_type = await _read_local_image(image_path)
    result = await client.extract_image_segments(image_bytes, filename, content_type)

    segments = [s.get("text", "") for s in result.get("segments", []) if s.get("text")]
    if not segments:
        return f"No text found in {filename}."

    lines = [f"**Extracted {len(segments)} text segment(s) from {filename}:**\n"]
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}. {seg}")
    return "\n".join(lines)


@mcp.tool()
async def localize_image(
    image_path: str,
    replacements: str,
    target_language_code: str,
    output_path: str = "",
    num_images: int = 1,
    output_format: str = "png",
) -> str:
    """Localize an image in place by replacing its on-image text with translations.

    Keeps every non-text element (layout, colours, graphics) intact and
    re-renders the original text with the provided translations. Pair with
    `extract_image_text` (to get the source strings) and `translate` (to
    translate them with TM and brand voice) for a full image localization flow.

    The localized image is saved to disk and the file path is returned — the
    raw image bytes are not sent back to the model. Hosted mode returns a
    download URL instead of writing to a local path.

    Args:
        image_path: Public HTTPS URL (hosted) or local path (stdio) to a PNG, JPEG, or WebP image to localize.
        replacements: JSON array of {"original": "...", "translated": "..."} pairs,
            e.g. '[{"original": "Buy now", "translated": "Achetez maintenant"}]'.
        target_language_code: Target language code (e.g. "fr-FR"), used for labelling output.
        output_path: Optional path to write the localized image to. Defaults to
            "<input>.<lang>.<format>" next to the source image.
        num_images: Number of variants to generate (1-5, default 1).
        output_format: Output format — png, jpeg, or webp (default png).
    """
    client = _get_client()

    try:
        parsed = json.loads(replacements)
    except json.JSONDecodeError as e:
        return (
            "`replacements` must be a JSON array of "
            '{"original": "...", "translated": "..."} objects. '
            f"Parse error: {e}"
        )
    if not isinstance(parsed, list) or not parsed:
        return '`replacements` must be a non-empty JSON array of {"original", "translated"} objects.'

    image_bytes, filename, content_type = await _read_local_image(image_path)
    result = await client.localize_image(
        image_bytes,
        filename,
        content_type,
        replacements_json=replacements,
        language_code=target_language_code,
        num_images=num_images,
        output_format=output_format,
    )

    images = result.get("images", [])
    if not images:
        return "No localized image was returned by Nativ."

    source_name = urlparse(image_path).path if hosted_request.get() is not None else os.path.expanduser(image_path)
    base, _ = os.path.splitext(source_name)
    saved: list[str] = []
    for idx, img in enumerate(images):
        b64 = img.get("image_base64")
        if not b64:
            continue
        if output_path:
            if len(images) == 1:
                out = os.path.expanduser(output_path)
            else:
                ob, oe = os.path.splitext(os.path.expanduser(output_path))
                out = f"{ob}_{idx + 1}{oe or '.' + output_format}"
        else:
            suffix = f"_{idx + 1}" if len(images) > 1 else ""
            out = f"{base}.{target_language_code}{suffix}.{output_format}"
        saved.append(await _save_base64_image(b64, out))

    if not saved:
        return "Nativ returned a response but no image data could be decoded."

    meta = result.get("metadata", {})
    lines = [f"**Localized image saved ({len(saved)}):**"]
    lines.extend(f"- {p}" for p in saved)
    if meta:
        lines.append(f"\nCost: {meta.get('cost', '?')} credits · images: {meta.get('num_images', len(saved))}")
    return "\n".join(lines)


@mcp.tool()
async def check_image_cultural_fit(image_path: str, countries: str = "") -> str:
    """Analyze an image for cultural-sensitivity issues across markets before launch.

    Returns a SAFE / NOT SAFE verdict and, where relevant, the specific
    countries affected with the issue and a concrete fix.

    Args:
        image_path: Public HTTPS URL (hosted) or local path (stdio) to a PNG, JPEG, or WebP image.
        countries: Optional comma-separated list of countries to check against
            (e.g. "Saudi Arabia, Japan, France"). Defaults to the top markets by GDP.
    """
    client = _get_client()
    image_bytes, filename, content_type = await _read_local_image(image_path)
    country_list = [c.strip() for c in countries.split(",") if c.strip()] if countries else []
    result = await client.inspect_image(
        image_bytes, filename, content_type, countries=country_list
    )

    verdict = result.get("verdict", "UNKNOWN")
    affected = result.get("affected_countries", [])

    lines = [f"**Cultural sensitivity verdict: {verdict}**"]
    if not affected:
        lines.append("\nNo issues found across the analyzed markets.")
    else:
        for ac in affected:
            lines.append(f"\n**{ac.get('country', 'Unknown market')}**")
            lines.append(f"- Issue: {ac.get('issue', '')}")
            lines.append(f"- Suggestion: {ac.get('suggestion', '')}")
    return "\n".join(lines)


from nativ_mcp.media_tools import register_media_tools

register_media_tools(mcp, _get_client, _read_local_file, _save_base64_image, save_subtitle)


# ===================== RESOURCES =====================


@mcp.resource("nativ://languages")
async def resource_languages() -> str:
    """Configured languages with formality and style settings."""
    client = _get_client()
    result = await client.get_languages()
    return _fmt_json(result)


@mcp.resource("nativ://style-guides")
async def resource_style_guides() -> str:
    """All style guides including enabled/disabled status."""
    client = _get_client()
    result = await client.list_style_guides()
    return _fmt_json(result)


@mcp.resource("nativ://brand-prompt")
async def resource_brand_prompt() -> str:
    """The master brand voice prompt used for all translations."""
    client = _get_client()
    result = await client.get_brand_prompt()
    return _fmt_json(result)


@mcp.resource("nativ://tm/stats")
async def resource_tm_stats() -> str:
    """Translation memory statistics and source breakdown."""
    client = _get_client()
    result = await client.get_tm_stats()
    return _fmt_json(result)


# ===================== PROMPTS =====================


@mcp.prompt()
def localize_content(
    content: str,
    target_languages: str = "",
    context: str = "",
) -> str:
    """Localize content into target languages using Nativ.

    Args:
        content: The content to localize.
        target_languages: Comma-separated list of target languages (e.g. "French, German, Japanese"). Leave empty to use all configured languages.
        context: Optional context about the content (e.g. "marketing email subject line").
    """
    parts = [
        "You are helping localize content using Nativ's AI localization platform.\n",
        "## Instructions\n",
        "1. First, call `get_languages` to see which languages are configured and their formality/style settings.",
        "2. Call `get_brand_voice` to understand the brand's localization personality.",
    ]

    if target_languages:
        parts.append(f"3. Translate the content below into: **{target_languages}**")
    else:
        parts.append("3. Translate the content below into **all configured languages**.")

    parts.extend([
        "4. For each language, use the `translate` tool with the appropriate formality and context.",
        "5. Present results in a clear table: Source | Language | Translation | TM Match %",
        "",
        "## Content to Localize\n",
        content,
    ])

    if context:
        parts.extend(["", f"## Context\n", context])

    return "\n".join(parts)


@mcp.prompt()
def review_translation(
    source_text: str,
    translated_text: str,
    target_language: str,
) -> str:
    """Review a translation for quality and consistency with TM and style guides.

    Args:
        source_text: The original text.
        translated_text: The translation to review.
        target_language: The target language name.
    """
    return "\n".join([
        "You are reviewing a translation for quality using Nativ.\n",
        "## Instructions\n",
        "1. Call `get_brand_voice` to understand the brand's localization guidelines.",
        "2. Call `get_style_guides` to check for any relevant style rules.",
        f"3. Call `search_translation_memory` with the source text to find existing TM matches for {target_language}.",
        "4. Compare the translation against TM matches and style guides.",
        "5. Provide feedback on:",
        "   - Accuracy: Does it preserve the original meaning?",
        "   - Consistency: Does it match existing TM entries?",
        "   - Brand voice: Does it follow style guide rules?",
        "   - Tone: Is the formality level appropriate?",
        "6. If the translation is good, suggest adding it to TM with `add_translation_memory_entry`.",
        "",
        f"## Source Text\n{source_text}",
        "",
        f"## Translation ({target_language})\n{translated_text}",
    ])


@mcp.prompt()
def batch_localize_strings(
    strings: str,
    target_languages: str = "",
    format_hint: str = "json",
) -> str:
    """Batch-localize i18n strings for a software project.

    Args:
        strings: The strings to localize — can be JSON, CSV, or one-per-line.
        target_languages: Comma-separated target languages. Leave empty for all configured.
        format_hint: Expected output format: "json", "csv", or "plain".
    """
    return "\n".join([
        "You are batch-localizing i18n strings using Nativ.\n",
        "## Instructions\n",
        "1. Call `get_languages` to see configured languages.",
        f"2. Parse the strings below (format hint: {format_hint}).",
        "3. Use `translate_batch` for each target language to translate all strings at once.",
        f"4. Output results in **{format_hint}** format, preserving the original keys/structure.",
        "5. If any TM matches are >= 90%, note them — these are well-established translations.",
        "",
        f"## Target Languages\n{target_languages if target_languages else '(all configured languages)'}",
        "",
        f"## Strings\n```\n{strings}\n```",
    ])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
