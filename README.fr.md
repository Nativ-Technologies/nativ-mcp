# Serveur Nativ MCP

mcp-name: io.github.Nativ-Technologies/nativ

Localisation boostée par IA pour tout outil compatible MCP - [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [Cursor](https://cursor.sh), [Windsurf](https://codeium.com/windsurf) et plus encore.

[Nativ](https://usenativ.com) est une plateforme de localisation qui utilise l'IA pour traduire votre contenu tout en respectant la voix de votre marque, la mémoire de traduction, les glossaires et les guides de style. Ce serveur MCP intègre le moteur de localisation complet de Nativ directement dans votre flux de travail de codage IA.

<a href="https://smithery.ai/server/@nativ-ai/nativ-mcp"><img alt="Smithery" src="https://smithery.ai/badge/@nativ-ai/nativ-mcp"></a>

---

## Pourquoi choisir Nativ avec MCP ?

- **Localisez sur le vif** — adaptez chaînes, textes et contenus directement depuis votre éditeur, sans ouvrir de navigateur
- **Mémoire de traduction prise en compte** — chaque traduction interroge d'abord votre TM pour garantir la cohérence de votre projet
- **La voix de votre marque intégrée** — le ton, la formalité et les guides de style de votre équipe appliqués automatiquement
- **Vérifiez et approuvez** — ajoutez les traductions validées à la TM depuis votre éditeur, et améliorez la qualité au fil du temps
- **Tous les formats** — JSON, CSV, Markdown ou texte libre — Nativ gère tout.

## Prise en main rapide

### 1. Obtiens une clé API Nativ

Inscris-toi sur [dashboard.usenativ.com](https://dashboard.usenativ.com), va dans **Paramètres → Clés API** et crée une clé. Elle ressemble à `nativ_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.

### 2. Installer

Ajoutez à votre configuration MCP :

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

#### Cursor (`.cursor/mcp.json` dans votre projet ou `~/.cursor/mcp.json` globalement)

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

> **Remarque :** npx télécharge automatiquement le paquet à la première exécution — pas besoin d'installation manuelle. Si uv n'est pas déjà sur votre machine, il s'installera automatiquement au premier lancement.
>
> <details><summary>Alternative : utilisez <code>uvx</code> directement</summary>
>
> Si uv est déjà installé et que vous préférez passer le wrapper npm :
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
> **Astuce macOS :** si vous voyez `spawn uvx ENOENT` dans Cursor ou Claude Desktop, les apps GUI n'héritent pas du PATH de votre shell. Utilisez le chemin complet (ex. `"command": "/Users/you/.local/bin/uvx"`) ou lancez-les via un shell de connexion : `"command": "/bin/sh", "args": ["-lc", "uvx nativ-mcp"]`.
>
> </details>

### 3. Utilise-le

Demandez à votre assistant IA des choses comme :

- *« Traduis 'Welcome back!' en français et en allemand »*
- *« Consultez notre mémoire de traduction pour les traductions existantes de 'Sign up' »*
- *« Quelles sont nos règles de style pour la localisation ? »*
- *« Localisez ces chaînes i18n pour toutes les langues configurées »*
- *« Compare cette traduction allemande à notre TM et à la voix de la marque »*

## Outils

| Outil | Description |
|-------|-------------|
| `translate` | Traduisez le texte en utilisant l'intégralité du moteur de localisation (TM, guides de style, voix de la marque, glossaire) |
| `translate_batch` | Traduisez plusieurs textes vers une langue cible en un seul appel |
| `search_translation_memory` | Recherche floue dans la mémoire de traduction pour retrouver des traductions existantes |
| `add_translation_memory_entry` | Ajoutez une traduction approuvée au TM pour réutilisation ultérieure |
| `get_languages` | Lister toutes les langues configurées, avec leurs réglages de formalité et de style |
| `get_translation_memory_stats` | Consultez les statistiques TM — nombre total d'entrées, sources et répartition |
| `get_style_guides` | Lister tous les guides de style avec leur contenu et leur statut |
| `get_brand_voice` | Obtenez le prompt de la voix de marque qui façonne toutes les traductions |

## Ressources

| URI | Description |
|-----|-------------|
| `nativ://languages` | Langues configurées (JSON) |
| `nativ://style-guides` | Tous les guides de style (JSON) |
| `nativ://brand-prompt` | Consigne de la voix de la marque (JSON) |
| `nativ://tm/stats` | Statistiques de la mémoire de traduction (JSON) |

## Consignes

| Invite | Description |
|--------|-------------|
| `localize-content` | Parcours guidé pour localiser votre contenu dans les langues cibles |
| `review-translation` | Comparez la traduction à la TM, aux guides de style et à la voix de la marque |
| `batch-localize-strings` | Localisez par lots vos chaînes i18n — sortie structurée |

## Exemples

### Donnez du punch à votre accroche

```
Vous : Traduis "The future of luxury, delivered" en français et en japonais

IA : [appelle l'outil translate pour chaque langue]

Traduction (Français) : "L'avenir du luxe, livré chez vous"
  TM Match : 0% — nouvelle traduction, aucune entrée TM antérieure
  Justification : "Livré chez vous" ajoute une touche personnelle absente du
  littéral "livré", en accord avec la voix premium mais accessible de la marque.

Traduction (Japonais) : "ラグジュアリーの未来を、あなたの元へ"
  TM Match : 45% partiel — motif similaire trouvé dans la TM (source brand_voice)
```

### Consulter les traductions existantes

```
Vous : Avons-nous des traductions pour "Add to cart" dans notre TM ?

IA : [appelle search_translation_memory]

Résultats TM pour "Add to cart" (3 résultats) :
- 95% [fort] "Add to cart" → "Ajouter au panier" (source : approved)
- 95% [fort] "Add to cart" → "In den Warenkorb" (source : brand_voice)
- 72% [partiel] "Add items to cart" → "Ajouter des articles" (source : phrase_tm)
```

### Localisez par lot vos chaînes i18n

```
Vous : Localise ceux-ci en français :
  - "Sign up"
  - "Log in"
  - "Forgot password?"
  - "Continue with Google"

IA : [appelle translate_batch]

Traduction par lot en français (4 éléments) :
1. "Sign up" → "S'inscrire" (TM 100%)
2. "Log in" → "Se connecter" (TM 100%)
3. "Forgot password?" → "Mot de passe oublié ?" (TM 92%)
4. "Continue with Google" → "Continuer avec Google" (TM 85%)
```

## Configuration

| Variable d'environnement | Obligatoire | Description |
|--------------------------|-------------|-------------|
| `NATIV_API_KEY` | Oui | Votre clé API Nativ (`nativ_xxx...`) |
| `NATIV_API_URL` | Non | URL de base de l'API (par défaut : `https://api.usenativ.com`) |

## Comment ça marche

Le serveur MCP fait le lien entre votre assistant de codage IA et l'API Nativ :

```
┌─────────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Claude / Cursor /   │────▶│  Serveur MCP │────▶│   API Nativ     │
│  Windsurf / etc.     │◀────│  Nativ       │◀────│ (Traduction,    │
│                      │     │  (stdio)     │     │  TM, Styles)    │
└─────────────────────┘     └──────────────┘     └─────────────────┘
```

Le serveur MCP s'exécute en local via stdio. Il s'authentifie avec votre clé API et appelle l'API REST de Nativ en votre nom. Votre assistant IA perçoit les outils, ressources et prompts de Nativ comme des capacités natives.

## Développement

```bash
# Clonez le dépôt
git clone https://github.com/nativ-ai/nativ-mcp.git
cd nativ-mcp

# Configurer l'environnement
uv venv
source .venv/bin/activate
uv pip install -e .

# Lance le serveur (pour tests)
NATIV_API_KEY=nativ_xxx nativ-mcp

# Lancez MCP Inspector
NATIV_API_KEY=nativ_xxx npx @modelcontextprotocol/inspector uv run nativ-mcp
```

## Licence

MIT — voir le fichier [LICENSE](LICENSE).

## Liens

- [Plateforme Nativ](https://usenativ.com)
- [Tableau de bord Nativ](https://dashboard.usenativ.com)
- [Protocole MCP](https://modelcontextprotocol.io)
- [Signaler un problème](https://github.com/nativ-ai/nativ-mcp/issues)
