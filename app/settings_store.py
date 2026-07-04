"""Korningsbara installningar som overlever databasombyggen.

Databasen byggs om fran GTFS-zippen varje natt, sa admin-installningar
kan inte bo dar - de ligger i en liten JSON-fil i DATA_DIR i stallet.
Env-variablerna ar defaultvarden; filen innehaller bara avvikelser.
"""

import json
import threading
from pathlib import Path

from app import config

_LOCK = threading.Lock()
_cache: dict | None = None


def _path() -> Path:
    return config.DATA_DIR / "settings.json"


def load() -> dict:
    global _cache
    with _LOCK:
        if _cache is None:
            try:
                _cache = json.loads(_path().read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                _cache = {}
        return dict(_cache)


def save(values: dict) -> None:
    global _cache
    with _LOCK:
        _path().parent.mkdir(parents=True, exist_ok=True)
        tmp = _path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_path())
        _cache = dict(values)
