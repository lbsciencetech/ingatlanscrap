# ingatlanscrap

Recherche d'appartements sur [ingatlan.com](https://ingatlan.com) en langage naturel :
tu décris le bien recherché, Claude construit les critères de recherche, un navigateur
Camoufox remplit le formulaire du site et les annonces trouvées s'affichent dans une page web.

```
page Next.js (web/) ──MCP stdio──> mcp_server.py ──> Claude (critères)
                                                 └─> run_search.py + fillform.py ──> Camoufox ──> ingatlan.com
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `fillform.py` | schéma des critères, validation, remplissage du formulaire |
| `run_search.py` | lance Camoufox, soumet la recherche, récupère les annonces et les captures d'écran |
| `mcp_server.py` | serveur MCP : outil `search_flats(description, …)` (appelle Claude avec sa clé ou celle du client) |
| `mcp_client.py` | client MCP en ligne de commande |
| `web/` | page Next.js (client MCP) |
| `Dockerfile`, `docker-compose.yml`, `DEPLOY.md` | déploiement sur un VPS avec ngrok |

## Lancer en local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m camoufox fetch
cp .env.example .env            # mettre au moins ANTHROPIC_API_KEY

# en ligne de commande
.venv/bin/python mcp_client.py --max-results 10 "2 pièces dans le XIe arrondissement, max 90 M Ft"

# ou la page web
cd web && npm ci && npm run dev  # http://localhost:3000
```

Mise en production : voir [DEPLOY.md](DEPLOY.md).

## Avertissement

Ce projet automatise un site tiers : respecte ses conditions d'utilisation et
limite le nombre de requêtes.
