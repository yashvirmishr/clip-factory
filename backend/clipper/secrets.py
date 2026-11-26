"""Secret storage for OAuth client credentials and tokens.

The app is local-first, so there is no server-side vault. On the desktop the
OS credential store (Windows Credential Locker, macOS Keychain, Secret
Service) is the only production backend. Tests use an in-memory store; it is
never persisted and cannot be selected by accident because the environment
variable is only read once at startup.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Protocol

logger = logging.getLogger(__name__)

SERVICE = "clipfactory"


class SecretError(RuntimeError):
    """Base class for secret-store failures."""


class SecretStoreUnavailable(SecretError):
    """Raised when no secure backend is usable on this machine."""


class SecretStore(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        ...

    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str) -> None:
        ...

    def delete(self, key: str) -> None:
        ...


class MemorySecretStore:
    """Process-local store for tests. Never writes to disk."""

    name = "memory"

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values: dict[str, str] = dict(initial or {})
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        return True, "in-memory test store"

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)


class KeyringSecretStore:
    """OS credential store backed by the optional ``keyring`` package."""

    name = "keyring"

    def __init__(self) -> None:
        try:
            import keyring  # type: ignore[import-not-found]
            from keyring.errors import KeyringError  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001 - dependency missing or broken
            raise SecretStoreUnavailable(
                "Secure token storage needs the `keyring` package. Install it with "
                "`./.venv/Scripts/python.exe -m pip install keyring` and restart the app."
            ) from exc
        self._keyring = keyring
        self._keyring_error = KeyringError
        try:
            backend = keyring.get_keyring()
            self._backend_name = type(backend).__name__
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreUnavailable(f"Could not open the OS credential store: {exc}") from exc

    def available(self) -> tuple[bool, str]:
        try:
            backend = self._keyring.get_keyring()
        except Exception as exc:  # noqa: BLE001
            return False, f"credential store unavailable: {exc}"
        module = type(backend).__module__
        if module.endswith(".fail") or type(backend).__name__.lower().startswith("fail"):
            return False, "no OS credential backend is available"
        return True, f"{type(backend).__name__} ({module})"

    def _wrap(self, exc: Exception) -> SecretStoreUnavailable:
        return SecretStoreUnavailable(f"OS credential store error: {type(exc).__name__}")

    def get(self, key: str) -> str | None:
        try:
            return self._keyring.get_password(SERVICE, key)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc) from exc

    def set(self, key: str, value: str) -> None:
        try:
            self._keyring.set_password(SERVICE, key, value)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc) from exc

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(SERVICE, key)
        except self._keyring_error:
            return
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc) from exc


_STORE: SecretStore | None = None
_LOCK = threading.Lock()


def _build_store() -> SecretStore:
    requested = os.environ.get("CLIPPER_SECRET_BACKEND", "").strip().lower()
    if requested == "memory":
        return MemorySecretStore()
    if requested and requested != "keyring":
        raise SecretStoreUnavailable(f"Unknown CLIPPER_SECRET_BACKEND={requested!r}")
    return KeyringSecretStore()


def store() -> SecretStore:
    global _STORE
    if _STORE is None:
        with _LOCK:
            if _STORE is None:
                _STORE = _build_store()
    return _STORE


def configure(store_impl: SecretStore) -> None:
    """Replace the process store. Used by tests and the desktop bridge."""
    global _STORE
    with _LOCK:
        _STORE = store_impl


def reset() -> None:
    global _STORE
    with _LOCK:
        _STORE = None


def status() -> dict:
    try:
        active = store()
        ok, detail = active.available()
        return {"backend": active.name, "available": bool(ok), "detail": detail}
    except SecretStoreUnavailable as exc:
        return {"backend": "unavailable", "available": False, "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - diagnostics must never crash the app
        return {"backend": "error", "available": False, "detail": type(exc).__name__}


def get_secret(key: str) -> str | None:
    return store().get(key)


def set_secret(key: str, value: str) -> None:
    store().set(key, value)


def delete_secret(key: str) -> None:
    store().delete(key)


def get_json(key: str) -> dict:
    raw = get_secret(key)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def set_json(key: str, value: dict) -> None:
    set_secret(key, json.dumps(value, separators=(",", ":")))


def redact(value: str | None, keep: int = 4) -> str:
    """Return a log-safe fingerprint, never the secret itself."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "…" + ("*" * min(8, max(1, len(value) - keep)))
