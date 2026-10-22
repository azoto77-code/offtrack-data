#!/usr/bin/env python3
"""Cuts the Valhalla tiles of one offline zone out of the common build of all the zones.

Every zone takes the tiles of each level that touch its outline widened by a few kilometres, at their usual paths,
so the phone untars the zones it has into one tile directory. All the zones come from the same build, so a tile two
zones share is the same file in both, and a route from one zone into the next carries on across the border.

    valhalla_zone.py TILE_DIR OUT.tar AREA.poly
"""
import argparse
import tarfile
from pathlib import Path

from shapely import box, prepare

from split_tiles import SIZES, tile_box, tile_id
from zone_area import read_poly, widen


def tiles_in(tiles, area):
    """The tile files of [tiles] whose box touches [area], level by level."""
    prepare(area)
    out = []
    for lvl, size in SIZES.items():
        base = tiles / str(lvl)
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.gph")):
            s, w = tile_box(lvl, tile_id(lvl, f.relative_to(base)))
            if area.intersects(box(w, s, w + size, s + size)):
                out.append(f)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("tiles", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("area", type=Path)
    a = p.parse_args()
    files = tiles_in(a.tiles, widen(read_poly(a.area)))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(a.out, "w") as tar:
        for f in files:
            # Owner and date left out, so the same tiles always give the same file.
            info = tar.gettarinfo(f, arcname=str(f.relative_to(a.tiles)))
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with open(f, "rb") as src:
                tar.addfile(info, src)
    levels = {}
    for f in files:
        lvl = f.relative_to(a.tiles).parts[0]
        levels[lvl] = levels.get(lvl, 0) + 1
    print(f"{a.out.name}: {len(files)} tile ({', '.join(f'livello {k}: {v}' for k, v in sorted(levels.items()))}), "
          f"{a.out.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
