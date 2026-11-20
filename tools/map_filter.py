#!/usr/bin/env python3
"""Drops from a zone's base map what the app never draws.

The Protomaps map of a zone carries every land use and every small point of OpenStreetMap, and the styles of the app
draw only some of them: fields, meadows, bare rock and residential areas are never filled, single trees, street lamps
and crossings never get an icon. They weigh a seventh of the map in Liguria and a third in Abruzzo (19 November 2026).
This rewrites the PMTiles file without them: the other layers pass through byte for byte, so nothing changes on screen.

The kinds kept are those the styles of the app name (assets/protomaps/light.json, dark.json and liberty.json, layers on
"landuse" and "pois"), listed in tools/data/map_kinds.json: they must change together. "kinds" reads them out of the
style files again.

    map_filter.py filter IN.pmtiles OUT.pmtiles [--kinds tools/data/map_kinds.json]
    map_filter.py kinds STYLE.json [STYLE.json ...]      prints the JSON of the kinds those styles draw
"""
import argparse
import gzip
import hashlib
import io
import json
import struct
import tempfile
import zlib
from pathlib import Path

KINDS = Path(__file__).parent / "data" / "map_kinds.json"

# The layers thinned, each by the attribute "kind" of its features.
LAYERS = ("landuse", "pois")

HEADER = 127
# Header and root directory together must fit the first request of a reader.
ROOT_ROOM = 16384 - HEADER
NONE, GZIP = 1, 2


# --- Protocol buffers, as much as a vector tile needs ---

def read_varint(b, i):
    r = 0
    s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def varint(n):
    out = bytearray()
    while True:
        c = n & 0x7F
        n >>= 7
        if n:
            out.append(c | 0x80)
        else:
            out.append(c)
            return bytes(out)


def fields(b):
    """The fields of a message: number, wire type and value (the bytes of a length-delimited or fixed one)."""
    i = 0
    n = len(b)
    while i < n:
        key, i = read_varint(b, i)
        f, w = key >> 3, key & 7
        if w == 2:
            size, i = read_varint(b, i)
            yield f, w, b[i:i + size]
            i += size
        elif w == 0:
            v, i = read_varint(b, i)
            yield f, w, v
        elif w == 5:
            yield f, w, b[i:i + 4]
            i += 4
        elif w == 1:
            yield f, w, b[i:i + 8]
            i += 8
        else:
            raise ValueError(f"wire type {w}")


def field(f, w, v):
    if w == 2:
        return varint(f << 3 | 2) + varint(len(v)) + v
    if w == 0:
        return varint(f << 3) + varint(v)
    return varint(f << 3 | w) + v


def text_of(value):
    """The string of a tile value, None when it holds a number or a boolean."""
    for f, w, v in fields(value):
        if f == 1 and w == 2:
            return v.decode("utf-8", "replace")
    return None


# --- Vector tiles ---

def layer_name(body):
    for f, w, v in fields(body):
        if f == 1 and w == 2:
            return v.decode("utf-8", "replace")
    return None


def thin_layer(body, keep):
    """The layer [body] with only the features whose kind is in [keep], and only the keys and values they still use;
    None when no feature is left."""
    keys, values, features, rest = [], [], [], []
    for f, w, v in fields(body):
        if f == 3:
            keys.append(v)
        elif f == 4:
            values.append(v)
        elif f == 2:
            features.append(v)
        else:
            rest.append((f, w, v))
    kind = keys.index(b"kind") if b"kind" in keys else -1
    kept_values = {i for i, v in enumerate(values) if text_of(v) in keep} if kind >= 0 else set()
    new_keys, key_at, new_values, value_at, out = [], {}, [], {}, []
    for feature in features:
        parts = list(fields(feature))
        tags = []
        for f, w, v in parts:
            if f == 2 and w == 2:
                i = 0
                while i < len(v):
                    t, i = read_varint(v, i)
                    tags.append(t)
            elif f == 2:
                tags.append(v)
        pairs = list(zip(tags[::2], tags[1::2]))
        if not any(k == kind and v in kept_values for k, v in pairs):
            continue
        packed = bytearray()
        for k, v in pairs:
            if k not in key_at:
                key_at[k] = len(new_keys)
                new_keys.append(keys[k])
            if v not in value_at:
                value_at[v] = len(new_values)
                new_values.append(values[v])
            packed += varint(key_at[k]) + varint(value_at[v])
        feature_out = bytearray()
        written = False
        for f, w, v in parts:
            if f != 2:
                feature_out += field(f, w, v)
            elif not written:
                feature_out += field(2, 2, bytes(packed))
                written = True
        out.append(bytes(feature_out))
    if not out:
        return None
    # In the order of the field numbers, as every encoder writes a layer: name, features, keys, values, the rest.
    layer = bytearray()
    for f, w, v in rest:
        if f < 2:
            layer += field(f, w, v)
    for feature in out:
        layer += field(2, 2, feature)
    for k in new_keys:
        layer += field(3, 2, k)
    for v in new_values:
        layer += field(4, 2, v)
    for f, w, v in rest:
        if f > 4:
            layer += field(f, w, v)
    return bytes(layer)


def thin_tile(tile, kinds):
    """The tile without the features of [kinds]' layers that the app does not draw; the other layers as they were."""
    out = bytearray()
    for f, w, v in fields(tile):
        if f == 3 and w == 2:
            name = layer_name(v)
            if name in kinds:
                v = thin_layer(v, kinds[name])
                if v is None:
                    continue
        out += field(f, w, v)
    return bytes(out)


# --- PMTiles v3 ---

class Entry:
    __slots__ = ("tile_id", "offset", "length", "run")

    def __init__(self, tile_id, offset, length, run):
        self.tile_id, self.offset, self.length, self.run = tile_id, offset, length, run


def unpack(data, compression):
    if compression == GZIP:
        return gzip.decompress(data)
    if compression == NONE:
        return data
    raise ValueError(f"compression {compression}: only gzip and none are read")


def pack(data):
    # No date in the gzip header, so the same tile always gives the same bytes.
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=0) as f:
        f.write(data)
    return out.getvalue()


def read_directory(data):
    n, i = read_varint(data, 0)
    entries = []
    last = 0
    for _ in range(n):
        d, i = read_varint(data, i)
        last += d
        entries.append(Entry(last, 0, 0, 0))
    for e in entries:
        e.run, i = read_varint(data, i)
    for e in entries:
        e.length, i = read_varint(data, i)
    for k, e in enumerate(entries):
        v, i = read_varint(data, i)
        e.offset = entries[k - 1].offset + entries[k - 1].length if v == 0 and k > 0 else v - 1
    return entries


def write_directory(entries):
    out = bytearray(varint(len(entries)))
    last = 0
    for e in entries:
        out += varint(e.tile_id - last)
        last = e.tile_id
    for e in entries:
        out += varint(e.run)
    for e in entries:
        out += varint(e.length)
    for k, e in enumerate(entries):
        follows = k > 0 and e.offset == entries[k - 1].offset + entries[k - 1].length
        out += varint(0 if follows else e.offset + 1)
    return pack(bytes(out))


def directories(entries):
    """The root directory and the leaves below it: the root alone when it fits the first 16 KB of the file."""
    root = write_directory(entries)
    if len(root) <= ROOT_ROOM:
        return root, b""
    size = 4096
    while True:
        leaves = bytearray()
        pointers = []
        for i in range(0, len(entries), size):
            leaf = write_directory(entries[i:i + size])
            pointers.append(Entry(entries[i].tile_id, len(leaves), len(leaf), 0))
            leaves += leaf
        root = write_directory(pointers)
        if len(root) <= ROOT_ROOM:
            return root, bytes(leaves)
        size *= 2


class Archive:
    """A PMTiles v3 file on disk: its header, its metadata as stored, and its tiles in the order of their ids."""

    def __init__(self, path):
        self.f = open(path, "rb")
        head = self.f.read(HEADER)
        if head[:7] != b"PMTiles" or head[7] != 3:
            raise ValueError(f"{path}: not a PMTiles v3 file")
        (self.root_offset, self.root_length, self.meta_offset, self.meta_length, self.leaf_offset, self.leaf_length,
         self.data_offset, self.data_length) = struct.unpack_from("<8Q", head, 8)
        self.internal, self.tile_compression = head[97], head[98]
        # Tile type, zooms, bounds and centre: copied as they are.
        self.tail = head[99:HEADER]
        self.clustered = head[96]

    def read(self, offset, length):
        self.f.seek(offset)
        return self.f.read(length)

    def metadata(self):
        return unpack(self.read(self.meta_offset, self.meta_length), self.internal)

    def entries(self):
        """Every tile entry, leaves followed, in the order of the tile ids."""
        def walk(offset, length):
            for e in read_directory(unpack(self.read(offset, length), self.internal)):
                if e.run == 0:
                    yield from walk(self.leaf_offset + e.offset, e.length)
                else:
                    yield e
        yield from walk(self.root_offset, self.root_length)

    def tile(self, e):
        return self.read(self.data_offset + e.offset, e.length)

    def close(self):
        self.f.close()


def write_archive(path, source, entries, data, contents):
    """Writes [entries] and the tile [data] (a file, read from its start) with the header fields of [source]."""
    root, leaves = directories(entries)
    meta = pack(source.metadata())
    data.seek(0, 2)
    size = data.tell()
    root_offset = HEADER
    meta_offset = root_offset + len(root)
    leaf_offset = meta_offset + len(meta)
    data_offset = leaf_offset + len(leaves)
    head = bytearray(b"PMTiles\x03")
    head += struct.pack("<8Q", root_offset, len(root), meta_offset, len(meta), leaf_offset, len(leaves), data_offset, size)
    head += struct.pack("<3Q", sum(e.run for e in entries), len(entries), contents)
    head += bytes([source.clustered, GZIP, GZIP]) + source.tail
    assert len(head) == HEADER
    with open(path, "wb") as out:
        out.write(head)
        out.write(root)
        out.write(meta)
        out.write(leaves)
        data.seek(0)
        while chunk := data.read(1 << 20):
            out.write(chunk)


def filter_archive(src, dst, kinds):
    """Writes [src] to [dst] with every tile thinned; returns the tiles read and the bytes of tile data before and
    after. A tile left empty stays in the file as an empty tile, so the app does not take it for a missing one and
    enlarge the level above in its place."""
    source = Archive(src)
    try:
        entries = []
        # A tile of open sea or of plain forest is stored once and named by many entries: thinned once too.
        moved = {}
        by_hash = {}
        before = 0
        with tempfile.TemporaryFile() as data:
            size = 0
            for e in source.entries():
                at = moved.get(e.offset)
                if at is None:
                    before += e.length
                    tile = pack(thin_tile(unpack(source.tile(e), source.tile_compression), kinds))
                    digest = hashlib.sha256(tile).digest()
                    at = by_hash.get(digest)
                    if at is None:
                        at = by_hash[digest] = (size, len(tile))
                        data.write(tile)
                        size += len(tile)
                    moved[e.offset] = at
                last = entries[-1] if entries else None
                if last and last.offset == at[0] and last.tile_id + last.run == e.tile_id:
                    last.run += e.run
                else:
                    entries.append(Entry(e.tile_id, at[0], at[1], e.run))
            write_archive(dst, source, entries, data, len(by_hash))
        return len(moved), before, size
    finally:
        source.close()


# --- The kinds the styles draw ---

def style_kinds(styles):
    """What the layers of [styles] (parsed style JSON) on "landuse" and "pois" ask for by kind."""
    kinds = {name: set() for name in LAYERS}

    def collect(x, into):
        if not isinstance(x, list) or not x:
            return
        # ["in", "kind", a, b], ["==", "kind", a], and the newer ["in", ["get", "kind"], ["literal", [a, b]]].
        if x[0] in ("in", "==") and len(x) > 2 and x[1] in ("kind", ["get", "kind"]):
            for v in x[2:]:
                if isinstance(v, str):
                    into.add(v)
                elif isinstance(v, list) and v and v[0] == "literal":
                    into.update(s for s in v[1] if isinstance(s, str))
            return
        for y in x:
            collect(y, into)

    for style in styles:
        for layer in style.get("layers", []):
            name = layer.get("source-layer")
            if name in kinds:
                if "filter" not in layer:
                    raise ValueError(f"layer {layer.get('id')} draws all of {name}: nothing can be dropped from it")
                collect(layer["filter"], kinds[name])
    return {name: sorted(k) for name, k in kinds.items()}


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("filter")
    f.add_argument("src")
    f.add_argument("dst")
    f.add_argument("--kinds", default=str(KINDS))
    k = sub.add_parser("kinds")
    k.add_argument("styles", nargs="+")
    a = p.parse_args()
    if a.cmd == "kinds":
        print(json.dumps(style_kinds([json.loads(Path(s).read_text()) for s in a.styles]), indent=1))
        return
    doc = json.loads(Path(a.kinds).read_text())
    kinds = {name: set(doc[name]) for name in LAYERS}
    tiles, before, after = filter_archive(a.src, a.dst, kinds)
    print(f"{Path(a.dst).name}: {tiles} tile, {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB "
          f"({100 * (before - after) / max(before, 1):.0f}% in meno)")


if __name__ == "__main__":
    main()
