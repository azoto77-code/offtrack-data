import unittest

import france

LIST = [
    {"id": "20006", "typeLabel": "Radar Vitesse Moyenne", "type": "troncons", "lat": 47.21546, "lng": 6.01039},
    {"id": "101", "typeLabel": "Radar fixe", "type": "fixes", "lat": 49.95842, "lng": 2.85479},
    {"id": "12001", "typeLabel": "Radar discriminant", "type": "discriminants", "lat": 45.361, "lng": 4.2526},
    {"id": "FE110000", "typeLabel": "Radar feu rouge", "type": "feux", "lat": 48.26735, "lng": 4.08897},
    {"id": "FE307501", "typeLabel": "Radar Passage à Niveau", "type": "niveaux", "lat": 44.63, "lng": 4.74},
    {"id": "I_01_001", "typeLabel": "Itinéraire", "type": "itineraire", "lat": 46.18, "lng": 5.24},
    {"id": "bad", "type": "fixes", "lat": None, "lng": 2.0},
]

PAGES = {
    "20006": {"radarroad": "RN57", "radardirection": "Vallorbe vers Nancy", "radartronconkm": "1,8",
              "rulesmesured": [{"name": "Vitesse VL 70"}]},
    "12001": {"radarroad": "RN88", "radardirection": "-", "radartronconkm": "",
              "rulesmesured": [{"name": "Vitesse PL 70"}, {"name": "Vitesse VL 90"}]},
}


class FranceTest(unittest.TestCase):
    def test_only_the_speed(self):
        rows = france.rows_of(LIST)
        self.assertEqual([r[0] for r in rows], ["fr-20006", "fr-101", "fr-12001"])
        self.assertEqual(rows[0][5], {"camera:type": "average_speed", "source": "Sécurité routière"})
        self.assertEqual(rows[1][5]["camera:type"], "fixed")

    def test_details(self):
        rows = france.rows_of(LIST)

        def get(rid):
            if rid not in PAGES:
                raise OSError("404")
            return PAGES[rid]

        self.assertEqual(france.add_details(rows, get=get, workers=2), 2)
        tronc, fixed, disc = rows
        self.assertEqual(tronc[5]["maxspeed"], "70")
        self.assertEqual(tronc[5]["section:m"], "1800")
        self.assertEqual(tronc[5]["direction"], "Vallorbe vers Nancy")
        self.assertNotIn("maxspeed", fixed[5])
        # The limit for cars, not for lorries; "-" is no direction.
        self.assertEqual(disc[5]["maxspeed"], "90")
        self.assertNotIn("direction", disc[5])
        self.assertNotIn("section:m", disc[5])


if __name__ == "__main__":
    unittest.main()
