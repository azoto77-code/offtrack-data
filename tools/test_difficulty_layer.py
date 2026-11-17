"""Checks that the levels of the difficulty map match Levels.kt in the app (the same cases as its LevelRuleTest), and
the barriers."""
import unittest

from difficulty_layer import barrier_feature, barrier_kind, feature, is_path, level, number, prohibited, value


class LevelsTest(unittest.TestCase):
    def test_asphalt_stays_level_1(self):
        self.assertEqual(level({"highway": "tertiary"})[0], 1)
        self.assertEqual(level({"highway": "track", "tracktype": "grade1", "surface": "asphalt"})[0], 1)
        self.assertEqual(level({"highway": "path", "surface": "asphalt"})[0], 1)
        self.assertEqual(level({"highway": "secondary", "surface": "asphalt", "smoothness": "intermediate"})[0], 1)
        self.assertGreaterEqual(level({"highway": "unclassified", "surface": "asphalt", "smoothness": "very_bad"})[0], 2)
        self.assertGreaterEqual(level({"highway": "track", "tracktype": "grade3", "surface": "concrete"})[0], 2)

    def test_the_weighted_mean_as_levelrule(self):
        # The same cases as LevelRuleTest in the app.
        sale = {"highway": "track", "tracktype": "grade2", "surface": "gravel", "width": "2", "mtb:scale": "0",
                "smoothness": "horrible", "motor_vehicle": "yes"}
        self.assertAlmostEqual(value(sale), 2.65)
        self.assertEqual(level(sale), (3, "smoothness=horrible", False))
        self.assertEqual(level({"highway": "unclassified", "surface": "compacted"})[0], 2)
        self.assertEqual(level({"highway": "track"}), (3, "highway=track", True))
        self.assertTrue(level({"highway": "track", "width": "4"})[2])
        self.assertFalse(level({"highway": "track", "mtb:scale": "1"})[2])
        self.assertEqual(level({"highway": "track", "tracktype": "grade2", "surface": "rock"})[0], 3)
        self.assertEqual(level({"highway": "track", "smoothness": "horrible"})[0], 4)
        self.assertEqual(level({"highway": "path"}), (5, "highway=path", True))
        self.assertAlmostEqual(value({"highway": "path", "tracktype": "grade2"}), 2.43, places=2)

    def test_width_reads_the_number_at_the_start(self):
        self.assertEqual(number("2 m"), 2)
        self.assertEqual(number("2,5"), 2)
        self.assertEqual(number("3.5"), 3.5)
        self.assertEqual(number("largo"), 0)
        self.assertEqual(number(None), 0)

    def test_paths_with_two_clues_are_roads(self):
        wide = {"highway": "path", "tracktype": "grade2", "width": "3"}
        self.assertFalse(is_path(wide))
        self.assertEqual(level(wide)[0], 2)
        self.assertEqual(prohibited(wide), "highway=path")
        self.assertFalse(is_path({"highway": "footway", "tracktype": "grade3", "motor_vehicle": "forestry"}))
        self.assertTrue(is_path({"highway": "path", "tracktype": "grade2"}))
        self.assertTrue(is_path({"highway": "path", "tracktype": "grade2", "motor_vehicle": "no"}))
        self.assertTrue(is_path({"highway": "cycleway", "tracktype": "grade2", "width": "3", "motor_vehicle": "yes"}))

    def test_bans(self):
        self.assertEqual(prohibited({"highway": "track", "motor_vehicle": "no"}), "motor_vehicle=no")
        self.assertIsNone(prohibited({"highway": "path", "motorcycle": "yes"}))
        self.assertEqual(prohibited({"highway": "path"}), "highway=path")
        self.assertIsNone(prohibited({"highway": "track", "access": "no", "motorcycle": "yes"}))


class BarriersTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(barrier_kind({"barrier": "chain"}), "chiuso")
        self.assertEqual(barrier_kind({"barrier": "chain", "motorcycle": "yes"}), "aperto")
        self.assertEqual(barrier_kind({"barrier": "gate"}), "aperto")
        self.assertEqual(barrier_kind({"barrier": "gate", "locked": "yes"}), "chiuso")
        self.assertEqual(barrier_kind({"barrier": "lift_gate", "access": "private"}), "chiuso")
        self.assertEqual(barrier_kind({"barrier": "lift_gate", "access": "private", "motorcycle": "yes"}), "aperto")
        self.assertEqual(barrier_kind({"barrier": "bollard"}), "paletti")
        self.assertEqual(barrier_kind({"barrier": "bollard", "motorcycle": "no"}), "chiuso")
        self.assertIsNone(barrier_kind({"barrier": "kerb"}))
        self.assertIsNone(barrier_kind({"barrier": "cattle_grid"}))

    def test_feature(self):
        f = barrier_feature(5, {"barrier": "gate", "locked": "yes", "foo": "bar"}, 8.1234567, 44.5)
        self.assertEqual(f["geometry"]["coordinates"], [8.123457, 44.5])
        self.assertEqual(f["properties"], {"barrier": "gate", "locked": "yes", "id": 5, "kind": "chiuso"})
        self.assertIsNone(barrier_feature(6, {"barrier": "kerb"}, 8, 44))


class FeatureTest(unittest.TestCase):
    line = [[8.0, 44.0], [8.001, 44.001]]

    def test_asphalt_and_pavements_stay_off_the_map(self):
        self.assertIsNone(feature(1, {"highway": "residential"}, self.line))
        self.assertIsNone(feature(2, {"highway": "path", "surface": "asphalt"}, self.line))
        self.assertIsNone(feature(3, {"highway": "footway", "footway": "sidewalk"}, self.line))
        self.assertIsNone(feature(4, {"highway": "track", "tracktype": "grade3"}, self.line[:1]))

    def test_a_track_keeps_its_tags_and_level(self):
        f = feature(7, {"highway": "track", "tracktype": "grade4", "name": "Strada del colle", "motor_vehicle": "no",
                        "foo": "bar"}, self.line)
        p = f["properties"]
        self.assertEqual(p["lvl"], 4)
        self.assertEqual(p["why"], "tracktype=grade4")
        self.assertEqual(p["banned"], "motor_vehicle=no")
        self.assertEqual(p["name"], "Strada del colle")
        self.assertEqual(p["id"], 7)
        self.assertNotIn("foo", p)
        self.assertNotIn("guess", p)
        self.assertEqual(p["minz"], 11)

    def test_paths_appear_later(self):
        f = feature(8, {"highway": "path", "sac_scale": "mountain_hiking"}, self.line)
        self.assertEqual(f["properties"]["minz"], 12)
        self.assertEqual(f["properties"]["banned"], "highway=path")
        self.assertEqual(f["properties"]["guess"], 1)
        # A path with the clues of a road comes with the roads, still closed without a permit for motorbikes.
        g = feature(9, {"highway": "path", "tracktype": "grade2", "width": "3"}, self.line)
        self.assertEqual(g["properties"]["minz"], 11)
        self.assertEqual(g["properties"]["banned"], "highway=path")


if __name__ == "__main__":
    unittest.main()
