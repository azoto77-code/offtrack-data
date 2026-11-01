#!/usr/bin/env python3
"""Writes the descriptions the app reads to offer the offline zones.

"zone" writes zona.json in the directory of one zone's files: what the zone is, where its outline runs, and the size
and sha256 of each file, so the app downloads again only the files that changed from the edition it has. "index"
joins the zona.json of every zone into indice.json, the list the app reads first.

    zone_index.py zone OUT_DIR ZONES.json ID AREA.poly --edition 20261104 --tag zona-nord-ovest-20261104
                  --valhalla 3.6.3 --contours 20m-1
    zone_index.py index OUT.json ZONA.json [ZONA.json ...] [--brouter-url URL] [--brouter-have LIST] [--contours 20m-1]
                  [--zones ZONES.json]
                  LIST names the segments the URL really serves, one a line: the others leave the zones' lists;
                  ZONES.json lends every zone its names and legacy as they are now, not as they were when it was built
    zone_index.py terrain OUT.json DIR --contours 20m-1 [--previous OLD.json]
                  the manifest of one row of the shared terrain: the squares in DIR added to those of OLD.json
"""
import argparse
import datetime
import gzip
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from zone_area import outline, read_poly, segments, squares, widen

GEOFABRIK = "https://download.geofabrik.de"
BASE_URL = "https://github.com/azoto77-code/offtrack-data/releases/download"
ATTRIBUTION = ("Dati © OpenStreetMap contributors, licenza ODbL. Quote: Terrain Tiles su AWS (SRTM, EU-DEM prodotto "
               "con dati Copernicus, Mapzen).")
BAN_ATTRIBUTION = " Indirizzi in Francia: Base Adresse Nationale, Licence Ouverte 2.0."


def search_meta(path):
    """The meta table of the compressed search index: counts and sources."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        with gzip.open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                tmp.write(chunk)
        tmp.flush()
        db = sqlite3.connect(tmp.name)
        try:
            return dict(db.execute("SELECT chiave, valore FROM meta"))
        finally:
            db.close()


def describe(path):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": sha.hexdigest()}


def zone(a):
    zones = json.loads(Path(a.zones).read_text())
    info = next(z for z in zones["zones"] if z["id"] == a.id)
    # The Valhalla block the zone's routing tiles come from: zones of one block share one build and one edition.
    block = next(b for b in zones["blocks"] if b["id"] == info["block"])
    area = read_poly(a.area)
    wide = widen(area)
    files = {f.name: describe(f) for f in sorted(Path(a.out).iterdir()) if f.is_file() and f.name != "zona.json"}
    doc = {
        "id": info["id"],
        "name": info["name"],
        # The name in the other languages of the app, and legacy on a zone the app no longer offers (kept for the
        # phones that have it): the list is what the app shows, so both come from the list, not from the build.
        **presentation(info),
        "country": info["country"],
        "edition": a.edition,
        "tag": a.tag,
        "box": [round(x, 4) for x in wide.bounds],
        "outline": outline(area),
        "files": files,
        "bytes": sum(f["bytes"] for f in files.values()),
        "valhalla": a.valhalla,
        "contours": a.contours,
        "brouter": segments(wide),
        "squares": squares(wide),
        "block": block["id"],
        "sources": sorted({f"{GEOFABRIK}/{p}-latest.osm.pbf" for p in [info["geofabrik"]] + [
            s if isinstance(s, str) else s["geofabrik"] for s in block["sources"]]}),
        "attribution": ATTRIBUTION,
    }
    poi = Path(a.out) / "poi.json.gz"
    if poi.exists():
        with gzip.open(poi, "rt", encoding="utf-8") as f:
            doc["poi_count"] = json.load(f)["count"]
    search = Path(a.out) / "ricerca.sqlite.gz"
    if search.exists():
        meta = search_meta(search)
        doc["search"] = {"version": int(meta["versione"]), "places": int(meta["luoghi"]),
                         "numbers": int(meta["civici"])}
        if "ban" in meta["fonti"].split(","):
            doc["attribution"] += BAN_ATTRIBUTION
    (Path(a.out) / "zona.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print(f"{doc['name']}: {doc['bytes'] / 1e6:.0f} MB")
    for name, f in files.items():
        print(f"  {name}: {f['bytes'] / 1e6:.1f} MB")
    print(f"  BRouter: {', '.join(doc['brouter'])}")


def presentation(info):
    """What the list says about how a zone is shown: its names in the other languages and, when it is legacy, the
    regions that replace it."""
    doc = {}
    if "names" in info:
        doc["names"] = info["names"]
    if info.get("legacy"):
        doc["legacy"] = True
        doc["replaced_by"] = info["replaced_by"]
    return doc


def index(a):
    zones = [json.loads(Path(p).read_text()) for p in a.zones]
    # A zona.json says what the list said when the zone was built: the names and legacy of the list now win, so a
    # change to the list reaches the app at the next index without building every zone again.
    if a.zones_list:
        infos = {z["id"]: z for z in json.loads(Path(a.zones_list).read_text())["zones"]}
        for z in zones:
            if z["id"] in infos:
                z.pop("names", None)
                z.pop("legacy", None)
                z.pop("replaced_by", None)
                z.update(presentation(infos[z["id"]]))
    # A zone's box widened by 20 km touches 5x5 degree squares that are open sea, and brouter.de has no segment
    # for those: the list of what the server really has prunes them, or the app would ask for a file that is not there.
    if a.brouter_have:
        have = set(Path(a.brouter_have).read_text().split())
        for z in zones:
            missing = [s for s in z["brouter"] if s not in have]
            if missing:
                print(f"{z['id']}: senza i segmenti BRouter {', '.join(missing)}")
                z["brouter"] = [s for s in z["brouter"] if s in have]
    doc = {
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": BASE_URL,
        # The BRouter segments: the copy of this edition in a release of its own, or brouter.de when that failed.
        "brouter_url": a.brouter_url,
        # The shared terrain, one release a row of squares: <terrain_url>/terreno-N44/N44E008.hgt.gz and
        # N44E008.curve.pmtiles, listed with their sizes in <terrain_url>/terreno-N44/terreno.json.
        "terrain_url": BASE_URL,
        "contours": a.contours,
        "zones": sorted(zones, key=lambda z: (z["country"] != "IT", z["country"], z["id"])),
    }
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    for z in doc["zones"]:
        print(f"{z['id']}: {z['tag']}, {z['bytes'] / 1e6:.0f} MB")


def terrain(a):
    """The manifest of one row of the shared terrain. A square has "hgt" and "curve", each with size and sha256, or
    null where the sea leaves nothing to publish; a square built this time replaces the one in the previous
    manifest, the others stay."""
    old = json.loads(Path(a.previous).read_text()) if a.previous and Path(a.previous).exists() else {}
    squares = dict(old.get("squares", {})) if old.get("contours") == a.contours else {}
    before = len(squares)
    for name in sorted({f.name.split(".")[0] for f in Path(a.dir).iterdir() if f.name[0] in "NS" and "." in f.name}):
        hgt = Path(a.dir, f"{name}.hgt.gz")
        curve = Path(a.dir, f"{name}.curve.pmtiles")
        squares[name] = {"hgt": describe(hgt) if hgt.exists() else None,
                         "curve": describe(curve) if curve.exists() else None}
    doc = {"contours": a.contours, "attribution": ATTRIBUTION, "squares": dict(sorted(squares.items()))}
    Path(a.out).write_text(json.dumps(doc, separators=(",", ":")))
    print(f"{len(doc['squares'])} quadrati nel manifesto, {len(squares) - before} nuovi")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    z = sub.add_parser("zone")
    z.add_argument("out")
    z.add_argument("zones")
    z.add_argument("id")
    z.add_argument("area")
    z.add_argument("--edition", required=True)
    z.add_argument("--tag", required=True)
    z.add_argument("--valhalla", required=True)
    z.add_argument("--contours", required=True)
    i = sub.add_parser("index")
    i.add_argument("out")
    i.add_argument("zones", nargs="+")
    i.add_argument("--brouter-url", default="https://brouter.de/brouter/segments4")
    i.add_argument("--brouter-have")
    i.add_argument("--contours", default="")
    i.add_argument("--zones", dest="zones_list")
    t = sub.add_parser("terrain")
    t.add_argument("out")
    t.add_argument("dir")
    t.add_argument("--contours", required=True)
    t.add_argument("--previous")
    a = p.parse_args()
    {"zone": zone, "index": index, "terrain": terrain}[a.cmd](a)


if __name__ == "__main__":
    main()
