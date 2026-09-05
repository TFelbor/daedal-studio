# Supabase

The telemetry database — every job row, sample, event and human verdict — is
PostgreSQL on Supabase (project `lxdtmktcaaypdqeuheoq`). The application reaches it
through one URL, `DS_DATABASE_URL` in `.env`; see `.env.template` for where to copy
it from.

## Schema

`migrations/*_telemetry_schema.sql` is **generated** from `pythonsrc/telemetry/db.py`:

```bash
python -m pythonsrc.telemetry.db --ddl > supabase/migrations/<stamp>_telemetry_schema.sql
```

`tests/test_supabase_migration.py` fails when the newest migration file and the code
disagree, so the file Supabase tooling applies and the DDL the server runs cannot
drift apart. Every statement is idempotent (`CREATE ... IF NOT EXISTS`, `ALTER TABLE
... ENABLE ROW LEVEL SECURITY`), and the server runs the same DDL on startup, so a
fresh project needs nothing but the URL — applying the file is how the project's
migration history stays truthful, not how the tables come to exist.

Apply it with any of:

* the Supabase MCP server's `apply_migration` tool (this repo's `.mcp.json` names it);
* `supabase db push` with the CLI linked to the project;
* the SQL editor in the dashboard.

## Security posture

Row-level security is enabled on every table with **no policies**. Supabase exposes
the `public` schema through PostgREST to its `anon` and `authenticated` roles; with
RLS on and no policy they see nothing. The API server connects as the tables' owner
(the `postgres` role, via the session pooler), which RLS does not restrict. The
`service_role` key bypasses RLS and must never leave the server side — nothing in
this project uses it.

## Connection string

Prefer the **session pooler** (`…pooler.supabase.com:5432`) or the direct connection.
The transaction pooler (6543) is tolerated — prepared statements are disabled — but
`SET TIME ZONE` is per-session, so session semantics are the documented path. Append
`?sslmode=require` to refuse an unencrypted connection.

## Backups

Supabase's. The SQLite-era snapshot rotation and Drive mirror are gone with the file
they protected; point-in-time recovery is a Supabase add-on if the retention window
needs to be longer than the plan's daily backups.
