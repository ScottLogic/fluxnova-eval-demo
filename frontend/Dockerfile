# frontend: static React/Vite UI, served by nginx.
#
# Build from the repo root so this stays consistent with the other Dockerfiles'
# convention, even though the frontend has no sibling path dependencies:
#   podman build -f frontend/Dockerfile -t frontend:local .
FROM node:22-slim AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend .
RUN npm run build

FROM docker.io/library/nginx:1.29-alpine

# API_PROXY_PASS/LISTEN_PORT are substituted into the config by nginx's
# docker-entrypoint (envsubst over /etc/nginx/templates/*.template) at container
# start. LISTEN_PORT defaults to 80 for compose (which does the host port mapping);
# local-dev/services/frontend-up.sh overrides it since it runs on --network host.
# API_PROXY_PASS defaults to ui-api on localhost:8090 — both local-dev/compose.yaml
# and services/frontend-up.sh run the ui-api container in the same network namespace
# as this one (the "same pod" the frontend and ui-api are deployed together in).
ENV API_PROXY_PASS=http://localhost:8090
ENV LISTEN_PORT=80
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
