# Flat finder: Next.js page + Python MCP server + Camoufox, in one image.
#   docker compose up -d --build        (see DEPLOY.md)

# ---------- 1. build the Next.js app (standalone output) ----------
FROM node:24.22.0-bookworm-slim AS web
WORKDIR /app/web
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build \
 && cp -r .next/static .next/standalone/.next/static

# ---------- 2. runtime: Python + Camoufox + the node binary ----------
FROM python:3.14.7-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Node only runs the prebuilt standalone server: the binary is enough.
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt .
# Python deps, then the system libraries Firefox (Camoufox) needs.
RUN python -m venv /app/.venv \
 && /app/.venv/bin/pip install -r requirements.txt \
 && /app/.venv/bin/python -m playwright install-deps firefox \
 && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user; Camoufox's browser is downloaded into its home.
RUN useradd --create-home --uid 10001 app
USER app
RUN /app/.venv/bin/python -m camoufox fetch

COPY --chown=app:app fillform.py run_search.py mcp_server.py ./
COPY --from=web --chown=app:app /app/web/.next/standalone /app/web

ENV INGATLAN_ROOT=/app \
    INGATLAN_PYTHON=/app/.venv/bin/python \
    PORT=3000 \
    HOSTNAME=0.0.0.0
EXPOSE 3000
WORKDIR /app/web
CMD ["node", "server.js"]
