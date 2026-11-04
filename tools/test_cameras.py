"""Checks the speed cameras of MapAtlas added to those of OpenStreetMap."""
import json
import tempfile
import unittest
from pathlib import Path

import cameras


def feature(lon, lat, cls="spot", limit=None, ref="MCI-IT-1", **extra):
    props = {"ref": ref, "class": cls, **extra}
    if limit is not None:
        props["limitKph"] = limit
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


class RowsTest(unittest.TestCase):
    def test_speed_cameras_only_with_a_believable_limit(self):
        rows = cameras.rows_of([
            feature(8.1, 44.1, limit=50, ref="A"),
            feature(8.2, 44.2, cls="signal", ref="B"),
            feature(8.3, 44.3, cls="corridor", limit=140, ref="C"),
            feature(8.4, 44.4, limit=70, ref="D", reportedInactive=True),
        ], "IT")
        self.assertEqual([r[0] for r in rows], ["mci-A", "mci-C"])
        self.assertEqual(rows[0], ["mci-A", "speed_camera", 44.1, 8.1, None, {"camera:type": "fixed", "source": "MapAtlas", "maxspeed": "50"}])
        # 140 km/h does not exist in Italy: not known.
        self.assertNotIn("maxspeed", rows[1][5])
        self.assertEqual(rows[1][5]["camera:type"], "average_speed")

    def test_reads_every_country_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "IT.geojson").write_text(json.dumps({"features": [feature(8.1, 44.1, limit=50)]}))
            Path(d, "FR.geojson").write_text(json.dumps({"features": [feature(7.1, 43.7, limit=80, ref="MCI-FR-1")]}))
            Path(d, "XX.geojson").write_text("not json")
            self.assertEqual(sorted(r[0] for r in cameras.load(d)), ["mci-MCI-FR-1", "mci-MCI-IT-1"])


class MergeTest(unittest.TestCase):
    def test_osm_wins_and_takes_the_limit_it_lacks(self):
        points = {
            "n1": ["n1", "speed_camera", 44.0, 8.0, None, {}],
            "n2": ["n2", "fuel", 44.5, 8.5, None, {}],
        }
        extra = [
            ["mci-near", "speed_camera", 44.0003, 8.0, None, {"maxspeed": "70", "source": "MapAtlas"}],  # about 33 m
            ["mci-far", "speed_camera", 44.01, 8.0, None, {"source": "MapAtlas"}],
            ["mci-fuel", "speed_camera", 44.5, 8.5, None, {"source": "MapAtlas"}],  # near a fuel station, not a camera
        ]
        added, lent = cameras.merge(points, extra)
        self.assertEqual((added, lent), (2, 1))
        self.assertEqual(points["n1"][5], {"maxspeed": "70"})
        self.assertIn("mci-far", points)
        self.assertNotIn("mci-near", points)

    def test_two_mapatlas_points_together_are_one(self):
        points = {}
        added, _ = cameras.merge(points, [
            ["mci-a", "speed_camera", 44.0, 8.0, None, {}],
            ["mci-b", "speed_camera", 44.0002, 8.0, None, {}],
        ])
        self.assertEqual(added, 1)


if __name__ == "__main__":
    unittest.main()
