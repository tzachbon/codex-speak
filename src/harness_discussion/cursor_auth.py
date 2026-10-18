"""The Cursor desktop sign-in, read from Cursor's own state database. Never writes it and never refreshes the token."""
import base64
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from .audio import NoAudioError

_STATE = Path("Cursor", "User", "globalStorage", "state.vscdb")
DB = (Path(os.environ.get("APPDATA", "")) if sys.platform == "win32"
      else Path.home() / "Library" / "Application Support") / _STATE


def _expires(token):
    try:
        payload = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return 0  # undecodable counts as expired


def _check():
    try:
        con = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)  # read-only: Cursor may hold it open
        try:
            row = con.execute("SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'").fetchone()
        finally:
            con.close()
    except (sqlite3.Error, ValueError):  # ValueError: a relative path when %APPDATA% is unset
        return "missing", None
    value = row[0] if row else None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    token = value.strip('"') if isinstance(value, str) else ""
    if not token:
        return "signed_out", None
    return ("ready" if _expires(token) > time.time() + 60 else "expired"), token


def status():
    """"ready", "missing" (no Cursor database), "signed_out" or "expired"."""
    return _check()[0]


def token():
    state, tok = _check()
    if state != "ready":
        raise NoAudioError(f"{state}")
    return tok
