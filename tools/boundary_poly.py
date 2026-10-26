#!/usr/bin/env python3
"""Writes the border of a country (or any boundary relation of OpenStreetMap) as an Osmosis .poly file, for the zones
that Geofabrik does not publish on their own: Oman, for one, comes only inside "asia/gcc-states".

The relation is taken from the extract itself with osmium, so the border is that of the same day's data; it is
simplified to about 500 m, which is all the zone tools need (they widen it by 5 km anyway).

    boundary_poly.py IN.osm.pbf RELATION_ID OUT.poly
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from shapely.geometry import MultiPolygon, shape


def boundary(pbf, relation):
    """The area of boundary relation [relation] in [pbf], as one shapely (multi)polygon."""
    with tempfile.TemporaryDirectory() as tmp:
        rel = Path(tmp, "rel.osm.pbf")
        out = Path(tmp, "rel.geojson")
        subprocess.run(["osmium", "getid", "-r", "-o", str(rel), str(pbf), f"r{relation}"], check=True)
        subprocess.run(["osmium", "export", "--geometry-types=polygon", "-o", str(out), str(rel)], check=True)
        features = json.loads(out.read_text())["features"]
    areas = [shape(f["geometry"]) for f in features if f["properties"].get("boundary") == "administrative"]
    if not areas:
        raise SystemExit(f"r{relation}: nessun confine in {pbf}")
    # The largest area is the relation itself; smaller administrative ones inside it are its subdivisions.
    return max(areas, key=lambda a: a.area)


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


def main():
    pbf, relation, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    # Simplifying can make a ring cross itself: buffer(0) mends it.
    area = boundary(pbf, relation).simplify(0.005).buffer(0)
    write_poly(area, out, f"r{relation}")
    print(f"r{relation}: {len(getattr(area, 'geoms', [area]))} parti, riquadro {[round(b, 3) for b in area.bounds]}")


if __name__ == "__main__":
    main()
