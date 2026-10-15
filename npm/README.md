# Nativ MCP Server

mcp-name: io.github.Nativ-Technologies/nativ

AI-powered localization for any MCP-compatible tool — [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Cursor](https://cursor.sh), [Windsurf](https://codeium.com/windsurf), and more.

[Nativ](https://usenativ.com) is a localization platform that uses AI to translate content while respecting your brand voice, translation memory, glossaries, and style guides. This MCP server brings Nativ's full localization engine into your AI coding workflow.

<a href="https://smithery.ai/server/@nativ-ai/nativ-mcp"><img alt="Smithery" src="https://smithery.ai/badge/@nativ-ai/nativ-mcp"></a>
[![MCP Badge](https://lobehub.com/badge/mcp/nativ-ai-nativ-mcp)](https://lobehub.com/mcp/nativ-ai-nativ-mcp)

---

## Why use Nativ via MCP?

- **Translate in-context** — localize strings, copy, and content directly from your editor without switching to a browser
- **Translation Memory aware** — every translation checks your TM first, ensuring consistency across your project
- **Brand voice built-in** — your team's tone, formality, and style guides are applied automatically
- **Review and approve** — add approved translations to TM from your editor, building quality over time
- **Multi-format** — JSON, CSV, Markdown, or freeform text — Nativ handles it all

## Quick Start

For a remote Streamable HTTP connection, see [Hosted MCP](docs/hosting.md).
Hosted calls use your API key in `X-API-Key`; the stdio setup below uses
`NATIV_API_KEY` in the environment.
JSON-only API clients can import [the tools schema](https://mcp.usenativ.com/json-openapi.json)
and call `/tools/{tool_name}` with HTTPS media URLs.

### 1. Get a Nativ API Key

Sign up at [dashboard.usenativ.com](https://dashboard.usenativ.com), go to **Settings → API Keys**, and create a key. It looks like `nativ_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.

### 2. Install

Add to your MCP configuration:

#### Claude Code / Claude Desktop (`~/.claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "nativ": {
      "command": "npx",
      "args": ["-y", "nativ-mcp"],
      "env": {
        "NATIV_API_KEY": "nativ_your_api_key_here"
      }
    }
  }
}
```

#### Cursor (`.cursor/mcp.json` in your project or `~/.cursor/mcp.json` globally)

```json
{
  "mcpServers": {
    "nativ": {
      "command": "npx",
      "args": ["-y", "nativ-mcp"],
      "env": {
        "NATIV_API_KEY": "nativ_your_api_key_here"
      }
    }
  }
}
```

#### Windsurf

```json
{
  "mcpServers": {
    "nativ": {
      "command": "npx",
      "args": ["-y", "nativ-mcp"],
      "env": {
        "NATIV_API_KEY": "nativ_your_api_key_here"
      }
    }
  }
}
```

> **Note:** `npx` auto-downloads the package on first run — no manual install needed. If `uv` isn't already on your machine, it will be installed automatically on first launch.
>
> <details><summary>Alternative: use <code>uvx</code> directly</summary>
>
> If you already have `uv` installed and prefer to skip the npm wrapper:
>
> ```json
> {
>   "mcpServers": {
>     "nativ": {
>       "command": "uvx",
>       "args": ["nativ-mcp"],
>       "env": {
>         "NATIV_API_KEY": "nativ_your_api_key_here"
>       }
>     }
>   }
> }
> ```
>
> **macOS tip:** If you get `spawn uvx ENOENT` in Cursor or Claude Desktop, GUI apps don't inherit your shell PATH. Use the full path (e.g. `"command": "/Users/you/.local/bin/uvx"`) or wrap in a login shell: `"command": "/bin/sh", "args": ["-lc", "uvx nativ-mcp"]`.
>
> </details>

### 3. Use it

Ask your AI assistant things like:

- *"Translate 'Welcome back!' to French and German"*
- *"Check our translation memory for existing translations of 'Sign up'"*
- *"What are our style guides for localization?"*
- *"Localize these i18n strings to all configured languages"*
- *"Review this German translation against our TM and brand voice"*

## Tools

| Tool | Description |
|------|-------------|
| `translate` | Translate text using the full localization engine (TM, style guides, brand voice, glossary) |
| `translate_batch` | Translate multiple texts to a target language in one call |
| `search_translation_memory` | Fuzzy-search the translation memory for existing translations |
| `add_translation_memory_entry` | Add an approved translation to TM for future reuse |
| `get_languages` | List all configured languages with formality and style settings |
| `get_translation_memory_stats` | Get TM statistics — total entries, sources, and breakdown |
| `get_style_guides` | List all style guides with their content and status |
| `get_brand_voice` | Get the brand voice prompt that shapes all translations |
| `extract_image_text` | Extract on-image text segments (OCR) in reading order |
| `localize_image` | Replace on-image text with translations in place, keeping layout and graphics intact |
| `check_image_cultural_fit` | Flag cultural-sensitivity issues in an image across target markets |
| `transcribe_audio` | Speech-to-text for a local audio or video file (draft; billed on synthesize) |
| `parse_audio_script` | Parse a script (.txt/.docx/.pdf/.srt) instead of running STT |
| `list_voices` | List TTS voices for dubbing |
| `preview_voice` | Save a short TTS preview WAV to disk |
| `get_voice_consent_script` | Consent copy required for voice cloning |
| `synthesize_audio` | Generate billed localized TTS (and optional dubbed MP4) and save to disk |
| `register_video` | Store a source video for later remux |
| `remux_video` | Mux a WAV onto a registered video |
| `parse_subtitle` | Parse a local SRT/ITT into timed cues |
| `localize_subtitles` | Localize subtitles in-memory from SRT/ITT and/or video STT |

| `clone_voice` | Create a Google voice clone from reference speech and spoken consent |
| `create_byo_voice` | Create and save an original-speaker clone from audio/video, or a Google clone with consent |
| `delete_saved_voice` | Delete a saved cloned voice when requested |
| `get_audio_capabilities` | Read account media duration limits and long-form eligibility |
| `transcribe_audio_detailed` | Return complete transcript segments, speaker IDs, timings and media IDs |
| `translate_dialogue` | Translate related speaker turns together, with timing and review details |
| `synthesize_audio_advanced` | Dub with speaker-specific voices, music, timing and complete review data |
| `upload_subtitle` | Save an SRT/ITT source, with optional auto-localization |
| `list_subtitles` | List saved subtitle sources and localized files |
| `localize_subtitle_file` | Localize an already saved ITT source |
| `get_subtitle_download_url` | Get an expiring download URL for a saved subtitle |
| `delete_subtitle` | Delete a saved subtitle when requested |
| `get_subtitle_review` | Read subtitle QC rows and approval status |
| `update_subtitle_review` | Save reviewed subtitle translations and approvals |
| `export_subtitle` | Export subtitles with review edits, or a QC workbook |
| `list_translation_memory_entries` | List and paginate TM entries with IDs |
| `update_translation_memory_entry` | Edit or enable/disable an existing TM entry |
| `delete_translation_memory_entry` | Delete a TM entry when requested |
| `list_language_settings` | Get complete language settings with IDs for updates |
| `get_language_formality_options` | List supported formality settings |
| `update_language_formality` | Save a workspace language's formality |
| `update_language_custom_style` | Save or clear per-language style instructions |
| `list_style_guides` | Get complete style-guide content and IDs for editing |
| `get_combined_prompt` | Read the combined brand prompt and enabled style guides |
| `create_style_guide` | Create a workspace style guide |
| `update_style_guide` | Edit or enable/disable an existing style guide |
| `delete_style_guide` | Delete a style guide when requested |
| `upload_style_guide` | Import a style guide from .txt or .docx |
| `reorder_style_guides` | Save the order of style guides |
| `submit_translation_feedback` | Save feedback or an approval rating |

All 51 tools are shared by local and hosted MCP. Existing tools retain their
arguments and results. Voice cloning uses the existing API and requires the
user’s ownership/permission confirmation. See the
[workflow coverage audit](https://github.com/Nativ-Technologies/nativ-mcp/blob/main/docs/capabilities.md)
for original-voice dubbing and saved-subtitle examples.

## Resources

| URI | Description |
|-----|-------------|
| `nativ://languages` | Configured languages (JSON) |
| `nativ://style-guides` | All style guides (JSON) |
| `nativ://brand-prompt` | Brand voice prompt (JSON) |
| `nativ://tm/stats` | Translation memory statistics (JSON) |

## Prompts

| Prompt | Description |
|--------|-------------|
| `localize-content` | Guided workflow to localize content into target languages |
| `review-translation` | Review a translation against TM, style guides, and brand voice |
| `batch-localize-strings` | Batch-localize i18n strings with structured output |

## Examples

### Translate a marketing headline

```
You: Translate "The future of luxury, delivered" to French and Japanese

AI: [calls translate tool for each language]

Translation (French): "L'avenir du luxe, livré chez vous"
  TM Match: 0% — new translation, no prior TM entries
  Rationale: "Livré chez vous" adds a personal touch absent from the literal
  "livré", aligning with the brand's premium yet approachable voice.

Translation (Japanese): "ラグジュアリーの未来を、あなたの元へ"
  TM Match: 45% partial — similar pattern found in TM from brand_voice source
```

### Check existing translations

```
You: Do we have translations for "Add to cart" in our TM?

AI: [calls search_translation_memory]

TM Search Results for "Add to cart" (3 matches):
- 95% [strong] "Add to cart" → "Ajouter au panier" (source: approved)
- 95% [strong] "Add to cart" → "In den Warenkorb" (source: brand_voice)
- 72% [partial] "Add items to cart" → "Ajouter des articles" (source: phrase_tm)
```

### Batch localize i18n strings

```
You: Localize these to French:
  - "Sign up"
  - "Log in"
  - "Forgot password?"
  - "Continue with Google"

AI: [calls translate_batch]

Batch translation to French (4 items):
1. "Sign up" → "S'inscrire" (TM 100%)
2. "Log in" → "Se connecter" (TM 100%)
3. "Forgot password?" → "Mot de passe oublié ?" (TM 92%)
4. "Continue with Google" → "Continuer avec Google" (TM 85%)
```

## Configuration

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `NATIV_API_KEY` | Yes | Your Nativ API key (`nativ_xxx...`) |
| `NATIV_API_URL` | No | API base URL (defaults to `https://api.usenativ.com`) |

## How It Works

This MCP server acts as a bridge between your AI coding assistant and the Nativ API:

```
┌─────────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Claude / Cursor /   │────▶│  Nativ MCP   │────▶│   Nativ API     │
│  Windsurf / etc.     │◀────│  Server      │◀────│ (Translation,   │
│                      │     │  (stdio)     │     │  TM, Styles)    │
└─────────────────────┘     └──────────────┘     └─────────────────┘
```

The MCP server runs locally via stdio. It authenticates with your API key and calls the Nativ REST API on your behalf. Your AI assistant sees Nativ's tools, resources, and prompts as native capabilities.

## Development

```bash
# Clone the repo
git clone https://github.com/nativ-ai/nativ-mcp.git
cd nativ-mcp

# Set up environment
uv venv
source .venv/bin/activate
uv pip install -e .

# Run the server (for testing)
NATIV_API_KEY=nativ_xxx nativ-mcp

# Run with MCP Inspector
NATIV_API_KEY=nativ_xxx npx @modelcontextprotocol/inspector uv run nativ-mcp
```

## License

MIT — see [LICENSE](LICENSE).

## Links

- [Nativ Platform](https://usenativ.com)
- [Nativ Dashboard](https://dashboard.usenativ.com)
- [MCP Protocol](https://modelcontextprotocol.io)
- [Report Issues](https://github.com/nativ-ai/nativ-mcp/issues)
