#!/usr/bin/env python3
"""Writes the border of a country or a region (any boundary relation of OpenStreetMap) as an Osmosis .poly file, for
the zones that Geofabrik does not publish on their own: Oman comes only inside "asia/gcc-states", Piedmont inside
"europe/italy/nord-ovest".

The relation is named by its id (305138 for Oman) or by its ISO 3166-2 code (IT-21 for Piedmont, FR-BRE for
Brittany, ES-CT for Catalonia): the code is written on the relation by OpenStreetMap and does not change, and the
name of what was found is printed, to check it by eye in the log. The relation is taken from the extract itself with
osmium, so the border is that of the same day's data; it is simplified to about 500 m, which is all the zone tools
need (they widen it by 5 km anyway).

    boundary_poly.py IN.osm.pbf RELATION_ID|ISO3166-2 OUT.poly
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from shapely.geometry import MultiPolygon, shape


def boundary(pbf, relation):
    """The area of boundary relation [relation] (an id, or an ISO 3166-2 code) in [pbf], as one shapely
    (multi)polygon, and the name of the relation."""
    with tempfile.TemporaryDirectory() as tmp:
        rel = Path(tmp, "rel.osm.pbf")
        out = Path(tmp, "rel.geojson")
        if isinstance(relation, int):
            subprocess.run(["osmium", "getid", "-r", "-o", str(rel), str(pbf), f"r{relation}"], check=True)
        else:
            # The relation with that code and, as getid -r does, the ways and nodes it is made of.
            subprocess.run(["osmium", "tags-filter", "-o", str(rel), str(pbf), f"r/ISO3166-2={relation}"], check=True)
        subprocess.run(["osmium", "export", "--geometry-types=polygon", "-o", str(out), str(rel)], check=True)
        features = json.loads(out.read_text())["features"]
    found = [(shape(f["geometry"]), f["properties"]) for f in features
             if f["properties"].get("boundary") == "administrative"
             and (isinstance(relation, int) or f["properties"].get("ISO3166-2") == relation)]
    if not found:
        raise SystemExit(f"{relation}: nessun confine in {pbf}")
    # With an id, the largest area is the relation itself; smaller administrative ones inside it are its subdivisions.
    area, tags = max(found, key=lambda f: f[0].area)
    return area, tags.get("name", "?")


def write_poly(area, path, name):
    """[area] in the Osmosis format: one numbered ring per polygon, holes marked with "!"."""
    polygons = list(area.geoms) if isinstance(area, MultiPolygon) else [area]
    lines = [name]
    n = 0
    for p in polygons:
        for ring, hole in [(p.exterior, False)] + [(r, True) for r in p.interiors]:
            n += 1
            lines.append(("!" if hole else "") + str(n))
            lines += [f"   {x:.6f} {y:.6f}" for x, y in ring.coords]
            lines.append("END")
    lines.append("END")
    Path(path).write_text("\n".join(lines) + "\n")


def parse(relation):
    """An id as an int, a code as it is."""
    return int(relation) if relation.isdigit() else relation


def main():
    pbf, relation, out = sys.argv[1], parse(sys.argv[2]), sys.argv[3]
    area, name = boundary(pbf, relation)
    # Simplifying can make a ring cross itself: buffer(0) mends it.
    area = area.simplify(0.005).buffer(0)
    write_poly(area, out, f"r{relation}")
    print(f"{relation} ({name}): {len(getattr(area, 'geoms', [area]))} parti, riquadro {[round(b, 3) for b in area.bounds]}")


if __name__ == "__main__":
    main()
