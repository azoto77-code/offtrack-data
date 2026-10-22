"""Checks that the points of the offline zones are read as Overpass.kt reads them in the app."""
import unittest

from poi_squares import Points, entry, kind_of, square_name


class KindsTest(unittest.TestCase):
    def test_the_first_matching_kind_wins(self):
        self.assertEqual(kind_of({"amenity": "fuel", "shop": "convenience"}), ("fuel", None))
        self.assertEqual(kind_of({"tourism": "alpine_hut"}), ("alpine_hut", None))
        self.assertEqual(kind_of({"mountain_pass": "yes", "natural": "saddle"}), ("mountain_pass", None))
        self.assertIsNone(kind_of({"amenity": "bench"}))

    def test_every_tag_of_a_kind_is_needed(self):
        self.assertIsNone(kind_of({"man_made": "water_tap"}))
        self.assertEqual(kind_of({"man_made": "water_tap", "drinking_water": "yes"}), ("water_tap", None))

    def test_gates_and_cameras_are_marked(self):
        self.assertEqual(kind_of({"barrier": "gate"}), ("gate", "track_gate"))
        self.assertEqual(kind_of({"highway": "speed_camera"}), ("speed_camera", "speed_camera"))


class SquaresTest(unittest.TestCase):
    def test_squares_are_named_as_the_valhalla_packs(self):
        self.assertEqual(square_name(44.19, 8.13), "N44E008")
        self.assertEqual(square_name(45.0, 7.0), "N45E007")
        self.assertEqual(square_name(-0.5, -0.5), "S01W001")

    def test_only_the_card_tags_are_kept(self):
        e = entry("w", 22, "camp_site", 44.41, 8.41, {"name": " ", "opening_hours": "Mo-Su", "foo": "bar"})
        self.assertEqual(e, ["w22", "camp_site", 44.41, 8.41, None, {"opening_hours": "Mo-Su"}])


    def test_a_place_wider_than_20_km_is_left_out(self):
        h = Points(cameras=True)
        self.assertTrue(h.fits("w1", (44.40, 8.40, 44.42, 8.42)))
        self.assertFalse(h.fits("w2", (40.0, 8.0, 44.0, 8.1)))
        self.assertFalse(h.fits("r3", None))
        self.assertEqual(h.too_wide, ["w2"])


if __name__ == "__main__":
    unittest.main()
