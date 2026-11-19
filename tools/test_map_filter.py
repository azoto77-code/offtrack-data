import json
import struct
import tempfile
import unittest
from pathlib import Path

import map_filter as mf

KINDS = {"landuse": {"forest", "park"}, "pois": {"peak"}}


def value(text):
    return mf.field(1, 2, text.encode())


def number(n):
    return mf.field(5, 0, n)


def feature(tags, fid=None):
    """A point feature with [tags] (indexes of key and value, in pairs) and one MoveTo."""
    out = b"" if fid is None else mf.field(1, 0, fid)
    out += mf.field(2, 2, b"".join(mf.varint(t) for t in tags))
    out += mf.field(3, 0, 1)
    out += mf.field(4, 2, mf.varint(9) + mf.varint(50) + mf.varint(34))
    return out


def layer(name, keys, values, features):
    out = mf.field(1, 2, name.encode())
    for f in features:
        out += mf.field(2, 2, f)
    for k in keys:
        out += mf.field(3, 2, k.encode())
    for v in values:
        out += mf.field(4, 2, v)
    return out + mf.field(5, 0, 4096) + mf.field(15, 0, 2)


def tile(*layers):
    return b"".join(mf.field(3, 2, body) for body in layers)


def read_layer(body):
    """Name, keys, values as text and the features as lists of (key, value) of a layer."""
    name, keys, values, features = None, [], [], []
    for f, w, v in mf.fields(body):
        if f == 1:
            name = v.decode()
        elif f == 3:
            keys.append(v.decode())
        elif f == 4:
            values.append(mf.text_of(v))
        elif f == 2:
            features.append(v)
    out = []
    for feat in features:
        tags = []
        for f, w, v in mf.fields(feat):
            if f == 2:
                i = 0
                while i < len(v):
                    t, i = mf.read_varint(v, i)
                    tags.append(t)
        out.append([(keys[k], values[v]) for k, v in zip(tags[::2], tags[1::2])])
    return name, keys, values, out


def layers_of(data):
    return [v for f, w, v in mf.fields(data) if f == 3]


LANDUSE = layer("landuse", ["kind", "sort_rank"], [value("farmland"), value("forest"), number(7), value("park")], [
    feature([0, 0, 1, 2]), feature([0, 1, 1, 2], fid=5), feature([0, 3]), feature([0, 0])])
ROADS = layer("roads", ["kind"], [value("farmland")], [feature([0, 0])])
POIS = layer("pois", ["kind", "name"], [value("tree"), value("Quercia")], [feature([0, 0, 1, 1])])


class ThinTest(unittest.TestCase):
    def test_keeps_only_the_kinds_drawn(self):
        out = layers_of(mf.thin_tile(tile(LANDUSE), KINDS))
        name, keys, values, features = read_layer(out[0])
        self.assertEqual(name, "landuse")
        self.assertEqual(features, [[("kind", "forest"), ("sort_rank", None)], [("kind", "park")]])
        # Keys and values the dropped features alone used are gone.
        self.assertNotIn("farmland", values)
        self.assertEqual(keys, ["kind", "sort_rank"])

    def test_the_rest_of_a_feature_stays(self):
        out = layers_of(mf.thin_tile(tile(LANDUSE), KINDS))[0]
        kept = [v for f, w, v in mf.fields(out) if f == 2][0]
        parts = {f: v for f, w, v in mf.fields(kept)}
        self.assertEqual(parts[1], 5)
        self.assertEqual(parts[3], 1)
        self.assertEqual(parts[4], mf.varint(9) + mf.varint(50) + mf.varint(34))
        # Extent and version of the layer too.
        rest = {f: v for f, w, v in mf.fields(out) if f in (5, 15)}
        self.assertEqual(rest, {5: 4096, 15: 2})

    def test_other_layers_pass_untouched(self):
        # A road whose kind is "farmland" is still a road.
        self.assertEqual(mf.thin_tile(tile(ROADS), KINDS), tile(ROADS))
        out = mf.thin_tile(tile(ROADS, LANDUSE), KINDS)
        self.assertEqual(layers_of(out)[0], ROADS)

    def test_a_layer_left_empty_goes(self):
        out = layers_of(mf.thin_tile(tile(ROADS, POIS), KINDS))
        self.assertEqual([mf.layer_name(b) for b in out], ["roads"])
        self.assertEqual(mf.thin_tile(tile(POIS), KINDS), b"")

    def test_a_layer_without_kind_goes(self):
        nameless = layer("pois", ["name"], [value("Quercia")], [feature([0, 0])])
        self.assertEqual(mf.thin_tile(tile(nameless), KINDS), b"")


class ArchiveTest(unittest.TestCase):
    def write(self, path, tiles, per_leaf=None):
        """A PMTiles file with [tiles] (id -> tile bytes, not compressed), written as map_filter writes one."""
        entries, data, at = [], bytearray(), {}
        for tile_id in sorted(tiles):
            packed = mf.pack(tiles[tile_id])
            if packed not in at:
                at[packed] = len(data)
                data += packed
            entries.append(mf.Entry(tile_id, at[packed], len(packed), 1))
        root, leaves = mf.directories(entries)
        meta = mf.pack(json.dumps({"vector_layers": []}).encode())
        head = bytearray(b"PMTiles\x03")
        offsets = [mf.HEADER, len(root), mf.HEADER + len(root), len(meta), mf.HEADER + len(root) + len(meta), len(leaves),
                   mf.HEADER + len(root) + len(meta) + len(leaves), len(data)]
        head += struct.pack("<8Q", *offsets) + struct.pack("<3Q", len(entries), len(entries), len(at))
        head += bytes([1, mf.GZIP, mf.GZIP, 1, 0, 15]) + struct.pack("<4i", 70000000, 430000000, 100000000, 450000000)
        head += bytes([10]) + struct.pack("<2i", 85000000, 440000000)
        self.assertEqual(len(head), mf.HEADER)
        Path(path).write_bytes(bytes(head) + root + meta + leaves + bytes(data))

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = f"{d}/in.pmtiles", f"{d}/out.pmtiles"
            self.write(src, {10: tile(ROADS, LANDUSE), 11: tile(ROADS, POIS), 12: tile(ROADS, POIS), 20: tile(LANDUSE)})
            tiles, before, after = mf.filter_archive(src, dst, KINDS)
            self.assertEqual(tiles, 3)
            self.assertLess(after, before)
            out = mf.Archive(dst)
            got = {}
            for e in out.entries():
                for i in range(e.run):
                    got[e.tile_id + i] = mf.unpack(out.tile(e), out.tile_compression)
            self.assertEqual(sorted(got), [10, 11, 12, 20])
            self.assertEqual(got[11], tile(ROADS))
            self.assertEqual(got[12], tile(ROADS))
            self.assertEqual(got[10], mf.thin_tile(tile(ROADS, LANDUSE), KINDS))
            # Two tiles next to each other with the same content: one entry and one copy.
            self.assertEqual([(e.tile_id, e.run) for e in out.entries()], [(10, 1), (11, 2), (20, 1)])
            source = mf.Archive(src)
            self.assertEqual(out.metadata(), source.metadata())
            self.assertEqual(out.tail, source.tail)
            head = out.read(0, mf.HEADER)
            self.assertEqual(struct.unpack_from("<3Q", head, 72), (4, 3, 3))
            out.close()
            source.close()

    def test_the_same_file_twice(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(f"{d}/in.pmtiles", {1: tile(LANDUSE), 2: tile(ROADS)})
            mf.filter_archive(f"{d}/in.pmtiles", f"{d}/a.pmtiles", KINDS)
            mf.filter_archive(f"{d}/in.pmtiles", f"{d}/b.pmtiles", KINDS)
            self.assertEqual(Path(f"{d}/a.pmtiles").read_bytes(), Path(f"{d}/b.pmtiles").read_bytes())

    def test_leaves_when_the_root_is_full(self):
        # Ids far apart and lengths all different do not compress: the root directory overflows its 16 KB.
        entries = [mf.Entry(i * 7919 + (i * i) % 977, i * 100003, 1000 + (i * 7907) % 5003, 1) for i in range(20000)]
        root, leaves = mf.directories(entries)
        self.assertLessEqual(len(root), mf.ROOT_ROOM)
        self.assertGreater(len(leaves), 0)
        pointers = mf.read_directory(mf.unpack(root, mf.GZIP))
        self.assertTrue(all(p.run == 0 for p in pointers))
        back = []
        for p in pointers:
            back += mf.read_directory(mf.unpack(leaves[p.offset:p.offset + p.length], mf.GZIP))
        self.assertEqual([(e.tile_id, e.offset, e.length, e.run) for e in back],
                         [(e.tile_id, e.offset, e.length, e.run) for e in entries])


class StyleTest(unittest.TestCase):
    def test_kinds_of_a_style(self):
        style = {"layers": [
            {"id": "a", "source-layer": "landuse", "filter": ["in", "kind", "forest", "wood"]},
            {"id": "b", "source-layer": "landuse", "filter": ["any", ["==", "kind", "pier"], ["in", "kind", "dam"]]},
            {"id": "c", "source-layer": "pois",
             "filter": ["all", ["in", ["get", "kind"], ["literal", ["peak", "bench"]]], [">=", ["zoom"], 12]]},
            {"id": "d", "source-layer": "roads"},
        ]}
        self.assertEqual(mf.style_kinds([style]), {"landuse": ["dam", "forest", "pier", "wood"], "pois": ["bench", "peak"]})

    def test_a_layer_that_draws_everything_stops_it(self):
        with self.assertRaises(ValueError):
            mf.style_kinds([{"layers": [{"id": "all", "source-layer": "landuse"}]}])

    def test_the_list_in_the_repository(self):
        doc = json.loads(mf.KINDS.read_text())
        self.assertEqual(sorted(doc), ["landuse", "pois"])
        # What the app draws today, and what weighs most among what it does not.
        self.assertIn("forest", doc["landuse"])
        self.assertIn("peak", doc["pois"])
        self.assertIn("garden", doc["pois"])
        for kind in ("farmland", "meadow", "bare_rock", "residential"):
            self.assertNotIn(kind, doc["landuse"])
        for kind in ("tree", "street_lamp", "crossing"):
            self.assertNotIn(kind, doc["pois"])


if __name__ == "__main__":
    unittest.main()
