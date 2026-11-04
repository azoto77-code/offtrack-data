#!/usr/bin/env python3
"""What each map keeps around a few places, for the trial of prova-mappa.yml: the same 3x3 tiles of zoom 15 are read
from the z15 file and, cut to the same ground, from the z14 ones. Prints a Markdown table per place and draws the
data of the central tile of each file side by side in PREVIEWS/<name>.png: roads by kind, buildings, house numbers,
named points.

    conta.py OUT_DIR PREVIEWS LAT LON NAME [LAT LON NAME ...]
"""
import gzip
import math
import sys
from collections import Counter
from pathlib import Path

import mapbox_vector_tile
from pmtiles.reader import MmapSource, Reader
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from shapely import affinity
from shapely.geometry import box, shape
from shapely.validation import make_valid

RADIUS = 1  # tiles of zoom 15 on each side of the place's own


def tile_of(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def read(reader, z, x, y):
    data = reader.get(z, x, y)
    if not data:
        return {}
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})


def features(reader, maxzoom, x15, y15, dx, dy):
    """The features of the z15 tile x15/y15, from the file's own z15 tile or cut from its z14 parent, in units of a
    z15 tile of extent 4096, placed at column dx and row dy of the block."""
    if maxzoom >= 15:
        layers = read(reader, 15, x15, y15)
    else:
        layers = read(reader, 14, x15 // 2, y15 // 2)
    out = []
    for name, layer in layers.items():
        extent = layer.get("extent", 4096)
        for f in layer["features"]:
            g = shape(f["geometry"])
            if not g.is_valid:
                g = make_valid(g)
            if maxzoom < 15:
                half = extent / 2
                ox, oy = x15 % 2, y15 % 2
                g = g.intersection(box(ox * half, oy * half, (ox + 1) * half, (oy + 1) * half))
                if g.is_empty:
                    continue
                g = affinity.translate(g, -ox * half, -oy * half)
                k = 4096 / half
            else:
                k = 4096 / extent
            g = affinity.affine_transform(g, [k, 0, 0, k, dx * 4096, dy * 4096])
            out.append((name, f.get("properties", {}), g))
    return out


def summary(feats, metres_per_tile):
    m = metres_per_tile / 4096
    s = Counter()
    names = {"strade con nome": set(), "luoghi e POI con nome": set()}
    for layer, p, g in feats:
        kind = p.get("kind_detail") or p.get("kind") or p.get("class") or ""
        if layer in ("roads", "transportation"):
            s["strade: km"] += g.length * m / 1000
            s[f"strade: {kind} km"] += g.length * m / 1000
        if layer in ("roads", "transportation_name") and p.get("name"):
            names["strade con nome"].add(p["name"])
        if layer in ("buildings", "building"):
            # A mended polygon can come back as a collection: its polygons count all the same.
            parts = polygons_of(g)
            s["edifici: ettari"] += sum(p.area for p in parts) * m * m / 10000
            s["edifici: poligoni"] += len(parts)
        if (p.get("addr_housenumber") or p.get("housenumber")) and g.geom_type == "Point":
            s["civici"] += 1
        if layer in ("pois", "poi"):
            s["POI"] += 1
        if layer in ("pois", "poi", "places", "place", "mountain_peak") and p.get("name"):
            names["luoghi e POI con nome"].add(p["name"])
    for k, v in names.items():
        s[k] = len(v)
    return s


ROAD_STYLE = {  # colour and width by Protomaps kind or OpenMapTiles class
    "highway": ("#d9534f", 2.2), "motorway": ("#d9534f", 2.2), "trunk": ("#e8743b", 2.0), "primary": ("#e8743b", 1.8),
    "major_road": ("#f0ad4e", 1.6), "secondary": ("#f0ad4e", 1.6), "tertiary": ("#f0ad4e", 1.3),
    "minor_road": ("#555555", 0.9), "minor": ("#555555", 0.9), "service": ("#888888", 0.6),
    "track": ("#8b5a2b", 0.8), "path": ("#2e8b57", 0.6),
}


def lines_of(g):
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type == "MultiLineString":
        return list(g.geoms)
    if hasattr(g, "geoms"):
        return [l for part in g.geoms for l in lines_of(part)]
    return []


def polygons_of(g):
    if g.geom_type == "Polygon":
        return [g]
    if g.geom_type == "MultiPolygon":
        return list(g.geoms)
    if hasattr(g, "geoms"):
        return [p for part in g.geoms for p in polygons_of(part)]
    return []


def draw(ax, feats, title, counts):
    """The central z15 tile of the block (about 900 m a side), where house numbers and names can still be read."""
    lo, hi = 4096 * RADIUS, 4096 * (RADIUS + 1)
    view = box(lo, lo, hi, hi)
    water, buildings, roads, colours, widths = [], [], [], [], []
    for layer, p, g in feats:
        if not g.intersects(view):
            continue
        if layer == "water":
            water += [list(poly.exterior.coords) for poly in polygons_of(g)]
        elif layer in ("buildings", "building"):
            buildings += [list(poly.exterior.coords) for poly in polygons_of(g)]
        elif layer in ("roads", "transportation"):
            kind = p.get("kind") or p.get("class") or ""
            detail = p.get("kind_detail") or p.get("class") or ""
            colour, width = ROAD_STYLE.get(detail, ROAD_STYLE.get(kind, ("#555555", 0.8)))
            if detail in ("footway", "path", "steps", "cycleway", "bridleway", "pedestrian", "sidewalk"):
                colour, width = ROAD_STYLE["path"]
            for l in lines_of(g):
                roads.append(list(l.coords))
                colours.append(colour)
                widths.append(width * 1.6)
    ax.add_collection(PolyCollection(water, facecolors="#a8d0f0", edgecolors="none"))
    ax.add_collection(PolyCollection(buildings, facecolors="#c9b8a6", edgecolors="#a08c78", linewidths=0.2))
    ax.add_collection(LineCollection(roads, colors=colours, linewidths=widths, capstyle="round"))
    for layer, p, g in feats:
        if g.geom_type != "Point" or not view.contains(g):
            continue
        number = p.get("addr_housenumber") or p.get("housenumber")
        if number:
            ax.text(g.x, g.y, str(number), fontsize=3.5, color="#7a3e9d", ha="center", va="center")
        elif layer in ("pois", "poi", "places", "place", "mountain_peak"):
            ax.plot(g.x, g.y, "o", color="#1f77b4", markersize=1.6)
            if p.get("name"):
                ax.text(g.x, g.y - 25, p["name"], fontsize=3.5, color="#1f4e79", ha="center")
    ax.set_xlim(lo, hi)
    ax.set_ylim(hi, lo)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=9)


def main():
    out = Path(sys.argv[1])
    previews = Path(sys.argv[2])
    previews.mkdir(parents=True, exist_ok=True)
    files = {f.stem: f for f in sorted(out.glob("*.pmtiles"), key=lambda f: ("openfreemap" in f.stem, f.stem), reverse=False)}
    args = sys.argv[3:]
    for i in range(0, len(args), 3):
        lat, lon, name = float(args[i]), float(args[i + 1]), args[i + 2]
        cx, cy = tile_of(lat, lon, 15)
        metres = 40075016.686 * math.cos(math.radians(lat)) / 2 ** 15
        cols = {}
        drawn = {}
        for stem, path in files.items():
            with open(path, "rb") as fh:
                reader = Reader(MmapSource(fh))
                maxzoom = reader.header()["max_zoom"]
                feats = []
                for dx in range(-RADIUS, RADIUS + 1):
                    for dy in range(-RADIUS, RADIUS + 1):
                        feats += features(reader, maxzoom, cx + dx, cy + dy, dx + RADIUS, dy + RADIUS)
                cols[stem] = summary(feats, metres)
                drawn[stem] = feats
        fig, axes = plt.subplots(1, len(files), figsize=(6 * len(files), 6.4), dpi=250)
        for ax, stem in zip(axes, files):
            draw(ax, drawn[stem], stem, cols[stem])
        fig.suptitle(f"{name}: tile centrale di zoom 15, circa {metres:.0f} m di lato", fontsize=11)
        fig.tight_layout()
        fig.savefig(previews / f"{name}.png")
        plt.close(fig)
        rows = sorted({k for c in cols.values() for k in c}, key=lambda k: (not k.startswith("strade: km"), k))
        side = metres * (2 * RADIUS + 1) / 1000
        print(f"\n#### {name} ({lat}, {lon}), {side:.1f} x {side:.1f} km\n")
        print("| | " + " | ".join(cols) + " |")
        print("|---|" + "---|" * len(cols))
        for r in rows:
            vals = [cols[c].get(r, 0) for c in cols]
            print(f"| {r} | " + " | ".join(f"{v:.1f}" if isinstance(v, float) else str(v) for v in vals) + " |")


if __name__ == "__main__":
    main()
