import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

import zone_index


class PackedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name, "out")
        self.packed = Path(self.tmp.name, "packed")
        self.out.mkdir()
        self.packed.mkdir()
        (self.out / "valhalla.tar").write_bytes(b"tile" * 5000)
        (self.out / "mappa.pmtiles").write_bytes(b"map")
        self.files = {f.name: zone_index.describe(f) for f in self.out.iterdir()}

    def tearDown(self):
        self.tmp.cleanup()

    def test_names_the_copy_of_a_file(self):
        copy = gzip.compress(b"tile" * 5000, mtime=0)
        (self.packed / "valhalla.tar.gz").write_bytes(copy)
        self.assertEqual(zone_index.packed(self.packed, self.files), {"valhalla.tar": {
            "file": "valhalla.tar.gz", "bytes": len(copy), "sha256": hashlib.sha256(copy).hexdigest()}})
        # The file itself stays as it was, whole: it is what an app that knows no copies downloads.
        self.assertEqual(self.files["valhalla.tar"]["bytes"], 20000)
        self.assertNotIn("valhalla.tar.gz", self.files)

    def test_nothing_packed(self):
        self.assertEqual(zone_index.packed(self.packed, self.files), {})

    def test_a_copy_of_no_file_stops_it(self):
        (self.packed / "altro.tar.gz").write_bytes(b"x")
        with self.assertRaises(SystemExit):
            zone_index.packed(self.packed, self.files)

    def test_a_name_already_taken_stops_it(self):
        # poi.json.gz.gz would be fine; a copy called as a file of the zone would be downloaded twice.
        (self.out / "valhalla.tar.gz").write_bytes(b"x")
        files = {f.name: zone_index.describe(f) for f in self.out.iterdir()}
        (self.packed / "valhalla.tar.gz").write_bytes(b"x")
        with self.assertRaises(SystemExit):
            zone_index.packed(self.packed, files)


if __name__ == "__main__":
    unittest.main()
