#!/usr/bin/env python3
"""Splits a Valhalla tile directory into packs of 1x1 degree for OffTrack.

Each pack holds the level 1 tile of its square, the 16 level 2 tiles inside it and the level 0 tile that covers
it, at their usual paths, so the phone can untar any set of packs into one tile directory. Writes the packs and
index.json, which lists them, into the output directory.

    split_tiles.py TILE_DIR OUT_DIR --valhalla 3.6.3 --source URL
"""
import argparse
import datetime
import hashlib
import json
import os
import tarfile
from pathlib import Path

# Size in degrees of a tile at each hierarchy level; level 3 (transit) is not built.
SIZES = {0: 4.0, 1: 1.0, 2: 0.25}


def tile_box(level, tile_id):
    """South-west corner of a tile from its level and id."""
    size = SIZES[level]
    cols = int(round(360.0 / size))
    row, col = divmod(tile_id, cols)
    return -90.0 + row * size, -180.0 + col * size


def tile_id(level, rel):
    """The id of a tile from its path below the level directory, e.g. 000/751/234.gph -> 751234."""
    return int("".join(rel.with_suffix("").parts))


def cell_name(south, west):
    ns = "N" if south >= 0 else "S"
    ew = "E" if west >= 0 else "W"
    return f"{ns}{abs(int(south)):02d}{ew}{abs(int(west)):03d}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tiles", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--valhalla", required=True)
    p.add_argument("--source", required=True)
    a = p.parse_args()

    by_level = {lvl: {} for lvl in SIZES}
    for lvl in SIZES:
        base = a.tiles / str(lvl)
        if not base.is_dir():
            continue
        for f in base.rglob("*.gph"):
            by_level[lvl][tile_id(lvl, f.relative_to(base))] = f

    cells = {}
    for lvl in (1, 2):
        for tid, f in by_level[lvl].items():
            s, w = tile_box(lvl, tid)
            key = (int(s // 1), int(w // 1))
            cells.setdefault(key, []).append(f)

    a.out.mkdir(parents=True, exist_ok=True)
    entries = []
    for (s, w), files in sorted(cells.items()):
        # The level 0 tile covering the square.
        cols0 = int(360 / SIZES[0])
        l0 = by_level[0].get(int((s + 90) // SIZES[0]) * cols0 + int((w + 180) // SIZES[0]))
        if l0 is not None:
            files = files + [l0]
        name = cell_name(s, w) + ".tar"
        path = a.out / name
        with tarfile.open(path, "w") as tar:
            for f in sorted(set(files)):
                tar.add(f, arcname=str(f.relative_to(a.tiles)))
        data = path.read_bytes()
        entries.append({
            "name": name,
            "south": s,
            "west": w,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    index = {
        "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valhalla": a.valhalla,
        "source": a.source,
        "cell_degrees": 1,
        "cells": entries,
    }
    (a.out / "index.json").write_text(json.dumps(index, indent=1))
    total = sum(e["bytes"] for e in entries)
    print(f"{len(entries)} packs, {total / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
