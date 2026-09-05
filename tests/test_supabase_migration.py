"""The committed Supabase migration is the schema the code runs — byte for byte.

`supabase/migrations/*_telemetry_schema.sql` is what Supabase tooling applies; the DDL
in `pythonsrc/telemetry/db.py` is what the server runs on startup. Two sources of the
same schema drift the first time either is edited alone, so the file is *generated*
from the code and this test fails when they disagree. Regenerate with
`python -m pythonsrc.telemetry.db --ddl`.
"""

from pathlib import Path

from pythonsrc.telemetry import db as db_module

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "supabase" / "migrations"


def _newest_schema_migration() -> Path:
    files = sorted(MIGRATIONS.glob("*_telemetry_schema.sql"))
    assert files, f"no *_telemetry_schema.sql under {MIGRATIONS}"
    return files[-1]


def test_the_committed_migration_matches_the_code():
    path = _newest_schema_migration()
    assert path.read_text() == db_module.render_schema_sql(), (
        f"{path.relative_to(REPO_ROOT)} is out of date. Regenerate it with "
        "`python -m pythonsrc.telemetry.db --ddl > <that file>`."
    )


def test_every_table_gets_row_level_security():
    """Supabase exposes `public` through PostgREST; RLS with no policy is the lock."""
    statements = db_module.schema_statements(include_config=True)
    locked = {
        s.split()[2] for s in statements if s.startswith("ALTER TABLE") and "ROW LEVEL SECURITY" in s
    }
    created = {
        s.split()[5].split("(")[0] for s in statements if s.startswith("CREATE TABLE")
    }
    assert created == locked == set(db_module.TELEMETRY_TABLES) | {db_module.CONFIG_TABLE}


def test_the_schema_is_idempotent(isolated_db):
    """Applying the migration to a database that already has it changes nothing."""
    before = isolated_db.table_columns("print_job")
    for statement in db_module.schema_statements(include_config=True):
        isolated_db.execute(statement)
    assert isolated_db.table_columns("print_job") == before
    assert isolated_db.health_check() == []


def test_the_cli_prints_the_migration(capsys):
    assert db_module._main(["--ddl"]) == 0
    assert capsys.readouterr().out == db_module.render_schema_sql()
