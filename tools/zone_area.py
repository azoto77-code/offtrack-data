#!/usr/bin/env python3
"""The outline of an offline zone, as Geofabrik publishes it in an Osmosis .poly file, and what the other tools of the
zones take from it: the outline widened by a few kilometres, the 1x1 degree squares and the BRouter segments it
touches, and a light outline for the app to draw.

    zone_area.py AREA.poly [--geojson OUT]   prints the box, the squares and the segments of the zone; with
                                             --geojson also writes the widened outline, for `pmtiles extract`
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
    a = read_poly(sys.argv[1])
    w = widen(a)
    print("riquadro", [round(x, 4) for x in w.bounds])
    print("quadrati", " ".join(squares(w)))
    print("segmenti BRouter", " ".join(segments(w)))
    if "--geojson" in sys.argv:
        out = sys.argv[sys.argv.index("--geojson") + 1]
        Path(out).write_text(json.dumps({"type": "Feature", "properties": {}, "geometry": outline(w)}))
