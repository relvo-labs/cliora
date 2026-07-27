# Cliora Console static build (P4-12).
#
# Multi-stage: node builds, nginx serves. The runtime image contains no node, no source
# and no build tooling — a console that ships its own toolchain is extra attack surface
# for zero benefit, since the output is static files.

FROM node:22-bookworm-slim AS build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
# `npm ci` (not install): the lockfile is the input, and a build that quietly resolves
# something else is not the artifact that was reviewed.
RUN npm ci
COPY frontend/ ./
# Baked at build time because Vite substitutes at build time. Overriding the product
# name per deployment therefore means rebuilding, which is stated here rather than
# discovered when the override silently does nothing.
ARG VITE_PRODUCT_NAME=Cliora
ARG VITE_API_BASE_URL=""
ENV VITE_PRODUCT_NAME=$VITE_PRODUCT_NAME \
    VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build


FROM nginx:1.27-alpine AS runtime
COPY --from=build /build/dist /usr/share/nginx/html
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
EXPOSE 80 443
STOPSIGNAL SIGQUIT
