#!/usr/bin/env python3
"""Writes the descriptions the app reads to offer the offline zones.

"zone" writes zona.json in the directory of one zone's files: what the zone is, where its outline runs, and the size
and sha256 of each file, so the app downloads again only the files that changed from the edition it has. "index"
joins the zona.json of every zone into indice.json, the list the app reads first.

    zone_index.py zone OUT_DIR ZONES.json ID AREA.poly --edition 20261104 --tag zona-nord-ovest-20261104
                  --valhalla 3.6.3 --contours 20m-1
    zone_index.py index OUT.json ZONA.json [ZONA.json ...]
"""
import argparse
import datetime
import gzip
import hashlib
import json
from pathlib import Path

from zone_area import outline, read_poly, segments, squares, widen

GEOFABRIK = "https://download.geofabrik.de"
BASE_URL = "https://github.com/azoto77-code/offtrack-data/releases/download"
ATTRIBUTION = ("Dati © OpenStreetMap contributors, licenza ODbL. Quote: Terrain Tiles su AWS (SRTM, EU-DEM prodotto "
               "con dati Copernicus, Mapzen).")


def describe(path):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": sha.hexdigest()}


def zone(a):
    zones = json.loads(Path(a.zones).read_text())
    info = next(z for z in zones["zones"] if z["id"] == a.id)
    area = read_poly(a.area)
    wide = widen(area)
    files = {f.name: describe(f) for f in sorted(Path(a.out).iterdir()) if f.is_file() and f.name != "zona.json"}
    doc = {
        "id": info["id"],
        "name": info["name"],
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
        "sources": sorted({f"{GEOFABRIK}/{p}-latest.osm.pbf" for p in [info["geofabrik"]] + [
            s if isinstance(s, str) else s["geofabrik"] for s in zones["valhalla_sources"]]}),
        "attribution": ATTRIBUTION,
    }
    poi = Path(a.out) / "poi.json.gz"
    if poi.exists():
        with gzip.open(poi, "rt", encoding="utf-8") as f:
            doc["poi_count"] = json.load(f)["count"]
    (Path(a.out) / "zona.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print(f"{doc['name']}: {doc['bytes'] / 1e6:.0f} MB")
    for name, f in files.items():
        print(f"  {name}: {f['bytes'] / 1e6:.1f} MB")
    print(f"  BRouter: {', '.join(doc['brouter'])}")


def index(a):
    zones = [json.loads(Path(p).read_text()) for p in a.zones]
    doc = {
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": BASE_URL,
        "brouter_url": "https://brouter.de/brouter/segments4",
        "zones": sorted(zones, key=lambda z: (z["country"] != "IT", z["country"], z["id"])),
    }
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    for z in doc["zones"]:
        print(f"{z['id']}: {z['tag']}, {z['bytes'] / 1e6:.0f} MB")


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
    a = p.parse_args()
    zone(a) if a.cmd == "zone" else index(a)


if __name__ == "__main__":
    main()
