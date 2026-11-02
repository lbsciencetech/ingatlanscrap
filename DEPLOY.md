# Mettre Flat finder en ligne (VPS + Docker + ngrok)

Tout tourne dans **un conteneur** (page Next.js + serveur MCP Python + navigateur
Camoufox), et **ngrok** donne une URL publique en HTTPS : pas de nom de domaine,
pas de certificat, aucun port à ouvrir sur le VPS.

```
navigateur ──HTTPS──> ngrok ──tunnel──> conteneur ngrok ──> conteneur app :3000
                                                             ├─ page Next.js (mot de passe)
                                                             └─ mcp_server.py ─> Claude + Camoufox ─> ingatlan.com
```

## 1. Le VPS

- **Debian 12 ou Ubuntu 24.04, processeur x86_64** (Intel/AMD), **2 Go de RAM minimum**,
  4 Go conseillés pour 2 recherches en parallèle (chaque recherche = un navigateur ≈ 400 Mo).
  Exemple : Hetzner CX22, OVH VPS, Scaleway…
- 10 Go de disque suffisent (l'image fait environ 1,5 Go).

Connexion et installation de Docker (script officiel) :

```bash
ssh root@IP_DU_VPS
curl -fsSL https://get.docker.com | sh
# Pare-feu : seul SSH doit être ouvert (ngrok sort vers Internet, rien n'entre).
apt-get install -y ufw && ufw allow OpenSSH && ufw --force enable
```

## 2. Le compte ngrok (gratuit)

1. Crée un compte sur https://ngrok.com
2. Récupère ton **authtoken** : https://dashboard.ngrok.com/get-started/your-authtoken
3. Récupère ton **domaine statique gratuit** (une URL fixe, du type
   `https://ton-nom.ngrok-free.app`) : https://dashboard.ngrok.com/domains

## 3. Envoyer le projet sur le VPS

Depuis ton ordinateur, dans le dossier du projet :

```bash
rsync -av --delete \
  --exclude .venv --exclude __pycache__ --exclude web/node_modules --exclude web/.next \
  --exclude .env --exclude 'web/.env*' --exclude shots \
  ./ root@IP_DU_VPS:/opt/ingatlanscrap/
```

(Ou un `git clone` si le projet est sur GitHub/GitLab.)

## 4. Configurer

Sur le VPS :

```bash
cd /opt/ingatlanscrap
cp .env.example .env
openssl rand -base64 24        # → un mot de passe solide pour APP_PASSWORD
nano .env                      # remplis APP_PASSWORD, NGROK_AUTHTOKEN, NGROK_URL
chmod 600 .env
```

## 5. Lancer

```bash
docker compose up -d --build   # 1er build : 5 à 10 minutes (télécharge Firefox/Camoufox)
docker compose ps              # les deux services doivent être "running"
docker compose logs -f ngrok   # doit afficher "started tunnel" avec ton URL
```

Ouvre ton `NGROK_URL` :
1. ngrok gratuit affiche d'abord une page d'avertissement → clique **Visit Site**
   (une fois par navigateur) ;
2. le navigateur demande l'identifiant (`APP_USER`, par défaut `admin`) et le mot de passe ;
3. sur la page, chaque utilisateur saisit **sa propre clé API Anthropic** (obligatoire,
   jamais stockée) : le serveur n'en a pas.

Les conteneurs redémarrent seuls (plantage, reboot du VPS) grâce à `restart: unless-stopped`.

## 6. Vérifier que ingatlan.com accepte le VPS

Les IP de datacenter sont plus souvent bloquées que ton IP perso. Test rapide, sans Claude :

```bash
docker compose exec app /app/.venv/bin/python /app/run_search.py --max-results 3
```

Tu dois obtenir 3 annonces en JSON. Si ça échoue (timeout, page de blocage),
il faudra un VPS chez un autre hébergeur ou un proxy résidentiel.

## Au quotidien

| Action | Commande (sur le VPS, dans `/opt/ingatlanscrap`) |
|---|---|
| Voir les logs | `docker compose logs -f app` |
| Mettre à jour | refaire le `rsync` de l'étape 3, puis `docker compose up -d --build` |
| Redémarrer | `docker compose restart` |
| Arrêter | `docker compose down` |
| Changer le mot de passe | modifier `.env`, puis `docker compose up -d` |
| Libérer de la place | `docker image prune -f` |

## Réglages (`.env`)

| Variable | Rôle |
|---|---|
| `APP_USER` / `APP_PASSWORD` | identifiants de la page (HTTP Basic, protégé par le HTTPS de ngrok) |
| `NGROK_AUTHTOKEN` / `NGROK_URL` | tunnel ngrok et ton domaine statique |
| `MAX_CONCURRENT_SEARCHES` | recherches simultanées (2 par défaut) ; les suivantes attendent leur tour |

## Test local avec Docker (facultatif)

Dans `docker-compose.yml`, décommente `ports: ["127.0.0.1:3000:3000"]`, puis
`docker compose up --build app` et ouvre http://localhost:3000 (avec `APP_PASSWORD` défini).

## En cas de problème

- **Le build échoue sur `camoufox fetch`** : souci réseau vers GitHub ; relance le build.
- **`Browser search failed`** dans la page : regarde `docker compose logs app` (trace complète).
  Manque de mémoire → baisse `MAX_CONCURRENT_SEARCHES` ou prends un VPS plus gros.
- **ngrok `ERR_NGROK_...`** : vérifie `NGROK_AUTHTOKEN` et que `NGROK_URL` est bien ton domaine.
- **Une recherche coupée au bout d'une minute** : normalement non (la réponse est
  diffusée en continu) ; si un proxy est ajouté devant ngrok, il doit accepter le streaming.
