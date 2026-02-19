# Nativ MCP Server

mcp-name: io.github.Nativ-Technologies/nativ

AI-powered localization for any MCP-compatible tool — [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Cursor](https://cursor.sh), [Windsurf](https://codeium.com/windsurf), and more.

[Nativ](https://usenativ.com) is a localization platform that uses AI to translate content while respecting your brand voice, translation memory, glossaries, and style guides. This MCP server brings Nativ's full localization engine into your AI coding workflow.

<a href="https://smithery.ai/server/@nativ-ai/nativ-mcp"><img alt="Smithery" src="https://smithery.ai/badge/@nativ-ai/nativ-mcp"></a>

---

## Why use Nativ via MCP?

- **Translate in-context** — localize strings, copy, and content directly from your editor without switching to a browser
- **Translation Memory aware** — every translation checks your TM first, ensuring consistency across your project
- **Brand voice built-in** — your team's tone, formality, and style guides are applied automatically
- **Review and approve** — add approved translations to TM from your editor, building quality over time
- **Multi-format** — JSON, CSV, Markdown, or freeform text — Nativ handles it all

## Quick Start

### 1. Get a Nativ API Key

Sign up at [dashboard.usenativ.com](https://dashboard.usenativ.com), go to **Settings → API Keys**, and create a key. It looks like `nativ_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.

### 2. Install

#### Claude Code / Claude Desktop

Add to your MCP configuration (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "nativ": {
      "command": "uvx",
      "args": ["nativ-mcp"],
      "env": {
        "NATIV_API_KEY": "nativ_your_api_key_here"
      }
    }
  }
}
```

#### Cursor

Add to your Cursor MCP settings (`.cursor/mcp.json` in your project or global config):

```json
{
  "mcpServers": {
    "nativ": {
      "command": "uvx",
      "args": ["nativ-mcp"],
      "env": {
        "NATIV_API_KEY": "nativ_your_api_key_here"
      }
    }
  }
}
```

#### Windsurf

Add to your Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "nativ": {
      "command": "uvx",
      "args": ["nativ-mcp"],
      "env": {
        "NATIV_API_KEY": "nativ_your_api_key_here"
      }
    }
  }
}
```

> **Note:** `uvx` runs the package directly from PyPI without needing a manual install. If you prefer, install it first with `pip install nativ-mcp` and use `"command": "nativ-mcp"` instead.

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
uv pip install -e ".[dev]"

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
