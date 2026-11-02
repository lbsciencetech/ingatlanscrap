# ingatlanscrap — Flat finder

Search for flats on [ingatlan.com](https://ingatlan.com) **in plain language**.
Describe the property you want (in Hungarian, English or French), Claude turns it into
search criteria, a real browser fills in the site's search form, and the matching
listings show up in a web page.

> *"A renovated 3-room flat in the XI. district under 90 million, with a balcony and a lift"*
> → the matching ingatlan.com search, and the list of listings.

## How it works

```
web page (Next.js)  ──MCP stdio──>  mcp_server.py ──> Claude: description → criteria (validated)
                                                  └─> Camoufox: fills in the ingatlan.com form
                                                                and reads the results pages
```

1. **You describe** what you are looking for, in a few words.
2. **Claude builds the search**: it produces the exact fields of ingatlan.com's search
   form. A validator checks every value; if one is wrong, Claude gets the errors and fixes
   it (up to 3 tries).
3. **A browser runs it**: [Camoufox](https://camoufox.com) (a stealth Firefox) opens the
   site, fills in the form field by field and submits it.
4. **Listings come back** to the page, with a link to each ad and to the full search on
   ingatlan.com. Screenshots are available as an option.

ingatlan.com has no public search API: filling in the real form means the results are
exactly what the site shows.

## Anthropic API key (required)

The app calls Claude, so **an Anthropic API key is required**. Create one at
[console.anthropic.com](https://console.anthropic.com/settings/keys).

- **Web page**: each user enters their own key in the key field. It is sent with each
  search only and never stored. Without a key, the search does not start.
- **Command line**: put `ANTHROPIC_API_KEY` in `.env` (or in your environment).

## Local setup

Requirements: recent Python 3 and Node.js (the Docker image uses Python 3.14 and Node.js 24).

```bash
git clone https://github.com/lbsciencetech/ingatlanscrap.git
cd ingatlanscrap

# Python server + browser
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m camoufox fetch      # downloads the Camoufox browser

cp .env.example .env                    # key used by the command-line client
```

### Web page

```bash
cd web
npm ci
npm run dev                             # http://localhost:3000
```

Enter your API key, describe the property, then click **Search**. The *Build search only*
mode only asks Claude for the criteria, without starting the browser.

### Command line

```bash
.venv/bin/python mcp_client.py --max-results 10 "2 rooms in the XI. district, max 90M Ft"
.venv/bin/python mcp_client.py --dry-run "studio in Budapest VIII, under 40M Ft"
.venv/bin/python mcp_client.py --screenshots shots/ "3 rooms with a balcony, XIII"
```

## Project layout

| File | Role |
|---|---|
| `fillform.py` | criteria schema, validation, form filling |
| `run_search.py` | starts Camoufox, submits the search, collects listings and screenshots |
| `mcp_server.py` | MCP server: tool `search_flats(description, dry_run, max_results, screenshots)` |
| `mcp_client.py` | command-line MCP client |
| `web/` | Next.js page (MCP client, streams progress live) |
| `Dockerfile`, `docker-compose.yml` | single image (page + server + browser) and ngrok tunnel |
| `DEPLOY.md` | deploying to a VPS (in French) |

## Deployment

One Docker container and an [ngrok](https://ngrok.com) tunnel are enough: no domain name,
no certificate, no open port. The page is password-protected (HTTP Basic).
Step-by-step guide: **[DEPLOY.md](DEPLOY.md)**.

## Disclaimer

This project automates a third-party website: respect its terms of use and keep the
number of requests low. Each search uses tokens on the API key it runs with.
