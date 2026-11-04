#!/usr/bin/env python3
"""The French automatic radars, from the Sécurité routière's own map, radars.securite-routiere.gouv.fr.

Its list (/radars/all?_format=json) gives each radar's id, type and place; the page of one radar
(/radars/<id>?_format=json) its road, direction and the limits it checks ("Vitesse VL 70", VL being cars and
motorcycles). Kept: the fixed radars, the "discriminants" (cars and lorries apart) and the urban ones, as fixed
cameras, and the average speed ones ("tronçons") as cameras of average speed at their start, without the line: the
list gives only the start and the length. Left out: red lights and level crossings, which do not check the speed,
and the "itinéraires", the roads where the radar cars drive, which are no place.

Only the radars of the zone are asked for their page, a few at a time.
"""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://radars.securite-routiere.gouv.fr"
SOURCE = "Sécurité routière"
TYPES = {"fixes": "fixed", "discriminants": "fixed", "urbain": "fixed", "troncons": "average_speed"}
_VL = re.compile(r"Vitesse VL (\d{2,3})")


def rows_of(items):
    """The rows of the list's radars that check the speed, without their limits."""
    out = []
    for i in items:
        kind = TYPES.get(i.get("type"))
        try:
            lat, lon = float(i["lat"]), float(i["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if kind is None or not i.get("id"):
            continue
        out.append([f"fr-{i['id']}", "speed_camera", round(lat, 7), round(lon, 7), None,
                    {"camera:type": kind, "source": SOURCE}])
    return out


def limit_of(page):
    """The limit for cars of one radar's page, as a string; None when it gives none."""
    for r in page.get("rulesmesured") or []:
        m = _VL.search(str(r.get("name", "")))
        if m:
            return m.group(1)
    return None


def fetch(rid, timeout=30):
    req = urllib.request.Request(f"{BASE}/radars/{rid}?_format=json", headers={"User-Agent": "OffTrack-data"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def add_details(rows, get=fetch, workers=6):
    """The limit, road and direction of each row, from its page; a page that does not come is left out. Returns how
    many pages came."""
    def one(row):
        try:
            return row, get(row[0].removeprefix("fr-"))
        except Exception:  # noqa: BLE001 - a radar without its page keeps its place
            return row, None

    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for row, page in pool.map(one, rows):
            if not page:
                continue
            done += 1
            limit = limit_of(page)
            if limit:
                row[5]["maxspeed"] = limit
            road = str(page.get("radarroad") or "").strip()
            if road and road != "-":
                row[5]["ref"] = road
            way = str(page.get("radardirection") or "").strip()
            if way and way != "-":
                row[5]["direction"] = way
            km = str(page.get("radartronconkm") or "").replace(",", ".")
            if row[5]["camera:type"] == "average_speed" and re.fullmatch(r"\d+(\.\d+)?", km):
                row[5]["section:m"] = str(round(float(km) * 1000))
    return done


def load(path):
    """The radar list saved from /radars/all?_format=json."""
    with open(path, encoding="utf-8") as f:
        return rows_of(json.load(f))
