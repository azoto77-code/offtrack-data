#!/usr/bin/env python3
"""The outline of an offline zone, as Geofabrik publishes it in an Osmosis .poly file, and what the other tools of the
zones take from it: the outline widened by a few kilometres, the 1x1 degree squares and the BRouter segments it
touches, and a light outline for the app to draw.

    zone_area.py AREA.poly [--geojson OUT]   prints the box, the squares and the segments of the zone; with
                                             --geojson also writes the widened outline, for `pmtiles extract`
    zone_area.py --square N44E008 OUT.poly   writes the 1x1 degree square as a .poly, for the shared terrain
"""
import json
import math
import sys
from pathlib import Path

from shapely import box, prepare, union_all
from shapely.geometry import Polygon, mapping

# Every file of a zone reaches this far beyond its border, so a road that runs along it, or a point just across, is
# there whichever zone the rider is in.
BUFFER_KM = 5


def read_poly(path):
    """The area of an Osmosis .poly file (as Geofabrik publishes them); holes, marked with "!", are cut out."""
    outer, holes, ring, hole = [], [], None, False
    for line in Path(path).read_text().splitlines()[1:]:
        s = line.strip()
        if not s:
            continue
        if s == "END":
            if ring is None:
                break
            (holes if hole else outer).append(Polygon(ring))
            ring = None
        elif ring is None:
            ring, hole = [], s.startswith("!")
        else:
            lon, lat = s.split()[:2]
            ring.append((float(lon), float(lat)))
    area = union_all(outer)
    return area.difference(union_all(holes)) if holes else area


def widen(area, km=BUFFER_KM):
    """The area grown by [km] in every direction. Degrees of longitude are shorter than those of latitude, so the
    growth is measured on the parallel of the zone's southern edge, where they are longest: never less than [km]."""
    south = area.bounds[1]
    return area.buffer(km / (111.32 * math.cos(math.radians(abs(south) + 1))), 8)


def square_name(lat, lon):
    """The 1x1 degree square a point lies in, named by its south-west corner: N44E008."""
    s, w = math.floor(lat), math.floor(lon)
    return f"{'N' if s >= 0 else 'S'}{abs(s):02d}{'E' if w >= 0 else 'W'}{abs(w):03d}"


def square_box(name):
    """The 1x1 degree square of a name like N44E008, as a shapely box."""
    s = int(name[1:3]) * (1 if name[0] == "N" else -1)
    w = int(name[4:7]) * (1 if name[3] == "E" else -1)
    return box(w, s, w + 1, s + 1)


def band(name):
    """The row of squares a square belongs to, N44 for N44E008: the shared terrain is published one release a row."""
    return name[:3]


def write_poly(area, path, name):
    """[area] as an Osmosis .poly file: one ring per polygon."""
    polygons = list(area.geoms) if hasattr(area, "geoms") else [area]
    lines = [name]
    for n, poly in enumerate(polygons, 1):
        lines.append(str(n))
        lines += [f"   {x:.6f} {y:.6f}" for x, y in poly.exterior.coords]
        lines.append("END")
    lines.append("END")
    Path(path).write_text("\n".join(lines) + "\n")


def squares(area):
    """The names of the 1x1 degree squares that touch [area]."""
    prepare(area)
    x0, y0, x1, y1 = area.bounds
    return sorted(square_name(s, w) for s in range(math.floor(y0), math.floor(y1) + 1)
                  for w in range(math.floor(x0), math.floor(x1) + 1) if area.intersects(box(w, s, w + 1, s + 1)))


def segments(area):
    """The BRouter segments of 5x5 degrees that touch [area], named as brouter.de does: E5_N45 covers 5-10 E, 45-50 N."""
    prepare(area)
    x0, y0, x1, y1 = area.bounds
    out = []
    for s in range(math.floor(y0 / 5) * 5, math.floor(y1 / 5) * 5 + 1, 5):
        for w in range(math.floor(x0 / 5) * 5, math.floor(x1 / 5) * 5 + 1, 5):
            if area.intersects(box(w, s, w + 5, s + 5)):
                out.append(f"{'E' if w >= 0 else 'W'}{abs(w)}_{'N' if s >= 0 else 'S'}{abs(s)}")
    return sorted(out)


def outline(area):
    """A light GeoJSON outline of [area] for the zone list of the app: about 1 km of detail, 5 decimals."""
    g = mapping(area.simplify(0.01))

    def rounded(c):
        return [round(c[0], 5), round(c[1], 5)] if isinstance(c[0], float) else [rounded(x) for x in c]

    return {"type": g["type"], "coordinates": rounded(g["coordinates"])}


if __name__ == "__main__":
    if sys.argv[1] == "--square":
        write_poly(square_box(sys.argv[2]), sys.argv[3], sys.argv[2])
        sys.exit()
    a = read_poly(sys.argv[1])
    w = widen(a)
    print("riquadro", [round(x, 4) for x in w.bounds])
    print("quadrati", " ".join(squares(w)))
    print("segmenti BRouter", " ".join(segments(w)))
    if "--geojson" in sys.argv:
        out = sys.argv[sys.argv.index("--geojson") + 1]
        Path(out).write_text(json.dumps({"type": "Feature", "properties": {}, "geometry": outline(w)}))
