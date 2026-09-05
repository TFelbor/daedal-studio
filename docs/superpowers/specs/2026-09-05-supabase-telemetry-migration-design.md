# Telemetry storage on Supabase (PostgreSQL) — design

**Date:** 2026-09-05 · **Status:** approved by direction ("migrate the DB and all
functionality attached to it to Supabase; contents are expendable, functionality is
not") · **Classification:** architectural

## Why

The telemetry database is the product's moat: every job row, sample, event and human
verdict is training and evaluation data. It lived in one SQLite file,
`~/.ds-mvp/telemetry.db`, bind-mounted into containers — and it corrupted once,
because a host process and a Linux VM sharing a file over VirtioFS is not something
SQLite supports for concurrent writers. Everything built around that file since
(integrity check at startup, rotating snapshots, an off-disk mirror, "WAL deliberately
off", the single-writer relay idea) was compensation for the storage, not product.

A managed PostgreSQL removes the failure class: one network server, real concurrent
writers, real transactions, backups that are somebody else's job. Supabase is the
chosen host (project `lxdtmktcaaypdqeuheoq`).

Existing data is **not** migrated. The product has not launched, the rows are
developer runs, and a fresh schema is cheaper than a data conversion nobody needs.

## What changes

| Layer | Before | After |
|---|---|---|
| Driver | `sqlite3` stdlib | `psycopg` 3 (LGPL-3.0, recorded) + `psycopg_pool` |
| Location | `TELEMETRY_DB_PATH` / `~/.ds-mvp/telemetry.db` | `DS_DATABASE_URL` (a PostgreSQL URL). Unset is a hard configuration error, never a silent default |
| Connections | one connection per `TelemetryDB` instance | one shared pool per process per URL; a `TelemetryDB` borrows a connection per operation; `close()` is a no-op |
| Types | everything TEXT/REAL/INTEGER, JSON as text, datetimes as ISO strings | `TIMESTAMPTZ`, `JSONB`, `DOUBLE PRECISION`, `BIGINT`; malformed JSON is refused at write time |
| Schema management | `CREATE IF NOT EXISTS` + `PRAGMA table_info` additive migration + two SQLite-era migrations | `CREATE IF NOT EXISTS` (full column list) + `information_schema` additive migration under an advisory lock. SQLite-era migrations dropped (nothing to migrate) |
| Foreign keys | `PRAGMA foreign_keys = ON` per connection | declared constraints, always enforced |
| Integrity check + snapshots + mirror | SQLite-specific, at startup and every 6 h | `TelemetryDB.health_check()` (reachability + expected tables), cached and refreshed every `DS_DB_HEALTH_INTERVAL_S` (60 s); `/health` reports the cached verdict. Backups are Supabase's |
| `POST /system/database/backup` | took a snapshot | removed (nothing in the UI called it) |
| Config store | `app_config` in the SQLite file; Fernet key beside it | `app_config` in Postgres (`BYTEA`); key at `DS_CONFIG_KEY_PATH`, default `~/.ds-mvp/.config_key` |
| Trace tool | `sqlite3` `mode=ro` | psycopg connection with `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`; `--db` takes a URL |
| Tests | temp SQLite files, `:memory:` | a throwaway `postgres:17-alpine` container started by `conftest.py` (or `DS_TEST_DATABASE_URL`, which CI provides via a service container); one schema per test via `options=-csearch_path=…` in the URL |
| Row-level security | n/a | enabled on every table, no policies: Supabase's PostgREST roles see nothing; the server connects as the table owner |

## Public surface kept

`TelemetryDB()` with no argument, every `insert_*` / `update_*` / `get_*` /
`record_job_event` / `feedback_funnel` / claim method, the same semantics for
first-write-wins, machine-never-overwrites-human, compare-and-swap claims and
None-skipping updates. `PrintJob`, `TelemetrySample`, `FailureEvent`, `JobEvent`
unchanged. `CollectorClaim` unchanged except that "missing table" is recognised in
PostgreSQL's wording too.

New on `TelemetryDB`: `query`, `query_one`, `execute` (raw SQL for the server's list
endpoint and for tests, so nothing outside `db.py` holds a connection), `table_columns`,
`health_check`, `describe` (redacted URL). Module level: `get_database_url`,
`DatabaseConfigError`, `connection()` (shared pool), `close_pools()`,
`schema_statements()` / `render_schema_sql()`, and `IntegrityError` /
`OperationalError` / `DatabaseError` re-exports.

## Supabase specifics

* Prefer the **session pooler** URL (`…pooler.supabase.com:5432`) or the direct
  connection. The transaction pooler (6543) is tolerated — prepared statements are
  disabled — but `SET TIME ZONE` is per-session, so session semantics are the
  documented path.
* `supabase/migrations/<stamp>_telemetry_schema.sql` is generated from
  `schema_statements()` and a guard test keeps it identical, so the file Supabase
  tooling applies and the DDL the server runs cannot drift.
* The server still creates the schema itself on first connect (idempotent), so a
  fresh project needs only the URL.

## Out of scope

Data migration from the SQLite file; Supabase Auth/Storage/Edge Functions; moving the
Fernet key into Supabase Vault; replacing the WebSocket fan-out with Realtime.

## Verification

`pytest tests/` against the throwaway container; CI with a `postgres` service; the
server started natively against a local Postgres with `DS_DATABASE_URL` set,
`GET /health` reporting `database.healthy`; the licence guards and the migration guard.
