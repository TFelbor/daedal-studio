"""Config store for persistent encrypted configuration."""
import os
import sqlite3
import threading
from typing import Optional, Dict

from cryptography.fernet import Fernet
from pythonsrc.telemetry.db import get_default_db_path

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

import logging
logger = logging.getLogger(__name__)

class ConfigStore:
    """Persistent configuration store backed by SQLite with Fernet encryption."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_default_db_path()
        self._lock = threading.Lock()

        # Store encryption key alongside the telemetry DB so it persists
        # across container restarts when the DB is on a Docker volume.
        db_dir = os.path.dirname(self.db_path)
        self.key_path = os.path.join(db_dir, ".config_key")

        # Migrate key from old repo-root location if present.
        #
        # Only into the DEFAULT database directory. This is a one-way `rename`, so
        # running it against an arbitrary override destroys the only copy of the key
        # that decrypts the real app_config table: a test suite pointing
        # TELEMETRY_DB_PATH at a temp dir would move the key there and take every
        # stored secret with it when the directory was cleaned up. The legacy location
        # only ever corresponded to the default one, so that is the only destination
        # the migration was ever correct for.
        old_key_path = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            ".config_key"
        )
        migrating_into_default = os.path.dirname(get_default_db_path()) == db_dir
        if (
            migrating_into_default
            and not os.path.exists(self.key_path)
            and os.path.exists(old_key_path)
        ):
            os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
            os.rename(old_key_path, self.key_path)
            logger.info("Migrated .config_key from repo root to DB directory")

        # Load or generate Fernet key
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
        
    def _get_conn(self):
        return sqlite3.connect(self.db_path, timeout=10.0)
        
    def init_schema(self):
        """Initialize the app_config table."""
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS app_config (
                        key TEXT PRIMARY KEY,
                        value_encrypted BLOB,
                        updated_at TEXT
                    )
                ''')
                conn.commit()

    def get(self, key: str) -> Optional[str]:
        """Retrieve and decrypt a configuration value."""
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value_encrypted FROM app_config WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row and row[0] is not None:
                    try:
                        decrypted = self.cipher.decrypt(row[0]).decode('utf-8')
                        return decrypted
                    except Exception:
                        return None
        return None

    def set(self, key: str, value: str):
        """Encrypt and store a configuration value."""
        if key not in CONFIG_KEYS:
            raise ValueError(f"Unknown config key: {key}")
            
        encrypted = self.cipher.encrypt(value.encode('utf-8'))
        
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO app_config (key, value_encrypted, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_encrypted=excluded.value_encrypted,
                        updated_at=excluded.updated_at
                ''', (key, encrypted, now))
                conn.commit()

    def get_all(self) -> Dict[str, str]:
        """Retrieve all defined configurations, returning them as a dictionary of key -> plaintext_value."""
        results = {}
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value_encrypted FROM app_config")
                rows = cursor.fetchall()
                
                for row in rows:
                    key = row[0]
                    val_enc = row[1]
                    if val_enc is not None:
                        try:
                            val_dec = self.cipher.decrypt(val_enc).decode('utf-8')
                            results[key] = val_dec
                        except Exception:
                            pass
        return results

    def delete(self, key: str):
        """Delete a configuration value."""
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM app_config WHERE key = ?", (key,))
                conn.commit()
