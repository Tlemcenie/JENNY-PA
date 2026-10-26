# syntax=docker/dockerfile:1
# ── Image frontend Jenny (Next.js 16, sortie standalone) — prête Cloud Run ──
# NEXT_PUBLIC_API_URL et NEXT_PUBLIC_SITE_URL sont inlinés AU BUILD (variables
# publiques Next) : il faut donc les passer en build-arg.
#  - NEXT_PUBLIC_API_URL  : URL de l'API déployée ;
#  - NEXT_PUBLIC_SITE_URL : URL publique du front (metadataBase, og:image,
#    canonical, sitemap). Vide = localhost dans les balises OG.

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_SITE_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080
RUN useradd --create-home --uid 10001 app
# Sortie standalone : serveur node minimal + assets statiques.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
USER app
EXPOSE 8080
# server.js est généré par la sortie standalone ; il écoute sur $PORT.
CMD ["node", "server.js"]
