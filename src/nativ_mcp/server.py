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
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("nativ-mcp")

# ---------------------------------------------------------------------------
# Nativ API client
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "https://api.usenativ.com"


class NativClient:
    """Thin async wrapper around the Nativ REST API."""

    def __init__(self, api_key: str, base_url: str | None = None):
        self.base_url = (base_url or DEFAULT_API_URL).rstrip("/")
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "nativ-mcp/0.1.0",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client() -> NativClient:
    """Build a NativClient from env vars. Raises on missing key."""
    api_key = os.environ.get("NATIV_API_KEY")
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

mcp = FastMCP(
    "nativ",
    instructions=(
        "Nativ is an AI-powered localization platform. Use the available tools to "
        "translate text, search translation memory, manage TM entries, and access "
        "style guides. Always use the user's configured languages and respect their "
        "brand voice and style settings."
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

    Useful for localizing lists of strings, UI labels, or i18n files.
    Each text is translated individually using the team's TM and style guides.

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
    results = []
    for i, text in enumerate(texts):
        try:
            result = await client.translate(
                text=text,
                language=target_language,
                language_code=target_language_code or None,
                source_language=source_language,
                source_language_code=source_language_code,
                context=context or None,
                formality=formality or None,
                include_tm_info=True,
                backtranslate=False,
                include_rationale=False,
            )
            translated = result.get("translated_text", "")
            tm = result.get("tm_match")
            tm_note = ""
            if tm and tm.get("score", 0) > 0:
                tm_note = f" (TM {tm['score']:.0f}%)"
            results.append(f"{i+1}. \"{text}\" → \"{translated}\"{tm_note}")
        except Exception as e:
            results.append(f"{i+1}. \"{text}\" → ERROR: {e}")

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
