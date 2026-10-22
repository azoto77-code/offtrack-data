#!/usr/bin/env python3
"""Writes the elevations of OffTrack's offline zones, one SRTM .hgt file of about 90 m per square of 1x1 degree.

The source is the "skadi" set of the public Terrain Tiles on AWS, the same elevations the contour lines come from:
one .hgt per square at 1 arc second (3601x3601). Every third sample of every third row is kept, which gives the
classic 3 arc second grid (1201x1201, big-endian 16-bit metres, -32768 where there is no data): enough for the
profile of a track and the slope of a road, at a tenth of the size.

    dem_squares.py OUT_DIR N44E008 [N45E007 ...]
"""
import argparse
import gzip
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

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
    p.add_argument("squares", nargs="+")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for name in a.squares:
        grid = fetch(name)
        if grid is None:
            print(f"{name}: nessuna quota")
            continue
        small = np.ascontiguousarray(grid[::3, ::3]).astype(">i2")
        with gzip.open(a.out / f"{name}.hgt.gz", "wb", compresslevel=9) as f:
            f.write(small.tobytes())
        valid = small[small != -32768]
        top = int(valid.max()) if valid.size else 0
        print(f"{name}: {small.shape[0]}x{small.shape[1]}, fino a {top} m")


if __name__ == "__main__":
    main()
