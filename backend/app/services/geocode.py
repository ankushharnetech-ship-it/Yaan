"""Address -> coordinates via OpenStreetMap Nominatim (used for the trip map when a trip has no coordinates).

Best effort: any failure returns None and the stop is simply left off the map. If the full address is not found, the
leading parts (house/plot number, building) are dropped one at a time, since OSM rarely knows them.
"""
import logging
import re
import time

import httpx

log = logging.getLogger(__name__)
_URL = "https://nominatim.openstreetmap.org/search"
WORDS = r"(?<![A-Za-z0-9])(main|road|rd|street|st|marg|lane|nagar|part[- ]?[0-9]+|mr[- ]?[0-9]+)(?![A-Za-z0-9])"
_HEADERS = {"User-Agent": "yaan-transport-platform/1.0"}


def geocode(address: str | None, hint: str | None = None) -> tuple[float, float] | None:
    if not address or not address.strip():
        return None
    parts = [p.strip() for p in address.replace("\n", ",").split(",") if p.strip()]
    try:
        with httpx.Client(timeout=6, headers=_HEADERS) as c:
            tries = [", ".join(parts[i:]) for i in range(min(len(parts), 4))]
            if hint:  # addresses often omit the city: retry the street/area with the office's city appended
                tries += [f"{', '.join(parts[i:])}, {hint}" for i in range(min(len(parts), 4))]
                # last resort: each part on its own, without road words ("Nipania Main road" -> "Nipania"), from the end
                for part in reversed(parts):
                    bare = re.sub(WORDS, " ", part, flags=re.I)
                    bare = " ".join(bare.split())
                    if bare and bare != part:
                        tries.append(f"{bare}, {hint}")
            for n, q in enumerate(tries):
                if n:
                    time.sleep(1.1)  # Nominatim usage policy: at most 1 request per second
                rows = c.get(_URL, params={"q": q, "format": "json", "limit": 1}).json()
                if rows:
                    return float(rows[0]["lat"]), float(rows[0]["lon"])
    except Exception as e:  # network down, rate limited, bad JSON...
        log.warning("geocoding failed: %s", e)
    return None
