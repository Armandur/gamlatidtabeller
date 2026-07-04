import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

TRAFIKLAB_STATIC_KEY = os.environ.get("TRAFIKLAB_STATIC_KEY", "")
TRAFIKLAB_RT_KEY = os.environ.get("TRAFIKLAB_RT_KEY", "")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
GTFS_ZIP_PATH = DATA_DIR / "dintur-gtfs.zip"
DB_PATH = DATA_DIR / "gtfs.sqlite"

GTFS_STATIC_URL = "https://opendata.samtrafiken.se/gtfs/dintur/dintur.zip"
GTFS_RT_BASE = "https://opendata.samtrafiken.se/gtfs-rt/dintur"

# Bronze-kvot pa static-nyckeln: 60 anrop/30 dagar. Ladda aldrig ner om
# cachad zip ar farskare an detta (nattlig uppdatering ger ~30 anrop/manad).
STATIC_MAX_AGE_HOURS = 20

# Klockslag (lokal tid) da den nattliga uppdateringen kors.
# Samtrafiken publicerar ny data ca 03:00-07:00; 04:30 ger farsk data
# utan att vanta hela natten. Missad korning tas igen vid nasta tick.
NIGHTLY_REFRESH_HOUR = 4
NIGHTLY_REFRESH_MINUTE = 30

TZ = ZoneInfo("Europe/Stockholm")

# Lokala linjer i Harnosand (stadsbussar 501-503, landsbygd 511,
# kvallslinje 590). Styr vilka hallplatser som importeras och vilka
# linjer som far linjevy och utskriftslappar. Hallplatsvyn visar
# alla avgangar (aven regionala linjer) fran de importerade hallplatserna.
# Default har; kan andras i admin-granssnittet (settings.json vinner).
LOCAL_LINES = {"501", "502", "503", "511", "590"}

# Admin-appen kors som egen ASGI-app pa egen port (exponeras normalt
# inte publikt). ADMIN_PASSWORD tomt = ingen inloggning (lita pa att
# porten ar privat); satt det i drift.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or os.urandom(32).hex()


def get_local_lines() -> set[str]:
    from app import settings_store
    value = settings_store.load().get("local_lines")
    return set(value) if value else set(LOCAL_LINES)


def get_base_url() -> str:
    from app import settings_store
    return (settings_store.load().get("base_url") or BASE_URL).rstrip("/")
