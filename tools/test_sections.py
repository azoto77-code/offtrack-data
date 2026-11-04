import os
import tempfile
import unittest

import sections
import tutor_pdf

# A motorway along the parallel 44 with its two carriageways 30 m apart, the northern one going east: exits "Albisola"
# at 8.40 and "Celle Ligure" at 8.45 on each, "Varazze" at 8.47 on the northern one only. The A12 comes from the north and ends 80 m from it at 8.425, its links
# left out as in the zones. "Rocca" is on the slip road that joins the eastbound carriageway at 8.435; at its eastern end a slip road turns back.
OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6">
  <node id="1" lat="44.0003" lon="8.38"/>
  <node id="2" lat="44.0003" lon="8.40"><tag k="highway" v="motorway_junction"/><tag k="name" v="Albisola"/></node>
  <node id="3" lat="44.0003" lon="8.425"/>
  <node id="6" lat="44.0003" lon="8.435"/>
  <node id="4" lat="44.0003" lon="8.45"><tag k="highway" v="motorway_junction"/><tag k="name" v="Celle Ligure"/></node>
  <node id="5" lat="44.0003" lon="8.47"><tag k="highway" v="motorway_junction"/><tag k="name" v="Varazze"/></node>
  <node id="11" lat="44.0" lon="8.47"/>
  <node id="12" lat="44.0" lon="8.45"><tag k="highway" v="motorway_junction"/><tag k="name" v="Celle Ligure"/></node>
  <node id="13" lat="44.0" lon="8.425"/>
  <node id="14" lat="44.0" lon="8.40"><tag k="highway" v="motorway_junction"/><tag k="name" v="Albisola"/></node>
  <node id="15" lat="44.0" lon="8.38"/>
  <node id="21" lat="44.03" lon="8.425"/>
  <node id="22" lat="44.0010" lon="8.425"/>
  <node id="31" lat="44.0025" lon="8.44"><tag k="highway" v="motorway_junction"/><tag k="name" v="Rocca"/></node>
  <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="6"/><nd ref="4"/><nd ref="5"/>
    <tag k="highway" v="motorway"/><tag k="ref" v="A10"/><tag k="maxspeed" v="130"/></way>
  <way id="101"><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="15"/>
    <tag k="highway" v="motorway"/><tag k="ref" v="A10"/><tag k="maxspeed" v="130"/></way>
  <way id="103"><nd ref="31"/><nd ref="6"/><tag k="highway" v="motorway_link"/><tag k="oneway" v="yes"/><tag k="maxspeed" v="60"/></way>
  <way id="104"><nd ref="5"/><nd ref="11"/><tag k="highway" v="motorway_link"/></way>
  <way id="102"><nd ref="21"/><nd ref="22"/><tag k="highway" v="motorway"/><tag k="ref" v="A12;E80"/></way>
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

    def test_lookup_other_names(self):
        by = {"TERRE DI CANOSSA CAMPEGINE": [1], "CORSO MALTA": [2], "SAN LAZZARO": [3], "RAVENNA": [4],
              "BASSO LODIGIANO": [5], "BARI": [6], "BARI NORD": [7]}
        self.assertEqual(sections.lookup(by, "CAMPEGINE"), [1])
        self.assertEqual(sections.lookup(by, "VIADOTTO CORSO MALTA"), [2])
        self.assertEqual(sections.lookup(by, "ALL SAN LAZZARO"), [3])
        self.assertEqual(sections.lookup(by, "ALL. RAVENNA SUD"), [4])
        self.assertEqual(sections.lookup(by, "PIACENZA NORD"), [5])
        self.assertEqual(sections.lookup(by, "BARI NORD"), [7])
        # An interchange by the numbers of its motorways is not a place.
        self.assertEqual(sections.lookup(by, "ALL A15 A1 N"), [])

    def test_lookup_a_name_held_before_a_shorter_one(self):
        by = {"BOLOGNA": [1], "CASTEL MAGGIORE BOLOGNA INTERPORTO": [2], "RAVENNA": [4]}
        self.assertEqual(sections.lookup(by, "BOLOGNA INTERPORTO"), [2])
        self.assertEqual(sections.lookup(by, "RAVENNA SUD"), [4])

    def test_lookup_not_a_name_with_two_more_words(self):
        by = {"SAN GIORGIO": [1], "A4": [2], "ALTEDO": [3]}
        self.assertEqual(sections.lookup(by, "SAN GIORGIO DI NOGARO"), [])
        self.assertEqual(sections.lookup(by, "NODO A4/A23"), [])
        self.assertEqual(sections.lookup(by, "ALTEDO MALALBERGO"), [3])

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

    def test_interchange_names(self):
        self.assertEqual(sections.interchange("ALL A15 A1 N"), ("A15", "A1"))
        self.assertEqual(sections.interchange("NODO A4/A23"), ("A4", "A23"))
        self.assertEqual(sections.interchange("ALL RAC RM-S A1 S"), ("A1DIR", "A1"))
        self.assertIsNone(sections.interchange("ALL SAN LAZZARO"))
        self.assertIsNone(sections.interchange("ALL. RAVENNA SUD"))

    def test_tutor_from_an_interchange(self):
        rows, _, missing = sections.build(self.osm, tutor=[("ALL A12 A10 N", "CELLE LIGURE", "OVEST", "")], log=lambda *_: None)
        self.assertEqual(missing, {})
        self.assertEqual(len(rows), 1)
        # From where the A12 comes nearest, on the carriageway going east.
        self.assertAlmostEqual(rows[0][2], 44.0003)
        self.assertAlmostEqual(rows[0][3], 8.425, places=3)
        self.assertAlmostEqual(int(rows[0][5]["section:m"]), 2002, delta=20)

    def test_tutor_from_a_slip_road(self):
        rows, _, _ = sections.build(self.osm, tutor=[("ROCCA", "CELLE LIGURE", "EST", "")], log=lambda *_: None)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][2], 44.0025)
        self.assertAlmostEqual(int(rows[0][5]["section:m"]), 1670, delta=30)
        # The slip road's limit is not the stretch's.
        self.assertEqual(rows[0][5]["maxspeed"], "130")

    def test_no_turning_back_on_slip_roads(self):
        # From Rocca westwards the only way is east to the end of the motorway and back: none.
        rows, _, _ = sections.build(self.osm, tutor=[("ROCCA", "ALBISOLA", "OVEST", "")], log=lambda *_: None)
        self.assertEqual(rows, [])

    def test_no_way_much_longer_than_the_straight_line(self):
        # 10 km between ends 2 km apart is a way that turns back somewhere, on any road.
        line = [(44.0, 8.40), (44.09, 8.40), (44.0, 8.4258)]
        self.assertFalse(sections.plausible(None, (20000.0, line, [])))
        self.assertTrue(sections.plausible(None, (4000.0, [(44.0, 8.40), (44.0, 8.4258)], [])))

    def test_tutor_name_not_found(self):
        rows, _, missing = sections.build(self.osm, tutor=[("ALBISOLA", "SPOTORNO", "OVEST", "")], log=lambda *_: None)
        self.assertEqual(rows, [])
        self.assertEqual(missing, {"SPOTORNO": 1})

    def test_tutor_from_the_other_carriageway(self):
        # Westwards from Varazze, mapped on the eastbound carriageway only: the stretch starts across from it.
        rows, _, _ = sections.build(self.osm, tutor=[("VARAZZE", "CELLE LIGURE", "OVEST", "")], log=lambda *_: None)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][2], 44.0)
        self.assertAlmostEqual(rows[0][3], 8.47, places=3)
        self.assertAlmostEqual(int(rows[0][5]["section:m"]), 1602, delta=20)

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
