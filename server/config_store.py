"""Config store for persistent encrypted configuration.

Values live in the `app_config` table of the telemetry database (PostgreSQL on
Supabase), Fernet-encrypted with a key that stays on the host: `DS_CONFIG_KEY_PATH`,
defaulting to `~/.ds-mvp/.config_key`. Keeping the key out of the database means a
dump of the table is ciphertext to anyone without the file, and containers reach the
same key through the `~/.ds-mvp:/root/.ds-mvp` bind mount.
"""
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet

from pythonsrc.telemetry.db import (
    CONFIG_TABLE,
    CONFIG_TABLE_DDL,
    DatabaseError,
    connection,
    get_database_url,
)

logger = logging.getLogger(__name__)

CONFIG_KEYS = {
    "HF_TOKEN": {"label": "HuggingFace Token", "secret": True, "required": True, "description": "Required for FLUX model download"},
    "OCTOPRINT_URL": {"label": "OctoPrint URL", "secret": False, "required": False, "description": "e.g. http://192.168.1.100:5001"},
    "OCTOPRINT_API_KEY": {"label": "OctoPrint API Key", "secret": True, "required": False, "description": "From OctoPrint Settings > API"},
    "MOONRAKER_URL": {"label": "Moonraker URL", "secret": False, "required": False, "description": "e.g. http://192.168.1.100:7125"},
    "MOONRAKER_API_KEY": {"label": "Moonraker API Key", "secret": True, "required": False, "description": "Optional"},
    "DEFAULT_PRINTER_FIRMWARE": {"label": "Default Printer Firmware", "secret": False, "required": False, "description": "klipper | octoprint | bambu"},
    "DEFAULT_PROFILE": {"label": "Default Slicer Profile", "secret": False, "required": False, "description": "Path to profile JSON"},
    "SKIP_VISUALIZER": {"label": "Skip Visualizer (dev mode)", "secret": False, "required": False, "description": "true | false"},
    "SKIP_SCULPTOR": {"label": "Skip Sculptor (dev mode)", "secret": False, "required": False, "description": "true | false"},
    "EXECUTION_STRATEGY_OVERRIDE": {
        "label": "Execution Strategy Override",
        "secret": False,
        "required": False,
        "description": "Override auto-detected strategy: mps_native | nvidia_docker | cpu_docker. Leave empty for auto-detection."
    },
    "BAMBU_IP": {"label": "Bambu Lab IP Address", "secret": False, "required": False, "description": "e.g. 192.168.1.150"},
    "BAMBU_CODE": {"label": "Bambu Lab LAN Access Code", "secret": True, "required": False, "description": "From printer Settings > Network > LAN Mode"},
    "LOG_LEVEL": {"label": "Log Level", "secret": False, "required": False, "description": "INFO | DEBUG"},
    "PYTHONPATH": {"label": "Python Path", "secret": False, "required": False, "description": "Optional override"}
}

#: Where the Fernet key lives when nothing overrides it.
CONFIG_KEY_PATH_ENV = "DS_CONFIG_KEY_PATH"

#: After a read fails, how long reads answer "not configured" without touching the
#: database. Config reads sit on `/health`, the strategy resolver and the printer probe,
#: all of them polled; during an outage each would otherwise wait the full pool timeout,
#: and the endpoints meant to report the outage would be the ones hanging.
READ_BREAKER_S = 30.0


def default_config_key_path() -> str:
    """`$DS_CONFIG_KEY_PATH`, else `~/.ds-mvp/.config_key`."""
    return os.environ.get(CONFIG_KEY_PATH_ENV) or str(Path.home() / ".ds-mvp" / ".config_key")


class ConfigStore:
    """Persistent configuration store backed by PostgreSQL with Fernet encryption."""

    def __init__(self, dsn: Optional[str] = None, key_path: Optional[str] = None):
        """Bind to a database and load or create the encryption key.

        Args:
            dsn: PostgreSQL URL. When omitted, `$DS_DATABASE_URL` is read *at each
                call* rather than here, so the module-level store the server builds
                at import follows the environment.
            key_path: Path of the Fernet key file. Defaults to `default_config_key_path()`.
        """
        self._dsn = dsn
        self.key_path = key_path or default_config_key_path()
        self._retry_reads_at = 0.0
        self._reads_failing = False

        # Migrate the key from its old repo-root location, but only into the DEFAULT
        # key path. This is a one-way `rename`, so running it against an arbitrary
        # override would move the only copy of the key that decrypts the real
        # app_config table into a directory a test suite is about to delete.
        old_key_path = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            ".config_key"
        )
        home_default = str(Path.home() / ".ds-mvp" / ".config_key")
        if (
            self.key_path == home_default
            and not os.path.exists(self.key_path)
            and os.path.exists(old_key_path)
        ):
            os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
            os.rename(old_key_path, self.key_path)
            logger.info("Migrated .config_key from repo root to %s", self.key_path)

        self._key = None
        if not os.path.exists(self.key_path):
            self._key = Fernet.generate_key()
            os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
            with open(self.key_path, "wb") as f:
                f.write(self._key)
        else:
            with open(self.key_path, "rb") as f:
                self._key = f.read().strip()

        try:
            self.cipher = Fernet(self._key)
        except (ValueError, TypeError):
            logger.warning("Fernet key file corrupted, regenerating...")
            self._key = Fernet.generate_key()
            with open(self.key_path, "wb") as f:
                f.write(self._key)
            self.cipher = Fernet(self._key)

    @property
    def dsn(self) -> str:
        """The database URL in force for the next call."""
        return self._dsn if self._dsn is not None else get_database_url()

    def init_schema(self):
        """Create the app_config table if it does not exist (idempotent)."""
        with connection(self.dsn) as conn:
            conn.execute(CONFIG_TABLE_DDL)
            conn.execute(f"ALTER TABLE {CONFIG_TABLE} ENABLE ROW LEVEL SECURITY")

    def _read(self, sql: str, params: tuple = ()) -> list:
        """Run a read, answering "nothing stored" while the database is unreachable.

        A configuration value that cannot be read is treated as not configured — the
        safe default for every key here — and the failure is logged once until a read
        succeeds again. Writes are not softened: `set` and `delete` raise, so a person
        saving a setting learns it did not land.
        """
        now = time.monotonic()
        if now < self._retry_reads_at:
            return []
        try:
            with connection(self.dsn) as conn:
                rows = conn.execute(sql, params).fetchall()
        except DatabaseError as exc:
            self._retry_reads_at = now + READ_BREAKER_S
            if not self._reads_failing:
                logger.error(
                    "Config store unreadable — every setting reads as unset for the next "
                    "%.0fs: %s", READ_BREAKER_S, exc,
                )
                self._reads_failing = True
            return []
        if self._reads_failing:
            logger.info("Config store readable again")
            self._reads_failing = False
        return rows

    def get(self, key: str) -> Optional[str]:
        """Retrieve and decrypt a configuration value."""
        rows = self._read(
            f"SELECT value_encrypted FROM {CONFIG_TABLE} WHERE key = %s", (key,)
        )
        row = rows[0] if rows else None
        if row and row["value_encrypted"] is not None:
            try:
                return self.cipher.decrypt(bytes(row["value_encrypted"])).decode("utf-8")
            except Exception:
                return None
        return None

    def set(self, key: str, value: str):
        """Encrypt and store a configuration value."""
        if key not in CONFIG_KEYS:
            raise ValueError(f"Unknown config key: {key}")

        encrypted = self.cipher.encrypt(value.encode("utf-8"))
        now = datetime.now(timezone.utc)
        with connection(self.dsn) as conn:
            conn.execute(
                f"INSERT INTO {CONFIG_TABLE} (key, value_encrypted, updated_at) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (key) DO UPDATE SET "
                "    value_encrypted = EXCLUDED.value_encrypted, "
                "    updated_at = EXCLUDED.updated_at",
                (key, encrypted, now),
            )

    def get_all(self) -> Dict[str, str]:
        """Every stored configuration as key -> plaintext value."""
        results = {}
        rows = self._read(f"SELECT key, value_encrypted FROM {CONFIG_TABLE}")
        for row in rows:
            val_enc = row["value_encrypted"]
            if val_enc is not None:
                try:
                    results[row["key"]] = self.cipher.decrypt(bytes(val_enc)).decode("utf-8")
                except Exception:
                    pass
        return results

    def delete(self, key: str):
        """Delete a configuration value."""
        with connection(self.dsn) as conn:
            conn.execute(f"DELETE FROM {CONFIG_TABLE} WHERE key = %s", (key,))
