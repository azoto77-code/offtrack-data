#!/usr/bin/env python3
"""Writes the elevations of one of OffTrack's offline zones: a tar of SRTM .hgt files of about 90 m, one per square
of 1x1 degree that the zone touches, named N44E008.hgt.gz.

The source is the "skadi" set of the public Terrain Tiles on AWS, the same elevations the contour lines come from:
one .hgt per square at 1 arc second (3601x3601). Every third sample of every third row is kept, which gives the
classic 3 arc second grid (1201x1201, big-endian 16-bit metres, -32768 where there is no data): enough for the
profile of a track and the slope of a road, at a tenth of the size.

    dem_zone.py OUT.tar AREA.poly
"""
import argparse
import gzip
import io
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from zone_area import read_poly, squares, widen

URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{ns}/{name}.hgt.gz"
FULL = 3601


def fetch(name):
    """The 1 arc second grid of the square, or None where the set has no file (open sea)."""
    url = URL.format(ns=name[:3], name=name)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                raw = gzip.decompress(r.read())
            return np.frombuffer(raw, dtype=">i2").reshape(FULL, FULL)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            err = e
        except OSError as e:
            err = e
        time.sleep(5 * (attempt + 1))
    raise err


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("area", type=Path)
    a = p.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(a.out, "w") as tar:
        for name in squares(widen(read_poly(a.area))):
            grid = fetch(name)
            if grid is None:
                print(f"{name}: nessuna quota")
                continue
            small = np.ascontiguousarray(grid[::3, ::3]).astype(">i2")
            # mtime 0, so the same elevations always give the same file and the app does not download them again.
            data = gzip.compress(small.tobytes(), compresslevel=9, mtime=0)
            info = tarfile.TarInfo(f"{name}.hgt.gz")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            valid = small[small != -32768]
            top = int(valid.max()) if valid.size else 0
            print(f"{name}: {small.shape[0]}x{small.shape[1]}, fino a {top} m")


if __name__ == "__main__":
    main()
