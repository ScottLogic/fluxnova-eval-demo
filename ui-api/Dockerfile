# ui-api: FastAPI backend for the demo UI (frontend/). See ui-api/README.md.
#
# Build from the repo root, same convention as the other Dockerfiles (ui-api has no
# sibling path dependencies today, but this keeps every service consistent):
#   podman build -f ui-api/Dockerfile -t ui-api:local .
FROM python:3.11-slim

WORKDIR /app

COPY ui-api /app/ui-api

RUN pip install --no-cache-dir /app/ui-api

# Bind on all interfaces inside the container — local-dev/services/frontend-up.sh and
# local-dev/compose.yaml both run this alongside frontend-local in a shared network
# namespace (the same "pod" the frontend nginx proxies /api/ into over localhost).
ENV UI_API_HOST=0.0.0.0

ENTRYPOINT ["ui-api"]
