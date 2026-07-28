# Cliora Console for Railway (RW-05, ADR 0020).
#
# Same shape as deploy/frontend.Dockerfile — node builds, nginx serves, and the runtime
# image contains no node, no source and no build tooling — with three changes, all because
# TLS is terminated by the platform rather than here:
#
#   * the config ships as a *template* and is rendered at container start, because it has
#     to interpolate ${PORT}, the private-network address of Central, and the resolver
#     addresses lifted from /etc/resolv.conf;
#   * no certificate is mounted and no port 443 is served;
#   * this image is also the reverse proxy for /api and /ws, so that the console and the
#     API share one origin. That is not a preference: the terminal WebSocket URL is built
#     from `location.host` (frontend/src/composables/useTerminalSession.ts) and ignores
#     VITE_API_BASE_URL, so a second origin breaks terminals while leaving the rest of the
#     app working.

FROM node:22-bookworm-slim AS build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
# `npm ci` (not install): the lockfile is the input, and a build that quietly resolves
# something else is not the artifact that was reviewed.
RUN npm ci
COPY frontend/ ./
ARG VITE_PRODUCT_NAME=Cliora
# Deliberately empty and deliberately not settable to anything else here. A non-empty base
# URL sends API calls to another origin while the terminal socket stays on this one, which
# is the hardest failure in this deployment to diagnose: login, node list and file tree all
# work, and only terminals fail.
ARG VITE_API_BASE_URL=""
ENV VITE_PRODUCT_NAME=$VITE_PRODUCT_NAME \
    VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build


FROM nginx:1.27-alpine AS runtime
COPY --from=build /build/dist /usr/share/nginx/html
# Rendered into /etc/nginx/nginx.conf at start by the image's own
# 20-envsubst-on-templates.sh. NGINX_ENVSUBST_OUTPUT_DIR redirects its output there;
# without it the rendered file lands in conf.d, where a full `http {}` config is invalid.
COPY deploy/railway/nginx.conf.template /etc/nginx/templates/nginx.conf.template
# NGINX_ENTRYPOINT_LOCAL_RESOLVERS turns on the image's own 15-local-resolvers.envsh, which
# reads /etc/resolv.conf and exports NGINX_LOCAL_RESOLVERS (IPv6 addresses bracketed) for
# the envsubst step. nginx needs to be told its resolvers explicitly; the config depends on
# one because the backend address is looked up per request. Using the image's script rather
# than our own keeps one less thing to maintain — and avoids the trap that a hand-added
# /docker-entrypoint.d/*.envsh is skipped unless it carries the executable bit.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    CLIORA_BACKEND_HOST=central.railway.internal \
    CLIORA_BACKEND_PORT=8080 \
    PORT=8080
# No EXPOSE: the served port is ${PORT} at runtime, and a hard-coded EXPOSE here would
# state something the container may not do.
STOPSIGNAL SIGQUIT
