"""Nedladdning av statisk GTFS fran Trafiklab/Samtrafiken.

Static-nyckeln har lag kvot (Bronze: 60 anrop/30 dagar) - all logik har
gar via en lokal zip-cache och laddar bara ner nar cachen ar for gammal.
"""

import logging
import time
from pathlib import Path

import httpx

from app import config

log = logging.getLogger(__name__)


def cache_age_hours(path: Path = config.GTFS_ZIP_PATH) -> float | None:
    """Alder pa cachad zip i timmar, eller None om den saknas."""
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 3600


def fetch_static_zip(force: bool = False) -> bool:
    """Hamta GTFS-zippen till cachen om den behovs.

    Returnerar True om en ny fil laddades ner, False om cachen anvands.
    Kastar vidare natverksfel bara om det inte finns nagon cache alls -
    finns en gammal zip loggas felet och den gamla behalls.
    """
    age = cache_age_hours()
    if not force and age is not None and age < config.STATIC_MAX_AGE_HOURS:
        log.info("GTFS-cache ar %.1f h gammal, laddar inte ner", age)
        return False

    if not config.TRAFIKLAB_STATIC_KEY:
        raise RuntimeError("TRAFIKLAB_STATIC_KEY saknas i miljon")

    url = f"{config.GTFS_STATIC_URL}?key={config.TRAFIKLAB_STATIC_KEY}"
    log.info("Laddar ner GTFS-zip fran Trafiklab (kvotbelagt anrop)")
    try:
        # API:et kraver Accept-Encoding gzip/deflate, annars HTTP 406
        with httpx.Client(timeout=120) as client:
            resp = client.get(url, headers={"Accept-Encoding": "gzip"})
            resp.raise_for_status()
    except httpx.HTTPError:
        if age is None:
            raise
        log.exception("Nedladdning misslyckades, behaller %.1f h gammal cache", age)
        return False

    config.GTFS_ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.GTFS_ZIP_PATH.with_suffix(".zip.tmp")
    tmp.write_bytes(resp.content)
    tmp.replace(config.GTFS_ZIP_PATH)
    log.info("Ny GTFS-zip sparad (%d byte)", len(resp.content))
    return True
