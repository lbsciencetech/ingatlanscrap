# ingatlanscrap — Flat finder

Recherche d'appartements sur [ingatlan.com](https://ingatlan.com) **en langage naturel**.
Tu décris le bien voulu (en hongrois, anglais ou français), Claude le traduit en critères
de recherche, un vrai navigateur remplit le formulaire du site, et les annonces trouvées
s'affichent dans une page web.

> *« Un 3 pièces rénové dans le XIe arrondissement, moins de 90 M Ft, avec balcon et ascenseur »*
> → la recherche ingatlan.com correspondante, et la liste des annonces.

## Comment ça marche

```
page web (Next.js)  ──MCP stdio──>  mcp_server.py ──> Claude : description → critères (validés)
                                                  └─> Camoufox : remplit le formulaire ingatlan.com
                                                                 et lit les pages de résultats
```

1. **Tu décris** ce que tu cherches, en quelques mots.
2. **Claude construit la recherche** : il produit les champs exacts du formulaire
   d'ingatlan.com. Un validateur vérifie chaque valeur ; en cas d'erreur, Claude corrige
   (jusqu'à 3 essais).
3. **Un navigateur la lance** : [Camoufox](https://camoufox.com) (Firefox furtif) ouvre le
   site, remplit le formulaire champ par champ et le soumet.
4. **Les annonces reviennent** dans la page, avec un lien vers chaque annonce et vers la
   recherche complète sur ingatlan.com. Des captures d'écran sont disponibles en option.

ingatlan.com n'a pas d'API publique : remplir le vrai formulaire garantit des résultats
identiques à ceux du site.

## Clé API Anthropic (obligatoire)

L'application appelle Claude : **une clé API Anthropic est obligatoire**. Crée-la sur
[console.anthropic.com](https://console.anthropic.com/settings/keys).

- **Page web** : chaque utilisateur saisit sa clé dans le champ prévu. Elle est envoyée
  avec chaque recherche uniquement et n'est jamais stockée. Sans clé, la recherche ne
  part pas.
- **Ligne de commande** : mets `ANTHROPIC_API_KEY` dans `.env` (ou dans l'environnement).

## Installation locale

Prérequis : Python 3 et Node.js récents (l'image Docker utilise Python 3.14 et Node.js 24).

```bash
git clone https://github.com/lbsciencetech/ingatlanscrap.git
cd ingatlanscrap

# serveur Python + navigateur
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m camoufox fetch      # télécharge le navigateur Camoufox

cp .env.example .env                    # clé utilisée par le client en ligne de commande
```

### Page web

```bash
cd web
npm ci
npm run dev                             # http://localhost:3000
```

Saisis ta clé API, décris le bien, puis **Search**. Le mode *Build search only* demande
seulement les critères à Claude, sans lancer le navigateur.

### Ligne de commande

```bash
.venv/bin/python mcp_client.py --max-results 10 "2 pièces dans le XIe arrondissement, max 90 M Ft"
.venv/bin/python mcp_client.py --dry-run "studio à Budapest VIII, moins de 40 M Ft"
.venv/bin/python mcp_client.py --screenshots shots/ "3 pièces avec balcon, XIII"
```

## Structure du projet

| Fichier | Rôle |
|---|---|
| `fillform.py` | schéma des critères, validation, remplissage du formulaire |
| `run_search.py` | lance Camoufox, soumet la recherche, récupère les annonces et les captures |
| `mcp_server.py` | serveur MCP : outil `search_flats(description, dry_run, max_results, screenshots)` |
| `mcp_client.py` | client MCP en ligne de commande |
| `web/` | page Next.js (client MCP, diffuse la progression en continu) |
| `Dockerfile`, `docker-compose.yml` | image unique (page + serveur + navigateur) et tunnel ngrok |
| `DEPLOY.md` | mise en ligne sur un VPS |

## Mise en production

Un conteneur Docker et un tunnel [ngrok](https://ngrok.com) suffisent : pas de nom de
domaine, pas de certificat, aucun port ouvert. La page est protégée par mot de passe
(HTTP Basic). Guide pas à pas : **[DEPLOY.md](DEPLOY.md)**.

## Avertissement

Ce projet automatise un site tiers : respecte ses conditions d'utilisation et limite le
nombre de requêtes. Chaque recherche consomme des tokens sur la clé API utilisée.
