"""Lasning av den fardigbyggda SQLite-databasen.

Databasfilen byts atomiskt av nattjobbet, darfor oppnas en ny
anslutning per anvandning i stallet for att hallas oppen.
"""

import sqlite3
from contextlib import contextmanager

from app import config


@contextmanager
def open_db():
    if not config.DB_PATH.exists():
        raise DatabaseMissing()
    db = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


class DatabaseMissing(Exception):
    """Databasen ar inte byggd an - visas som lugnt felmeddelande, inte krasch."""


def get_meta() -> dict:
    with open_db() as db:
        return {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM meta")}
