#!/usr/bin/env bash
# Runs automatically on first startup of the postgres-local container (mounted into
# /docker-entrypoint-initdb.d/ by postgres-up.sh, and sourced by the official postgres
# image's entrypoint — so it has access to any env vars passed into the container via
# `-e`). Creates the two application databases/roles used in place of MLflow's SQLite
# file and Fluxnova's H2 file:
#   - $MLFLOW_POSTGRES_DB   — MLflow tracking server backend store
#   - $FLUXNOVA_POSTGRES_DB — Fluxnova process-engine datasource
#
# Credentials come entirely from env vars (set in .env, passed through by
# postgres-up.sh) — never hardcoded here. Re-run only happens against an empty PGDATA
# volume; if you change these in .env after the volume already exists, remove the
# postgres-local-data volume to re-initialise (see local-dev/README.md).
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
    -v mlflow_db="$MLFLOW_POSTGRES_DB" \
    -v mlflow_user="$MLFLOW_POSTGRES_USER" \
    -v mlflow_password="$MLFLOW_POSTGRES_PASSWORD" \
    -v fluxnova_db="$FLUXNOVA_POSTGRES_DB" \
    -v fluxnova_user="$FLUXNOVA_POSTGRES_USER" \
    -v fluxnova_password="$FLUXNOVA_POSTGRES_PASSWORD" \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
    CREATE DATABASE :"mlflow_db";
    CREATE USER :"mlflow_user" WITH PASSWORD :'mlflow_password';
    GRANT ALL PRIVILEGES ON DATABASE :"mlflow_db" TO :"mlflow_user";

    CREATE DATABASE :"fluxnova_db";
    CREATE USER :"fluxnova_user" WITH PASSWORD :'fluxnova_password';
    GRANT ALL PRIVILEGES ON DATABASE :"fluxnova_db" TO :"fluxnova_user";
EOSQL

psql -v ON_ERROR_STOP=1 -v mlflow_user="$MLFLOW_POSTGRES_USER" --username "$POSTGRES_USER" --dbname "$MLFLOW_POSTGRES_DB" \
    -c 'GRANT ALL ON SCHEMA public TO :"mlflow_user";'
psql -v ON_ERROR_STOP=1 -v fluxnova_user="$FLUXNOVA_POSTGRES_USER" --username "$POSTGRES_USER" --dbname "$FLUXNOVA_POSTGRES_DB" \
    -c 'GRANT ALL ON SCHEMA public TO :"fluxnova_user";'
