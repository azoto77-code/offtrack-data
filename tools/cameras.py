#!/usr/bin/env python3
"""Speed cameras from MapAtlas, added to the ones OpenStreetMap has in a zone.

The MapAtlas Camera Index (https://mapatlas.eu/data/camera-index/, CC BY 4.0, "MapAtlas / MapMetrics driver reports")
has one GeoJSON per country, with a point for each fixed camera, red light camera and average speed section. OSM stays
the main source, as MapAtlas is a snapshot of May 2024: a MapAtlas camera within MERGE_M of an OSM one is the same
camera, and only lends it its limit when OSM has none. The others are added with the id "mci-<ref>".

Red light cameras are left out: they do not check the speed, and the app announces the cameras as speed cameras.
Limits above what the country allows are taken as unknown: in Italy 2,326 points say 140 km/h.
"""
import json
import math
from pathlib import Path

# Within this distance a MapAtlas camera and an OSM one are the same.
MERGE_M = 50.0

# The classes of the index that check the speed, with the value written in camera:type.
CLASSES = {"spot": "fixed", "corridor": "average_speed", "adaptive": "variable"}

# The highest limit of each country of the zones, in km/h: a camera's limit above it is not known.
MAX_KMH = {"IT": 130, "FR": 130, "ES": 120, "PT": 120, "AD": 90, "CH": 120, "AT": 130, "SI": 130, "HR": 130, "OM": 120}

SOURCE = "MapAtlas"


def limit_of(props, country):
    """The limit of a camera in km/h as a string, or None when it is missing or more than the country allows."""
    v = props.get("limitKph")
    if not isinstance(v, (int, float)) or v < 5:
        return None
    if v > MAX_KMH.get(country, 130):
        return None
    return str(int(v))


def rows_of(features, country):
    """The rows of the cameras of one country's GeoJSON that check the speed, as poi.json.gz has them."""
    out = []
    for f in features:
        g = f.get("geometry") or {}
        p = f.get("properties") or {}
        if g.get("type") != "Point" or p.get("class") not in CLASSES or p.get("reportedInactive"):
            continue
        lon, lat = g["coordinates"][:2]
        tags = {"camera:type": CLASSES[p["class"]], "source": SOURCE}
        limit = limit_of(p, country)
        if limit:
            tags["maxspeed"] = limit
        ref = str(p.get("ref") or f"{country}-{lat:.5f}-{lon:.5f}")
        out.append([f"mci-{ref}", "speed_camera", round(lat, 7), round(lon, 7), None, tags])
    return out


def load(folder):
    """The rows of every <country>.geojson in [folder]; a file that cannot be read is reported and left out."""
    out = []
    for f in sorted(Path(folder).glob("*.geojson")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"  MapAtlas {f.name} non leggibile: {e}")
            continue
        out.extend(rows_of(doc.get("features", []), f.stem.upper()))
    return out


def _cell(lat, lon):
    # About 110 m across: a camera within MERGE_M is in the same square or the next one.
    return int(math.floor(lat / 0.001)), int(math.floor(lon / 0.0014))


def _distance_m(a, b):
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * 110_540, (a[1] - b[1]) * 111_320 * k)


def merge(points, extra):
    """[points] (id -> row) with the cameras of [extra] that OSM does not have; returns (added, limits lent)."""
    grid = {}
    for e in points.values():
        if e[1] == "speed_camera":
            grid.setdefault(_cell(e[2], e[3]), []).append(e)
    added = lent = 0
    for x in extra:
        cy, cx = _cell(x[2], x[3])
        near = [e for dy in (-1, 0, 1) for dx in (-1, 0, 1) for e in grid.get((cy + dy, cx + dx), [])
                if _distance_m((e[2], e[3]), (x[2], x[3])) <= MERGE_M]
        if near:
            same = min(near, key=lambda e: _distance_m((e[2], e[3]), (x[2], x[3])))
            if "maxspeed" not in same[5] and "maxspeed" in x[5] and same[0][0] in "nwr":
                same[5]["maxspeed"] = x[5]["maxspeed"]
                lent += 1
            continue
        points[x[0]] = x
        grid.setdefault((cy, cx), []).append(x)
        added += 1
    return added, lent
