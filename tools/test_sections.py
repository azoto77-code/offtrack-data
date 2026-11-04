import os
import tempfile
import unittest

import sections
import tutor_pdf

# A motorway along the parallel 44 with its two carriageways 30 m apart, the northern one going east: exits "Albisola"
# at 8.40 and "Celle Ligure" at 8.45 on each, and a camera of MapAtlas near the eastern end.
OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6">
  <node id="1" lat="44.0003" lon="8.38"/>
  <node id="2" lat="44.0003" lon="8.40"><tag k="highway" v="motorway_junction"/><tag k="name" v="Albisola"/></node>
  <node id="3" lat="44.0003" lon="8.425"/>
  <node id="4" lat="44.0003" lon="8.45"><tag k="highway" v="motorway_junction"/><tag k="name" v="Celle Ligure"/></node>
  <node id="5" lat="44.0003" lon="8.47"/>
  <node id="11" lat="44.0" lon="8.47"/>
  <node id="12" lat="44.0" lon="8.45"><tag k="highway" v="motorway_junction"/><tag k="name" v="Celle Ligure"/></node>
  <node id="13" lat="44.0" lon="8.425"/>
  <node id="14" lat="44.0" lon="8.40"><tag k="highway" v="motorway_junction"/><tag k="name" v="Albisola"/></node>
  <node id="15" lat="44.0" lon="8.38"/>
  <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/>
    <tag k="highway" v="motorway"/><tag k="ref" v="A10"/><tag k="maxspeed" v="130"/></way>
  <way id="101"><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="15"/>
    <tag k="highway" v="motorway"/><tag k="ref" v="A10"/><tag k="maxspeed" v="130"/></way>
</osm>
"""

DGT = """<?xml version="1.0" encoding="UTF-8"?>
<d2LogicalModel xmlns="http://datex2.eu/schema/1_0/1_0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <payloadPublication xmlns:_0="http://datex2.eu/schema/1_0/1_0">
    <_0:predefinedLocationSet id="GUID_Inventario_CinemometrosVelocidadMedia">
      <_0:predefinedLocation id="GUID_CVM_1">
        <_0:predefinedLocation xsi:type="_0:Linear">
          <_0:tpeglinearLocation>
            <_0:to><_0:pointCoordinates><_0:latitude>44.0001</_0:latitude><_0:longitude>8.401</_0:longitude></_0:pointCoordinates></_0:to>
            <_0:from><_0:pointCoordinates><_0:latitude>44.0001</_0:latitude><_0:longitude>8.449</_0:longitude></_0:pointCoordinates></_0:from>
          </_0:tpeglinearLocation>
          <_0:referencePoint><_0:roadNumber>A-10</_0:roadNumber></_0:referencePoint>
        </_0:predefinedLocation>
      </_0:predefinedLocation>
    </_0:predefinedLocationSet>
    <_0:predefinedLocationSet id="GUID_Inventario_CabinasCinemometro">
      <_0:predefinedLocation id="GUID_CABINACINEMOMETRO_7">
        <_0:predefinedLocation xsi:type="_0:Point">
          <_0:tpegpointLocation>
            <_0:point><_0:pointCoordinates><_0:latitude>40.5</_0:latitude><_0:longitude>-3.7</_0:longitude></_0:pointCoordinates></_0:point>
          </_0:tpegpointLocation>
        </_0:predefinedLocation>
      </_0:predefinedLocation>
    </_0:predefinedLocationSet>
  </payloadPublication>
</d2LogicalModel>
"""


class SectionsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.osm = os.path.join(self.dir.name, "roads.osm")
        with open(self.osm, "w") as f:
            f.write(OSM)

    def tearDown(self):
        self.dir.cleanup()

    def test_names(self):
        self.assertEqual(sections.norm("S.M. CAPUAVETERE"), sections.norm("Santa Maria Capua Vetere"))
        self.assertEqual(sections.norm("SAN DONA'"), sections.norm("San Donà"))
        self.assertEqual(sections.norm("COLLEFFERRO"), "COLLEFERRO")

    def test_lookup_by_first_words(self):
        by = {"SAN DONA DI PIAVE": [1], "ROVIGO": [2], "ROVIGO SUD": [3]}
        self.assertEqual(sections.lookup(by, "SAN DONA'"), [1])
        self.assertEqual(sections.lookup(by, "ROVIGO"), [2])

    def test_polyline(self):
        pts = [(44.1, 8.2), (44.11, 8.21), (-12.3456, -77.0001)]
        self.assertEqual(sections.decode(sections.encode(pts)), pts)
        self.assertEqual(sections.encode([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]), "_p~iF~ps|U_ulLnnqC_mqNvxq`@")

    def test_tutor_both_ways(self):
        tutor = [("ALBISOLA", "CELLE LIGURE", "OVEST", ""), ("CELLE LIGURE", "ALBISOLA", "EST", "")]
        rows, fixed, missing = sections.build(self.osm, tutor=tutor, log=lambda *_: None)
        self.assertEqual(len(rows), 2)
        west, east = rows
        # Albisola to Celle runs east on the northern carriageway: the one-way rule picks it.
        self.assertAlmostEqual(west[2], 44.0003)
        self.assertAlmostEqual(west[3], 8.40)
        self.assertAlmostEqual(east[2], 44.0)
        self.assertAlmostEqual(east[3], 8.45)
        self.assertEqual(west[5]["camera:type"], "average_speed")
        self.assertEqual(west[5]["maxspeed"], "130")
        self.assertAlmostEqual(int(west[5]["section:m"]), 4004, delta=10)
        line = sections.decode(west[5]["section:line"])
        # Straight: only the two ends are kept.
        self.assertEqual(len(line), 2)
        self.assertEqual(west[0], "tutor-albisola-celle-ligure-ovest")
        self.assertEqual(west[4], "Albisola - Celle Ligure")

    def test_tutor_name_not_found(self):
        rows, _, missing = sections.build(self.osm, tutor=[("ALBISOLA", "VARAZZE", "OVEST", "")], log=lambda *_: None)
        self.assertEqual(rows, [])
        self.assertEqual(missing, {"VARAZZE": 1})

    def test_dgt(self):
        xml = os.path.join(self.dir.name, "dgt.xml")
        with open(xml, "w") as f:
            f.write(DGT)
        rows, fixed, _ = sections.build(self.osm, dgt=xml, log=lambda *_: None)
        self.assertEqual(len(rows), 1)
        # From east to west: the southern carriageway, 11 m from the given ends.
        self.assertAlmostEqual(rows[0][2], 44.0)
        self.assertEqual(rows[0][0], "dgt-CVM_1")
        self.assertEqual(rows[0][5]["ref"], "A-10")
        self.assertEqual([f[0] for f in fixed], ["dgt-CABINACINEMOMETRO_7"])

    def test_add_replaces_cameras_at_the_ends(self):
        rows, _, _ = sections.build(self.osm, tutor=[("ALBISOLA", "CELLE LIGURE", "OVEST", "")], log=lambda *_: None)
        points = {
            "n1": ["n1", "speed_camera", 44.0003, 8.4002, None, {"maxspeed": "110"}],
            "mci-9": ["mci-9", "speed_camera", 44.0003, 8.4498, None, {"camera:type": "average_speed"}],
            "n2": ["n2", "speed_camera", 44.0003, 8.43, None, {}],
            "n3": ["n3", "fuel", 44.0003, 8.40, None, {}],
        }
        self.assertEqual(sections.add(points, rows), 2)
        self.assertEqual(sorted(points), ["n2", "n3", "tutor-albisola-celle-ligure-ovest"])
        # The OSM limit of the way wins over the camera's.
        self.assertEqual(points["tutor-albisola-celle-ligure-ovest"][5]["maxspeed"], "130")


class TutorPdfTest(unittest.TestCase):
    def test_rows(self):
        text = """                                   TRATTI AUTOSTRADALI CONTROLLATI CON IL TUTOR

CASERTA NORD DIR NORD                     SANTA MARIA CAPUAVETERE DIR NORD
ORVIETO DIR NORD                          FABRO DIR NORD                              DIR NORD
FIRENZUOLA DIR NORD (A1 VAR)              BADIA DIR NORD (A1 VAR)            A1 Variante di Valico
VALMONTONE DIR NORD                       ALL RAC RM-S A1 S DIR NORD -M
                                                                  DIR OVEST
VALLE DEL RUBICONE                 CESENA DIR NORD
BOLOGNA FIERA DIR SUD              ALL SAN LAZZARODIR SUD
ROVIGO DIR NORD                    BOARA DI NORD
TRAFORO MONTEBIANCO SUD           TRAFORO MONTEBIANCO NORD        DIR FRANCIA
                                 aggiornato al 27 maggio 2026
"""
        self.assertEqual(tutor_pdf.rows_of(text), [
            ("CASERTA NORD", "SANTA MARIA CAPUAVETERE", "NORD", ""),
            ("ORVIETO", "FABRO", "NORD", ""),
            ("FIRENZUOLA", "BADIA", "NORD", "A1 VAR"),
            ("VALMONTONE", "ALL RAC RM-S A1 S", "NORD", ""),
            ("VALLE DEL RUBICONE", "CESENA", "NORD", ""),
            ("BOLOGNA FIERA", "ALL SAN LAZZARO", "SUD", ""),
            ("ROVIGO", "BOARA", "NORD", ""),
            ("TRAFORO MONTEBIANCO SUD", "TRAFORO MONTEBIANCO NORD", "FRANCIA", ""),
        ])


if __name__ == "__main__":
    unittest.main()
