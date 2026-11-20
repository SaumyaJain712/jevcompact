"""Fernet encryption for API keys at rest.

The Fernet key comes from, in order:
1. JEVCOMPACT_SECRET_KEY (env),
2. the OS keyring (service "jevcompact"), created there on first use,
3. if no keyring backend works (e.g. a headless Linux server), a key file
   <data dir>/secret.key with owner-only permissions. A warning is logged
   (never the key itself).
Set JEVCOMPACT_KEYRING=0 to skip the keyring.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)
SERVICE, USERNAME = "jevcompact", "fernet-key"


def _from_keyring() -> str | None:
    if os.environ.get("JEVCOMPACT_KEYRING", "1") == "0":
        return None
    try:
        import keyring

        key = keyring.get_password(SERVICE, USERNAME)
        if not key:
            key = Fernet.generate_key().decode()
            keyring.set_password(SERVICE, USERNAME, key)
        return key
    except Exception as exc:  # no backend, locked, etc.
        log.warning("OS keyring unavailable (%s); using a local key file instead", type(exc).__name__)
        return None


def _from_file(data_dir: Path) -> str:
    path = data_dir / "secret.key"
    if path.exists():
        return path.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode()
    path.write_text(key)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows ACLs
        pass
    return key


def load_fernet(data_dir: Path) -> Fernet:
    key = os.environ.get("JEVCOMPACT_SECRET_KEY") or _from_keyring() or _from_file(data_dir)
    return Fernet(key.encode())


class SecretBox:
    def __init__(self, fernet: Fernet):
        self._f = fernet

    def encrypt(self, value: str) -> str:
        return self._f.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken:
            log.warning("A stored API key could not be decrypted (the encryption key changed?)")
            return None


def mask(value: str | None) -> str | None:
    if not value:
        return None
    return "•" * 8 + (value[-4:] if len(value) > 8 else "")
