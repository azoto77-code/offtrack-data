"""Checks that the levels of the difficulty map match Levels.kt in the app (the same cases as its DifficultyTest)."""
import unittest

from difficulty_layer import feature, level, prohibited


class LevelsTest(unittest.TestCase):
    def test_levels_follow_the_evaluator_table(self):
        self.assertEqual(level({"highway": "tertiary"})[0], 1)
        self.assertEqual(level({"highway": "track", "tracktype": "grade2"})[0], 2)
        self.assertEqual(level({"highway": "track"})[0], 3)
        self.assertEqual(level({"highway": "track", "tracktype": "grade2", "surface": "rock"})[0], 4)
        self.assertEqual(level({"highway": "path"})[0], 5)
        self.assertEqual(level({"highway": "track", "smoothness": "horrible"})[0], 5)
        self.assertEqual(prohibited({"highway": "track", "motor_vehicle": "no"}), "motor_vehicle=no")
        self.assertIsNone(prohibited({"highway": "path", "motorcycle": "yes"}))

    def test_reasons_and_guesses(self):
        self.assertEqual(level({"highway": "track"}), (3, "highway=track", True))
        self.assertEqual(level({"highway": "unclassified", "surface": "gravel"}), (2, "surface=gravel", False))
        self.assertEqual(level({"highway": "track", "tracktype": "grade1", "surface": "asphalt"})[0], 1)
        # Smoothness raises the level, but "intermediate" leaves asphalt alone.
        self.assertEqual(level({"highway": "track", "tracktype": "grade2", "smoothness": "very_bad"}), (4, "smoothness=very_bad", False))
        self.assertEqual(level({"highway": "secondary", "surface": "asphalt", "smoothness": "intermediate"})[0], 1)
        self.assertEqual(prohibited({"highway": "path"}), "highway=path")
        self.assertIsNone(prohibited({"highway": "track", "access": "no", "motorcycle": "yes"}))


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


if __name__ == "__main__":
    unittest.main()
