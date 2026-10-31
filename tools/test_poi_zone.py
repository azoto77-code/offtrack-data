"""Checks that the points of the offline zones are read as Overpass.kt reads them in the app."""
import unittest

from shapely import box

from poi_zone import Points, entry, inside, kind_of
from zone_area import segments, square_name, squares, widen


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


class AreaTest(unittest.TestCase):
    def test_squares_are_named_as_the_valhalla_packs(self):
        self.assertEqual(square_name(44.19, 8.13), "N44E008")
        self.assertEqual(square_name(45.0, 7.0), "N45E007")
        self.assertEqual(square_name(-0.5, -0.5), "S01W001")

    def test_the_border_is_widened_by_five_km_at_least(self):
        w = widen(box(8.0, 44.0, 9.0, 45.0))
        self.assertLess(w.bounds[0], 8.0 - 5 / (111.32 * 0.72))
        self.assertLess(w.bounds[1], 44.0 - 5 / 111.32)
        self.assertGreater(w.bounds[1], 44.0 - 0.1)

    def test_squares_and_segments_of_a_zone(self):
        area = box(7.5, 44.2, 10.2, 44.8)
        self.assertEqual(squares(area), ["N44E007", "N44E008", "N44E009", "N44E010"])
        self.assertEqual(segments(area), ["E10_N40", "E5_N40"])
        self.assertEqual(segments(box(-1, 43, 1, 46)), ["E0_N40", "E0_N45", "W5_N40", "W5_N45"])

    def test_points_outside_the_zone_are_dropped(self):
        rows = {"n1": ["n1", "fuel", 44.3, 8.4, None, {}], "n2": ["n2", "ferry_terminal", 35.78, -5.81, None, {}]}
        self.assertEqual(list(inside(rows, box(7, 43.5, 10, 46))), ["n1"])

    def test_only_the_card_tags_are_kept(self):
        e = entry("w", 22, "camp_site", 44.41, 8.41, {"name": " ", "opening_hours": "Mo-Su", "foo": "bar"})
        self.assertEqual(e, ["w22", "camp_site", 44.41, 8.41, None, {"opening_hours": "Mo-Su"}])

    def test_a_place_wider_than_20_km_is_left_out(self):
        h = Points()
        self.assertTrue(h.fits("w1", (44.40, 8.40, 44.42, 8.42)))
        self.assertFalse(h.fits("w2", (40.0, 8.0, 44.0, 8.1)))
        self.assertFalse(h.fits("r3", None))
        self.assertEqual(h.too_wide, ["w2"])


if __name__ == "__main__":
    unittest.main()
