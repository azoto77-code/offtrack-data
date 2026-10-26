"""Checks that the search index of the offline zones finds places, streets, house numbers and named points."""
import argparse
import csv
import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

from search_zone import Municipalities, build, names_of, norm, norm_number, poi_kind, search

# A municipality of 0.1 x 0.1 degrees around Bardineto, with a village, two pieces of one street, a door on it, a
# hotel, a hamlet numbered by its own name and a door just outside the zone.
OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6">
  <node id="1" lat="44.10" lon="8.10"/>
  <node id="2" lat="44.10" lon="8.20"/>
  <node id="3" lat="44.20" lon="8.20"/>
  <node id="4" lat="44.20" lon="8.10"/>
  <node id="10" lat="44.15" lon="8.13"><tag k="place" v="village"/><tag k="name" v="Bardineto"/></node>
  <node id="11" lat="44.150" lon="8.140"/>
  <node id="12" lat="44.151" lon="8.141"/>
  <node id="13" lat="44.152" lon="8.142"/>
  <node id="14" lat="44.153" lon="8.143"/>
  <node id="20" lat="44.1515" lon="8.1412">
    <tag k="addr:street" v="Via Roma"/><tag k="addr:housenumber" v="12/A"/>
  </node>
  <node id="21" lat="44.16" lon="8.15">
    <tag k="tourism" v="hotel"/><tag k="name" v="Albergo Città di Bardineto"/>
    <tag k="addr:street" v="Via Roma"/><tag k="addr:housenumber" v="3"/>
  </node>
  <node id="22" lat="44.17" lon="8.16">
    <tag k="addr:place" v="Cascine Sottane"/><tag k="addr:housenumber" v="5"/>
  </node>
  <node id="23" lat="45.50" lon="9.50"><tag k="addr:street" v="Via Lontana"/><tag k="addr:housenumber" v="1"/></node>
  <node id="24" lat="44.18" lon="8.17"><tag k="amenity" v="bench"/></node>
  <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
  <way id="101"><nd ref="11"/><nd ref="12"/><tag k="highway" v="residential"/><tag k="name" v="Via Roma"/></way>
  <way id="102"><nd ref="12"/><nd ref="13"/><nd ref="14"/><tag k="highway" v="residential"/><tag k="name" v="Via Roma"/></way>
  <relation id="1000">
    <member type="way" ref="100" role="outer"/>
    <tag k="type" v="boundary"/><tag k="boundary" v="administrative"/><tag k="admin_level" v="8"/>
    <tag k="name" v="Bardineto"/>
  </relation>
</osm>
"""

POLY = """test
1
   8.0 44.0
   8.3 44.0
   8.3 44.3
   8.0 44.3
END
END
"""


class NormTest(unittest.TestCase):
    def test_words_lose_case_accents_and_signs(self):
        self.assertEqual(norm("Sant'Anna di Valdieri"), "sant anna di valdieri")
        self.assertEqual(norm("Città  di  Castello"), "citta di castello")
        self.assertEqual(norm("Straße"), "strasse")
        self.assertEqual(norm("Cœur-de-Lion"), "coeur de lion")

    def test_house_numbers_compare_without_signs(self):
        self.assertEqual(norm_number("12/A"), "12a")
        self.assertEqual(norm_number("12 a"), "12a")
        self.assertEqual(norm_number("4bis"), "4bis")

    def test_a_name_in_another_script_is_shown_by_its_latin_one(self):
        self.assertEqual(names_of({"name": "مسقط", "name:en": "Muscat", "name:it": "Mascate"}), ("Muscat", ["Mascate"]))
        self.assertEqual(names_of({"name": "Torino", "name:en": "Turin"}), ("Torino", ["Turin"]))
        self.assertEqual(names_of({"name": "مسقط"}), ("مسقط", []))

    def test_only_places_to_ride_to_are_points(self):
        self.assertEqual(poi_kind({"tourism": "hotel"}), "tourism=hotel")
        self.assertEqual(poi_kind({"natural": "peak"}), "natural=peak")
        self.assertIsNone(poi_kind({"natural": "tree"}))
        self.assertIsNone(poi_kind({"highway": "residential"}))


class MunicipalitiesTest(unittest.TestCase):
    def borders(self, **count):
        m = Municipalities()
        for level, n in count.items():
            m.by_level[level[1:]] = [(f"{level}-{i}", None) for i in range(n)]
        return m

    def test_municipalities_where_the_zone_has_them(self):
        m = self.borders(l8=300, l6=20)
        self.assertEqual(m.level, "8")
        self.assertEqual(len(m.found), 300)

    def test_the_wilayat_where_there_are_no_municipalities(self):
        # Oman: governorates at 4, wilayat at 6, a stray few at 8.
        self.assertEqual(self.borders(l8=2, l6=61).level, "6")
        self.assertEqual(self.borders(l6=61).level, "6")

    def test_a_few_borders_are_better_than_none(self):
        self.assertEqual(self.borders(l8=3).level, "8")
        self.assertEqual(self.borders().found, [])


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        d = Path(cls.dir.name)
        (d / "zone.osm").write_text(OSM)
        (d / "test.poly").write_text(POLY)
        with gzip.open(d / "adresses-99.csv.gz", "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["id", "numero", "rep", "nom_voie", "nom_commune", "lon", "lat"])
            w.writerow(["a", "12", "a", "Via Roma", "Bardineto", "8.1500", "44.1600"])
            w.writerow(["b", "7", "", "Via Nuova", "Bardineto", "8.1300", "44.1300"])
            w.writerow(["c", "99999", "", "Lieu-dit", "Bardineto", "8.1300", "44.1300"])
        a = argparse.Namespace(out=d / "ricerca.sqlite", area=d / "test.poly", input=d / "zone.osm",
                               municipalities=d / "zone.osm", ban=[d / "adresses-99.csv.gz"],
                               gzip=d / "ricerca.sqlite.gz")
        build(a)
        cls.db = sqlite3.connect(d / "ricerca.sqlite")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.dir.cleanup()

    def test_a_village_is_found_by_the_start_of_its_name(self):
        self.assertEqual(search(self.db, "bardi")[0][:3], ("Bardineto", "place=village", "Bardineto"))

    def test_one_street_per_name_and_municipality(self):
        rows = [r for r in search(self.db, "via roma") if r[1] == "highway"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "Bardineto")
        # At the middle of the longer of its two pieces.
        self.assertAlmostEqual(rows[0][3], 44.152)

    def test_the_ban_door_wins_over_the_same_door_in_openstreetmap(self):
        name, _, _, lat, lon, door = search(self.db, "via roma 12a bardineto")[0]
        self.assertEqual((name, door), ("Via Roma", "12a"))
        self.assertAlmostEqual(lat, 44.16)

    def test_a_door_in_openstreetmap_only_is_kept(self):
        self.assertEqual(search(self.db, "via roma 3")[0][5], "3")

    def test_a_street_only_the_ban_knows_is_added(self):
        self.assertEqual(search(self.db, "via nuova 7")[0][5], "7")

    def test_a_hamlet_numbered_by_its_name(self):
        name, kind, _, _, _, door = search(self.db, "cascine sottane 5")[0]
        self.assertEqual((name, kind, door), ("Cascine Sottane", "addr:place", "5"))

    def test_a_hotel_is_found_without_accents_and_with_its_municipality(self):
        rows = search(self.db, "albergo citta bardineto")
        self.assertEqual(rows[0][:2], ("Albergo Città di Bardineto", "tourism=hotel"))

    def test_outside_the_zone_and_nameless_benches_are_left_out(self):
        self.assertEqual(search(self.db, "via lontana"), [])
        self.assertEqual(self.db.execute("SELECT count(*) FROM luogo WHERE osm = 'n24'").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT valore FROM meta WHERE chiave = 'civici_ban'").fetchone()[0], "2")

    def test_the_compressed_copy_is_the_same_file(self):
        d = Path(self.dir.name)
        with gzip.open(d / "ricerca.sqlite.gz", "rb") as f:
            self.assertEqual(f.read(), (d / "ricerca.sqlite").read_bytes())


if __name__ == "__main__":
    unittest.main()
