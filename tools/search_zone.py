#!/usr/bin/env python3
"""Writes the search index of one of OffTrack's offline zones, so the app finds a destination without network.

What can be searched: the places (towns, villages, hamlets, localities), the streets of each municipality, the house
numbers along them and every named point worth riding to (hotels, restaurants, huts, shops, peaks, passes, lakes...).
Each place, street or point gets one row of `luogo`, with the municipality it lies in, worked out from the
municipal borders (admin_level=8, or the deepest level the zone has, see Municipalities) of the same day's OpenStreetMap; its words go into the full-text table `testo`.
House numbers are not words to search: they wait in `civico` under their street and are matched once the street
is found. In the French zones the house numbers come from the Base Adresse Nationale too, far more complete than
OpenStreetMap there; a number both sources have is kept once, from the BAN.

The words are normalized as `norm` does (lower case, no accents, only letters and digits): the app must do the same
to what the rider types. Positions are integers, degrees times 1e6.

    search_zone.py build OUT.sqlite AREA.poly IN.osm.pbf MUNICIPALITIES.osm.pbf [--ban adresses-XX.csv.gz ...]
    search_zone.py query DB.sqlite TEXT        prints what the app would find, to check an index by hand
"""
import argparse
import csv
import datetime
import gzip
import re
import sqlite3
import unicodedata
from pathlib import Path

import numpy as np
import osmium
from shapely import STRtree, contains_xy, points, prepare
from shapely.geometry import Polygon
from shapely.ops import unary_union

from zone_area import read_poly, widen

# Bump when the tables or the normalization change: the app reads only the versions it knows.
VERSION = 1

# Places by importance: the weight orders the results when the words match equally well.
PLACES = {
    "city": 100, "town": 90, "village": 80, "suburb": 70, "island": 65, "hamlet": 60, "quarter": 55,
    "neighbourhood": 50, "locality": 45, "isolated_dwelling": 40, "islet": 40, "farm": 35,
}
STREET_WEIGHT = 30
POI_WEIGHT = 20

# Named things worth riding to, by the first key they carry: (key, values or None for any value).
POI_KEYS = [
    ("tourism", None), ("amenity", None), ("shop", None), ("leisure", None), ("historic", None), ("office", None),
    ("craft", None), ("healthcare", None),
    ("natural", {"peak", "volcano", "saddle", "spring", "cave_entrance", "glacier", "water", "bay", "cape", "beach",
                 "valley", "ridge", "arch", "rock", "gorge"}),
    ("mountain_pass", {"yes"}), ("railway", {"station", "halt"}), ("aeroway", {"aerodrome"}),
    ("boundary", {"national_park", "protected_area"}), ("man_made", {"tower", "lighthouse", "dam"}),
]
POI_KEY_NAMES = {k for k, _ in POI_KEYS}

# Natural features and parks can be wide and still be one place to name; anything else wider than this is a
# broken outline or a ferry line (as in poi_zone.py).
MAX_SPAN = 0.2
MAX_SPAN_WIDE = 1.0
WIDE_KEYS = {"natural", "boundary", "leisure"}

# Highways that are not streets to drive to.
NOT_STREETS = {"proposed", "construction", "abandoned", "platform", "bus_stop", "elevator", "corridor", "razed"}

# Towns and villages stand on a node; drawn as areas too, they would come out twice.
NODE_PLACES = {"city", "town", "village", "suburb", "hamlet"}

# Other names a place is known by: Bolzano/Bozen, Aosta/Aoste, Nice/Nizza.
OTHER_NAMES = ["alt_name", "name:it", "name:fr", "name:de", "official_name", "old_name", "short_name", "loc_name"]

LETTERS = str.maketrans({"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th"})

# BAN writes 99999 for the named places that have no number.
BAN_NO_NUMBER = "99999"


def norm(text):
    """The words of [text] as the index keeps them: lower case, no accents, only letters and digits, one space
    between words. "Sant'Anna di Valdieri" -> "sant anna di valdieri"."""
    s = unicodedata.normalize("NFKD", text.lower().translate(LETTERS))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", s).strip()


def norm_number(number):
    """A house number as it is compared: "12/A", "12 a" and "12A" are the same door."""
    return norm(number).replace(" ", "")


def e6(x):
    return int(round(x * 1e6))


def names_of(tags):
    """The main name of an element and the other names it is known by, without repeats."""
    name = tags.get("name", "").strip()
    others = []
    for k in OTHER_NAMES:
        for v in tags.get(k, "").split(";"):
            v = v.strip()
            if v and v != name and v not in others:
                others.append(v)
    return name, others


def poi_kind(tags):
    """The kind of a named point, as "key=value"; None when it is nothing to ride to."""
    for k, values in POI_KEYS:
        v = tags.get(k)
        if v and (values is None or v in values) and v != "no":
            return f"{k}={v}"
    return None


def box_of(locations):
    pts = [(l.lat, l.lon) for l in locations if l.valid()]
    if not pts:
        return None
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    return min(lats), min(lons), max(lats), max(lons)


def fits(box, kind):
    if box is None:
        return False
    span = MAX_SPAN_WIDE if kind.split("=")[0] in WIDE_KEYS else MAX_SPAN
    return box[2] - box[0] <= span and box[3] - box[1] <= span


class Municipalities(osmium.SimpleHandler):
    """The municipal borders of the zone, as (name, polygon). Municipalities are admin_level=8 in Europe; a country
    without them, as Oman with its wilayat at 6, gets the deepest level that covers it: [found] has one level only,
    so a town is never named after a province where a municipality is missing."""

    LEVELS = ("8", "7", "6")
    # Fewer borders than this at a level are a stray few, not the country's municipalities.
    ENOUGH = 10

    def __init__(self):
        super().__init__()
        self.by_level = {level: [] for level in self.LEVELS}

    @property
    def level(self):
        full = [lv for lv in self.LEVELS if len(self.by_level[lv]) >= self.ENOUGH]
        some = [lv for lv in self.LEVELS if self.by_level[lv]]
        return (full or some or self.LEVELS)[0]

    @property
    def found(self):
        return self.by_level[self.level]

    def area(self, a):
        level = a.tags.get("admin_level")
        if a.tags.get("boundary") != "administrative" or level not in self.by_level:
            return
        name = a.tags.get("name", "").strip()
        if not name:
            return
        parts = []
        for outer in a.outer_rings():
            shell = [(n.lon, n.lat) for n in outer if n.location.valid()]
            holes = [[(n.lon, n.lat) for n in inner if n.location.valid()] for inner in a.inner_rings(outer)]
            if len(shell) >= 4:
                parts.append(Polygon(shell, [h for h in holes if len(h) >= 4]))
        if parts:
            geom = unary_union(parts)
            self.by_level[level].append((name, geom if geom.is_valid else geom.buffer(0)))


class Things(osmium.SimpleHandler):
    """Collects places, street pieces, named points and house numbers of one extract."""

    def __init__(self):
        super().__init__()
        self.places = []    # (name, others, kind, lat, lon, weight, osm id)
        self.streets = []   # (name, others, lat, lon, nodes)
        self.pois = []      # (name, others, kind, lat, lon, osm id)
        self.numbers = []   # (street, number, lat, lon, from a place name rather than a street)

    def tags_of(self, o):
        return {t.k: t.v for t in o.tags}

    def address(self, tags, lat, lon):
        number = tags.get("addr:housenumber", "").strip()
        if not number:
            return
        street = tags.get("addr:street", "").strip()
        place = tags.get("addr:place", "").strip()
        if street or place:
            # "12;14" is two doors at one point.
            for n in number.split(";"):
                if n.strip():
                    self.numbers.append((street or place, n.strip(), lat, lon, not street))

    def node(self, n):
        if not n.location.valid():
            return
        tags = self.tags_of(n)
        lat, lon = n.location.lat, n.location.lon
        self.address(tags, lat, lon)
        name, others = names_of(tags)
        if not name:
            return
        place = tags.get("place")
        if place in PLACES:
            self.places.append((name, others, f"place={place}", lat, lon, PLACES[place], f"n{n.id}"))
            return
        kind = poi_kind(tags)
        if kind:
            self.pois.append((name, others, kind, lat, lon, f"n{n.id}"))

    def way(self, w):
        tags = self.tags_of(w)
        if not tags:
            return
        name, others = names_of(tags)
        highway = tags.get("highway")
        if name and highway and highway not in NOT_STREETS:
            locs = [r.location for r in w.nodes if r.location.valid()]
            if locs:
                mid = locs[len(locs) // 2]
                self.streets.append((name, others, mid.lat, mid.lon, len(locs)))
            return
        if "addr:housenumber" not in tags and not name:
            return
        box = box_of(r.location for r in w.nodes)
        if box is None:
            return
        lat, lon = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if box[2] - box[0] <= MAX_SPAN and box[3] - box[1] <= MAX_SPAN:
            self.address(tags, lat, lon)
        if not name:
            return
        place = tags.get("place")
        if place in PLACES and place not in NODE_PLACES and fits(box, "place"):
            self.places.append((name, others, f"place={place}", lat, lon, PLACES[place], f"w{w.id}"))
            return
        kind = poi_kind(tags)
        if kind and fits(box, kind):
            self.pois.append((name, others, kind, lat, lon, f"w{w.id}"))

    def area(self, a):
        # Closed ways come through way(); here only multipolygon relations.
        if a.from_way():
            return
        tags = self.tags_of(a)
        name, others = names_of(tags)
        if not name and "addr:housenumber" not in tags:
            return
        box = box_of(p.location for ring in a.outer_rings() for p in ring)
        if box is None:
            return
        lat, lon = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if box[2] - box[0] <= MAX_SPAN and box[3] - box[1] <= MAX_SPAN:
            self.address(tags, lat, lon)
        if not name:
            return
        place = tags.get("place")
        if place in PLACES and place not in NODE_PLACES and fits(box, "place"):
            self.places.append((name, others, f"place={place}", lat, lon, PLACES[place], f"r{a.orig_id()}"))
            return
        kind = poi_kind(tags)
        if kind and fits(box, kind):
            self.pois.append((name, others, kind, lat, lon, f"r{a.orig_id()}"))


def read_ban(paths):
    """The house numbers of the BAN files: (street, number, lat, lon, municipality)."""
    out = []
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                numero = (row.get("numero") or "").strip()
                street = (row.get("nom_voie") or "").strip()
                if not numero or numero == BAN_NO_NUMBER or not street:
                    continue
                try:
                    lat, lon = float(row["lat"]), float(row["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                number = numero + (row.get("rep") or "").strip()
                out.append((street, number, lat, lon, (row.get("nom_commune") or "").strip()))
    return out


class Municipality:
    """Tells which municipality a point lies in."""

    def __init__(self, found):
        self.names = [n for n, _ in found]
        self.tree = STRtree([g for _, g in found]) if found else None

    def of(self, lats, lons):
        """The municipality of each point, "" where none holds it."""
        out = [""] * len(lats)
        if self.tree is None or not len(lats):
            return out
        pts = points(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
        which, geom = self.tree.query(pts, predicate="within")
        for i, g in zip(which.tolist(), geom.tolist()):
            if not out[i]:
                out[i] = self.names[g]
        return out


def keep_inside(rows, area, lat_at, lon_at):
    """The rows whose point lies in [area]."""
    if not rows:
        return rows
    keep = contains_xy(area, np.array([r[lon_at] for r in rows]), np.array([r[lat_at] for r in rows]))
    return [r for r, k in zip(rows, keep) if k]


class Index:
    """The rows of the index file, built in memory and written at the end."""

    def __init__(self):
        self.luoghi = []        # (id, tipo, nome, comune, lat, lon, peso, osm)
        self.testo = []         # (id, words)
        self.civici = {}        # (street id, normalized number) -> (street id, number, lat, lon)
        self.tipi = {}
        self.comuni = {"": 0}
        self.streets = {}       # (normalized name, municipality) -> street id

    def tipo(self, kind):
        return self.tipi.setdefault(kind, len(self.tipi) + 1)

    def comune(self, name):
        return self.comuni.setdefault(name, len(self.comuni))

    def add(self, kind, name, others, municipality, lat, lon, weight, osm):
        i = len(self.luoghi) + 1
        self.luoghi.append((i, self.tipo(kind), name, self.comune(municipality), e6(lat), e6(lon), weight, osm))
        words = []
        for w in [name] + others + ([municipality] if municipality and municipality != name else []):
            for t in norm(w).split():
                if t not in words:
                    words.append(t)
        self.testo.append((i, " ".join(words)))
        return i

    def add_streets(self, pieces, municipalities):
        """One street per name and municipality, standing on its longest piece."""
        groups = {}
        for (name, others, lat, lon, nodes), m in zip(pieces, municipalities):
            key = (norm(name), m)
            if not key[0]:
                continue
            g = groups.get(key)
            if g is None:
                groups[key] = [name, list(others), lat, lon, nodes]
            else:
                g[1].extend(o for o in others if o not in g[1])
                if nodes > g[4]:
                    g[0], g[2], g[3], g[4] = name, lat, lon, nodes
        for (key, m), (name, others, lat, lon, _) in sorted(groups.items()):
            self.streets[(key, m)] = self.add("highway", name, others, m, lat, lon, STREET_WEIGHT, None)

    def add_number(self, street, number, lat, lon, municipality, place):
        key = (norm(street), municipality)
        if not key[0] or not norm_number(number):
            return
        sid = self.streets.get(key)
        if sid is None:
            # A street no road carries the name of, or a hamlet whose doors are numbered by its own name.
            sid = self.add("addr:place" if place else "highway", street, [], municipality, lat, lon, STREET_WEIGHT,
                           None)
            self.streets[key] = sid
        self.civici.setdefault((sid, norm_number(number)), (sid, number, e6(lat), e6(lon)))

    def write(self, path, meta):
        path.unlink(missing_ok=True)
        db = sqlite3.connect(path)
        db.executescript("""
            PRAGMA page_size = 4096;
            CREATE TABLE meta(chiave TEXT PRIMARY KEY, valore TEXT);
            CREATE TABLE tipo(id INTEGER PRIMARY KEY, osm TEXT);
            CREATE TABLE comune(id INTEGER PRIMARY KEY, nome TEXT);
            CREATE TABLE luogo(id INTEGER PRIMARY KEY, tipo INTEGER, nome TEXT, comune INTEGER, lat INTEGER,
                               lon INTEGER, peso INTEGER, osm TEXT);
            CREATE TABLE civico(via INTEGER, numero TEXT, lat INTEGER, lon INTEGER, PRIMARY KEY(via, numero))
                WITHOUT ROWID;
            CREATE VIRTUAL TABLE testo USING fts4(content="", parole, prefix="2,3");
        """)
        db.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
        db.executemany("INSERT INTO tipo VALUES (?, ?)", [(i, k) for k, i in self.tipi.items()])
        db.executemany("INSERT INTO comune VALUES (?, ?)", [(i, n) for n, i in self.comuni.items()])
        db.executemany("INSERT INTO luogo VALUES (?, ?, ?, ?, ?, ?, ?, ?)", self.luoghi)
        db.executemany("INSERT OR IGNORE INTO civico VALUES (?, ?, ?, ?)", sorted(self.civici.values()))
        db.executemany("INSERT INTO testo(docid, parole) VALUES (?, ?)", self.testo)
        db.execute("INSERT INTO testo(testo) VALUES ('optimize')")
        db.commit()
        db.execute("VACUUM")
        db.close()


def build(a):
    area = widen(read_poly(a.area))
    prepare(area)

    borders = Municipalities()
    borders.apply_file(str(a.municipalities), locations=True, idx="flex_mem")
    where = Municipality(borders.found)
    print(f"comuni: {len(borders.found)} (admin_level={borders.level})")

    h = Things()
    h.apply_file(str(a.input), locations=True, idx="flex_mem")
    places = keep_inside(h.places, area, 3, 4)
    pois = keep_inside(h.pois, area, 3, 4)
    streets = keep_inside(h.streets, area, 2, 3)
    numbers = keep_inside(h.numbers, area, 2, 3)
    ban = keep_inside(read_ban(a.ban), area, 2, 3) if a.ban else []

    index = Index()
    for (name, others, kind, lat, lon, weight, osm), m in zip(places, where.of([p[3] for p in places],
                                                                            [p[4] for p in places])):
        index.add(kind, name, others, m, lat, lon, weight, osm)
    index.add_streets(streets, where.of([s[2] for s in streets], [s[3] for s in streets]))
    for (name, others, kind, lat, lon, osm), m in zip(pois, where.of([p[3] for p in pois], [p[4] for p in pois])):
        index.add(kind, name, others, m, lat, lon, POI_WEIGHT, osm)
    # The BAN first: where both have a door, its position is the one kept.
    for (street, number, lat, lon, commune), m in zip(ban, where.of([b[2] for b in ban], [b[3] for b in ban])):
        index.add_number(street, number, lat, lon, m or commune, False)
    from_ban = len(index.civici)
    for (street, number, lat, lon, place), m in zip(numbers, where.of([n[2] for n in numbers],
                                                                      [n[3] for n in numbers])):
        index.add_number(street, number, lat, lon, m, place)

    meta = {
        "versione": str(VERSION),
        "zona": a.area.stem,
        "data": datetime.date.today().isoformat(),
        "luoghi": str(len(index.luoghi)),
        "civici": str(len(index.civici)),
        "civici_ban": str(from_ban),
        "fonti": "osm,ban" if a.ban else "osm",
    }
    index.write(a.out, meta)
    print(f"{a.out.name}: {len(places)} località, {len(index.streets)} vie, {len(pois)} punti con nome, "
          f"{len(index.civici)} civici ({from_ban} dalla BAN, {len(numbers)} letti da OpenStreetMap), "
          f"{a.out.stat().st_size / 1e6:.1f} MB")
    with_number = len({c[0] for c in index.civici.values()})
    print(f"  vie con almeno un civico: {with_number} su {len(index.streets)}")
    if a.gzip:
        with open(a.out, "rb") as f, gzip.open(a.gzip, "wb", compresslevel=9) as g:
            while chunk := f.read(1 << 20):
                g.write(chunk)
        print(f"  {a.gzip.name}: {a.gzip.stat().st_size / 1e6:.1f} MB")


def search(db, text, limit=10):
    """What the app finds for [text]: (name, kind, municipality, lat, lon, house number or None) by weight. A token
    of digits after the first word is the house number; every other word must start a word of the place."""
    words = norm(text).split()
    number = None
    for i, w in enumerate(words):
        if i > 0 and re.fullmatch(r"\d+[a-z]*", w):
            number = w
            words = words[:i] + words[i + 1:]
            break
    if not words:
        return []
    match = " ".join(f"{w}*" for w in words)
    rows = db.execute(
        "SELECT l.id, l.nome, t.osm, c.nome, l.lat, l.lon FROM testo JOIN luogo l ON l.id = testo.docid "
        "JOIN tipo t ON t.id = l.tipo JOIN comune c ON c.id = l.comune WHERE testo MATCH ? "
        "ORDER BY l.peso DESC, length(l.nome) LIMIT ?", (match, limit)).fetchall()
    out = []
    for sid, name, kind, m, lat, lon in rows:
        door = None
        if number is not None:
            for numero, la, lo in db.execute("SELECT numero, lat, lon FROM civico WHERE via = ?", (sid,)):
                if norm_number(numero) == number:
                    door, lat, lon = numero, la, lo
                    break
        out.append((name, kind, m, lat / 1e6, lon / 1e6, door))
    return out


def query(a):
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    print(f"«{a.text}»")
    rows = search(db, a.text)
    for name, kind, m, lat, lon, door in rows:
        print(f"  {name}{' ' + door if door else ''}, {m or '-'} ({kind}) {lat:.5f},{lon:.5f}")
    if not rows:
        print("  niente")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out", type=Path)
    b.add_argument("area", type=Path)
    b.add_argument("input", type=Path)
    b.add_argument("municipalities", type=Path)
    b.add_argument("--ban", type=Path, nargs="*", default=[], help="BAN files of the French departments of the zone")
    b.add_argument("--gzip", type=Path, help="also write the file compressed here, as the app downloads it")
    q = sub.add_parser("query")
    q.add_argument("db", type=Path)
    q.add_argument("text")
    a = p.parse_args()
    build(a) if a.cmd == "build" else query(a)


if __name__ == "__main__":
    main()
