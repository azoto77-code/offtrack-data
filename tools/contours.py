#!/usr/bin/env python3
"""Writes contour lines of the areas in Geofabrik .poly files as GeoJSON lines, for the OffTrack contour overlay.

The elevations are the public Terrain Tiles on AWS (Terrarium PNG, about 30 m a pixel at zoom 12 in Europe). They are
joined into blocks of 16x16 tiles with one tile of margin, so the lines carry on from one block to the next, smoothed
a little and traced by gdal_contour. Each line keeps its elevation ("ele") and the zoom it appears from ("minz"): every
100 m from zoom 10, every 50 m from 11, the others from 12.

    contours.py OUT.geojsonseq AREA.poly [AREA.poly ...] [--interval 10] [--cache DIR] [--jobs 4]
"""
import argparse
import concurrent.futures as cf
import io
import json
import math
import os
import subprocess
import tempfile
import time
import urllib.request
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from shapely import box, clip_by_rect, prepare, union_all
from shapely.geometry import LineString, MultiLineString, Polygon, mapping

ZOOM = 12
BLOCK = 16
TILE = 256
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


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


def tile_lon(x):
    return x / 2 ** ZOOM * 360 - 180


def tile_lat(y):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** ZOOM))))


def tile_box(x, y):
    return box(tile_lon(x), tile_lat(y + 1), tile_lon(x + 1), tile_lat(y))


def tiles_of(area):
    """The zoom 12 tiles that touch [area]."""
    n = 2 ** ZOOM
    x0, y0, x1, y1 = area.bounds
    ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    prepare(area)
    return {(x, y) for x in range(int((x0 + 180) / 360 * n), int((x1 + 180) / 360 * n) + 1)
            for y in range(ty(y1), ty(y0) + 1) if area.intersects(tile_box(x, y))}


def fetch(x, y, cache):
    """The PNG of a tile, from the cache or AWS; four tries before giving up."""
    path = Path(cache) / f"{x}_{y}.png"
    if path.exists():
        return path.read_bytes()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(URL.format(z=ZOOM, x=x, y=y), timeout=60) as r:
                data = r.read()
            path.write_bytes(data)
            return data
        except OSError:
            time.sleep(2 ** attempt)
    raise OSError(f"tile {ZOOM}/{x}/{y} non scaricato")


def elevations(data):
    a = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
    return a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256 - 32768


def to_lonlat(coords):
    """Global pixel coordinates (y negated, as written for gdal_contour) to longitude and latitude."""
    c = np.asarray(coords)
    size = TILE * 2 ** ZOOM
    lon = c[:, 0] / size * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(math.pi * (1 + 2 * c[:, 1] / size))))
    return np.column_stack([lon, lat])


def minzoom(ele):
    return 10 if ele % 100 == 0 else 11 if ele % 50 == 0 else 12


def block(job):
    """Contour lines of one block of 16x16 tiles, clipped to the block and to the area, as GeoJSON text lines."""
    bx, by, area, interval, cache = job
    x0, y0 = bx * BLOCK - 1, by * BLOCK - 1
    side = (BLOCK + 2) * TILE
    dem = np.empty((side, side), dtype=np.float32)
    for j in range(BLOCK + 2):
        for i in range(BLOCK + 2):
            dem[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE] = elevations(fetch(x0 + i, y0 + j, cache))
    # A light blur takes the steps of the 1 m rounding and of the source models out of the lines.
    dem = gaussian_filter(dem, 1.0)
    with tempfile.TemporaryDirectory() as tmp:
        bil = os.path.join(tmp, "dem.bil")
        dem.astype("<f4").tofile(bil)
        # Georeferenced in global pixels, north up: x to the east, -y to the north.
        Path(tmp, "dem.hdr").write_text(
            f"BYTEORDER I\nLAYOUT BIL\nNROWS {side}\nNCOLS {side}\nNBANDS 1\nNBITS 32\nPIXELTYPE FLOAT\n"
            f"ULXMAP {x0 * TILE + 0.5}\nULYMAP {-(y0 * TILE + 0.5)}\nXDIM 1\nYDIM 1\n")
        out = os.path.join(tmp, "lines.geojsonseq")
        subprocess.run(["gdal_contour", "-q", "-a", "ele", "-i", str(interval), "-f", "GeoJSONSeq", bil, out],
                       check=True)
        lines = [json.loads(s.lstrip("\x1e")) for s in Path(out).read_text().splitlines() if s.strip()]
    core = box(tile_lon(x0 + 1), tile_lat(y0 + 1 + BLOCK), tile_lon(x0 + 1 + BLOCK), tile_lat(y0 + 1))
    inside = area.intersection(core)
    whole = inside.equals(core)
    prepare(inside)
    text = []
    for f in lines:
        ele = int(round(f["properties"]["ele"]))
        if ele <= 0:
            continue
        g = LineString(to_lonlat(f["geometry"]["coordinates"]))
        g = clip_by_rect(g, *core.bounds) if whole else g.intersection(inside)
        if g.is_empty:
            continue
        parts = [g] if isinstance(g, LineString) else [p for p in getattr(g, "geoms", []) if isinstance(p, LineString)]
        for p in parts:
            # About 4 m: well under a pixel of the elevations, and it takes most of the points off steady slopes.
            p = p.simplify(0.00004)
            if len(p.coords) < 2:
                continue
            coords = [[round(lon, 5), round(lat, 5)] for lon, lat in p.coords]
            text.append("\x1e" + json.dumps({
                "type": "Feature", "properties": {"ele": ele, "minz": minzoom(ele)},
                "geometry": {"type": "LineString", "coordinates": coords}}, separators=(",", ":")) + "\n")
    return "".join(text)


def main():
    p = argparse.ArgumentParser(description="Curve di livello per OffTrack")
    p.add_argument("out")
    p.add_argument("areas", nargs="+")
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--cache", default="dem-cache")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    a = p.parse_args()
    Path(a.cache).mkdir(parents=True, exist_ok=True)
    area = union_all([read_poly(f) for f in a.areas])
    tiles = tiles_of(area)
    blocks = sorted({(x // BLOCK, y // BLOCK) for x, y in tiles})
    need = {(bx * BLOCK + i, by * BLOCK + j) for bx, by in blocks for i in range(-1, BLOCK + 1) for j in range(-1, BLOCK + 1)}
    print(f"{len(tiles)} tile nell'area, {len(blocks)} blocchi, {len(need)} tile da scaricare", flush=True)
    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda t: fetch(t[0], t[1], a.cache), need))
    print("quote scaricate", flush=True)
    jobs = [(bx, by, area.intersection(box(tile_lon(bx * BLOCK), tile_lat((by + 1) * BLOCK),
                                           tile_lon((bx + 1) * BLOCK), tile_lat(by * BLOCK))), a.interval, a.cache)
            for bx, by in blocks]
    with open(a.out, "w") as out, Pool(a.jobs) as pool:
        for k, text in enumerate(pool.imap(block, jobs)):
            out.write(text)
            print(f"blocco {k + 1}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    main()
