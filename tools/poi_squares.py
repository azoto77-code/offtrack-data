#!/usr/bin/env python3
"""Writes the points of interest of OffTrack's offline zones, one file per square of 1x1 degree.

The kinds are those of PoiCatalog.kt in the app, matched the same way Overpass.kt reads an Overpass answer: the
first kind whose tags are all on the element wins, ways and relations stand at the centre of their box, and only
the tags the app keeps for the card are written. Gates count only where they close a dirt track, and speed cameras
are left out of the countries where showing them is forbidden (the extracts given with --no-cameras).

Each square is written as N44E008-poi.json.gz: {"name", "date", "count", "pois": [[id, kind, lat, lon, name, tags]]},
with the same columns as the app's poi table, so the phone loads it as it is.

    poi_squares.py OUT_DIR IN.osm.pbf [IN.osm.pbf ...] [--no-cameras IN.osm.pbf ...]
"""
import argparse
import datetime
import gzip
import json
import math
from pathlib import Path

import osmium

# PoiCatalog.kt, in its order: key, tags that must all be there (None = any value), special rule.
KINDS = [
    ("drinking_water", [("amenity", "drinking_water")], None),
    ("water_point", [("amenity", "water_point")], None),
    ("water_tap", [("man_made", "water_tap"), ("drinking_water", "yes")], None),
    ("spring", [("natural", "spring")], None),
    ("fuel", [("amenity", "fuel")], None),
    ("restaurant", [("amenity", "restaurant")], None),
    ("fast_food", [("amenity", "fast_food")], None),
    ("cafe", [("amenity", "cafe")], None),
    ("supermarket", [("shop", "supermarket")], None),
    ("convenience", [("shop", "convenience")], None),
    ("hotel", [("tourism", "hotel")], None),
    ("guest_house", [("tourism", "guest_house")], None),
    ("hostel", [("tourism", "hostel")], None),
    ("motel", [("tourism", "motel")], None),
    ("alpine_hut", [("tourism", "alpine_hut")], None),
    ("wilderness_hut", [("tourism", "wilderness_hut")], None),
    ("camp_site", [("tourism", "camp_site")], None),
    ("caravan_site", [("tourism", "caravan_site")], None),
    ("sanitary_dump_station", [("amenity", "sanitary_dump_station")], None),
    ("toilets", [("amenity", "toilets")], None),
    ("motorcycle_repair", [("shop", "motorcycle_repair")], None),
    ("motorcycle", [("shop", "motorcycle")], None),
    ("tyres", [("shop", "tyres")], None),
    ("motorcycle_parking", [("amenity", "motorcycle_parking")], None),
    ("hospital", [("amenity", "hospital")], None),
    ("clinic", [("amenity", "clinic")], None),
    ("doctors", [("amenity", "doctors")], None),
    ("pharmacy", [("amenity", "pharmacy")], None),
    ("defibrillator", [("emergency", "defibrillator")], None),
    ("viewpoint", [("tourism", "viewpoint")], None),
    ("mountain_pass", [("mountain_pass", "yes")], None),
    ("atm", [("amenity", "atm")], None),
    ("shelter", [("amenity", "shelter")], None),
    ("ferry_terminal", [("amenity", "ferry_terminal")], None),
    ("ford", [("ford", "yes")], None),
    ("gate", [("barrier", "gate")], "track_gate"),
    ("speed_camera", [("highway", "speed_camera")], "speed_camera"),
]

# Overpass.kt KEPT: the tags the card shows; everything else stays out.
KEPT = [
    "name", "opening_hours", "phone", "contact:phone", "website", "contact:website", "url", "email", "contact:email",
    "drinking_water", "seasonal", "ele", "emergency", "fee", "operator", "brand", "cuisine", "stars",
    "addr:street", "addr:housenumber", "addr:city", "addr:postcode", "capacity", "description", "access",
    "maxspeed", "fuel:diesel", "fuel:octane_95", "fuel:lpg", "self_service", "automated", "covered", "check_date",
]

# Keys worth looking at: an element with none of them cannot be a point of interest.
KEYS = {k for _, tags, _ in KINDS for k, _ in tags}


def kind_of(tags):
    """The first kind whose tags are all there, as Overpass.kt does; None when none matches."""
    for key, need, special in KINDS:
        if all(k in tags and (v is None or tags[k] == v) for k, v in need):
            return key, special
    return None


def square_name(lat, lon):
    """The square a point lies in, named by its south-west corner as the Valhalla packs are: N44E008."""
    s, w = math.floor(lat), math.floor(lon)
    return f"{'N' if s >= 0 else 'S'}{abs(s):02d}{'E' if w >= 0 else 'W'}{abs(w):03d}"


def entry(prefix, osm_id, key, lat, lon, tags):
    kept = {k: tags[k] for k in KEPT if tags.get(k, "").strip()}
    name = tags.get("name", "").strip() or None
    return [f"{prefix}{osm_id}", key, round(lat, 7), round(lon, 7), name, kept]


class Points(osmium.SimpleHandler):
    """Collects the points of one extract; gates wait until the tracks have been read."""

    def __init__(self, cameras):
        super().__init__()
        self.cameras = cameras
        self.found = {}
        self.gates = {}
        self.track_nodes = set()

    def node(self, n):
        tags = {t.k: t.v for t in n.tags}
        if not KEYS.intersection(tags):
            return
        k = kind_of(tags)
        if k is None or not n.location.valid():
            return
        key, special = k
        if special == "speed_camera" and not self.cameras:
            return
        e = entry("n", n.id, key, n.location.lat, n.location.lon, tags)
        if special == "track_gate":
            self.gates[n.id] = e
        else:
            self.found[e[0]] = e

    def way(self, w):
        if w.tags.get("highway") == "track":
            # Only the gates already seen matter: the node ids of every track would take too much memory.
            for r in w.nodes:
                if r.ref in self.gates:
                    self.track_nodes.add(r.ref)
        tags = {t.k: t.v for t in w.tags}
        if not KEYS.intersection(tags):
            return
        k = kind_of(tags)
        if k is None or k[1] is not None:
            return
        box = self.box((r.location for r in w.nodes))
        if box:
            self.found[f"w{w.id}"] = entry("w", w.id, k[0], (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, tags)

    def area(self, a):
        # Closed ways come through way(); here only multipolygon relations.
        if a.from_way():
            return
        tags = {t.k: t.v for t in a.tags}
        if not KEYS.intersection(tags):
            return
        k = kind_of(tags)
        if k is None or k[1] is not None:
            return
        box = self.box((p.location for ring in a.outer_rings() for p in ring))
        if box:
            oid = a.orig_id()
            self.found[f"r{oid}"] = entry("r", oid, k[0], (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, tags)

    @staticmethod
    def box(locations):
        """South, west, north, east of the valid locations; None when there is none."""
        pts = [(l.lat, l.lon) for l in locations if l.valid()]
        if not pts:
            return None
        lats, lons = [p[0] for p in pts], [p[1] for p in pts]
        return min(lats), min(lons), max(lats), max(lons)

    def points(self):
        out = dict(self.found)
        for nid, e in self.gates.items():
            if nid in self.track_nodes:
                out[e[0]] = e
        return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("--no-cameras", nargs="*", type=Path, default=[], help="extracts where speed cameras are left out")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    banned = {x.resolve() for x in a.no_cameras}

    squares = {}
    for path in a.inputs:
        h = Points(cameras=path.resolve() not in banned)
        h.apply_file(str(path), locations=True, idx="flex_mem")
        points = h.points()
        print(f"{path.name}: {len(points)} punti")
        # A point in two extracts along a border is kept once.
        for e in points.values():
            squares.setdefault(square_name(e[2], e[3]), {})[e[0]] = e

    day = datetime.date.today().isoformat()
    for name, pois in sorted(squares.items()):
        rows = sorted(pois.values(), key=lambda e: e[0])
        doc = {"name": name, "date": day, "count": len(rows), "pois": rows}
        with gzip.open(a.out / f"{name}-poi.json.gz", "wt", encoding="utf-8", compresslevel=9) as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        print(f"{name}: {len(rows)} punti")


if __name__ == "__main__":
    main()
