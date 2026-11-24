#!/bin/sh
# Runs once on first start of the postgres container (as superuser).
# Creates the three roles the app uses. Only a superuser may grant BYPASSRLS.
#   manima          schema owner, used by Alembic migrations only
#   manima_app      API runtime: NOBYPASSRLS, subject to forced RLS (tenant isolation)
#   manima_platform outbox relay / workers / CLI / platform metadata: BYPASSRLS
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
create role manima login password '${MANIMA_OWNER_PASSWORD}';
create role manima_app login password '${MANIMA_APP_PASSWORD}' nosuperuser nobypassrls;
create role manima_platform login password '${MANIMA_PLATFORM_PASSWORD}' nosuperuser bypassrls;
create database manima owner manima;
\c manima
create extension if not exists citext;
SQL
